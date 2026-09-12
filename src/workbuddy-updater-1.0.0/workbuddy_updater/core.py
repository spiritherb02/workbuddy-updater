"""核心逻辑：版本检测、更新检查、下载、安装。"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from . import __version__

API_URL = "https://copilot.tencent.com/v2/update"
PLATFORM = "workbuddy-linux-x64-deb"
PKGNAME = "workbuddy"

INSTALL_DIR = Path("/opt/WorkBuddy")
APP_BIN = Path("/usr/bin/workbuddy")
ASAR = INSTALL_DIR / "resources" / "app.asar"
DEBINSTALL = Path("/usr/local/bin/debinstall")

TIMER_UNIT = "workbuddy-updater-check.timer"
USER_AGENT = f"WorkBuddy-Updater/{__version__} ({platform.system()} {platform.machine()})"


class UpdaterError(Exception):
    """可以直接展示给用户的错误。"""


@dataclass
class Release:
    version: str
    url: str
    sha256: str = ""
    product_version: str = ""

    @property
    def filename(self) -> str:
        return (
            os.path.basename(urllib.parse.urlparse(self.url).path)
            or f"WorkBuddy-linux-x64-deb-{self.version}.deb"
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- 路径 / 状态

def state_dir() -> Path:
    override = os.environ.get("WORKBUDDY_UPDATER_STATE_DIR")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "workbuddy-updater"


def cache_dir() -> Path:
    override = os.environ.get("WORKBUDDY_UPDATER_CACHE_DIR")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "workbuddy-updater"


def load_state() -> dict:
    try:
        return json.loads((state_dir() / "state.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), "utf-8")
    tmp.replace(directory / "state.json")


def record_install(version: str, deb: str | os.PathLike[str] = "", source: str = "updater") -> None:
    state = load_state()
    state["installed_version"] = version
    state["installed_at"] = datetime.now().isoformat(timespec="seconds")
    state["installed_deb"] = str(deb)
    state["install_source"] = source
    save_state(state)


def log(message: str) -> str:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    try:
        directory = state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "updater.log", "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    return line


# ------------------------------------------------------------------ 版本检测

def is_installed() -> bool:
    return APP_BIN.exists() or (INSTALL_DIR / "workbuddy").exists() or shutil.which(PKGNAME) is not None


def asar_version() -> str | None:
    """从 Electron app.asar 里读 package.json 的 version（形如 5.5.4）。"""
    try:
        with open(ASAR, "rb") as handle:
            head = handle.read(16)
            if len(head) < 16:
                return None
            header_size = struct.unpack("<I", head[4:8])[0]
            json_size = struct.unpack("<I", head[12:16])[0]
            header = json.loads(handle.read(json_size))
            entry = header.get("files", {}).get("package.json")
            if not entry:
                return None
            handle.seek(8 + header_size + int(entry["offset"]))
            package = json.loads(handle.read(int(entry["size"])))
            return str(package.get("version") or "") or None
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def pacman_version() -> str | None:
    pacman = shutil.which("pacman")
    if not pacman:
        return None
    try:
        result = subprocess.run([pacman, "-Q", PKGNAME], capture_output=True, text=True)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    parts = result.stdout.split()
    if len(parts) < 2:
        return None
    return parts[1].rsplit("-", 1)[0]


def installed_version() -> str | None:
    if not is_installed():
        return None
    state = load_state()
    if state.get("installed_version"):
        return str(state["installed_version"])
    return asar_version() or pacman_version()


def is_same_build(installed: str, latest: str) -> bool:
    """5.5.4（包元数据）与 5.5.4.38151288（完整构建号）视为同一版本。"""
    if not installed or not latest:
        return False
    return installed == latest or latest.startswith(installed + ".")


# -------------------------------------------------------------------- HTTP

def _http_request(url: str, params: dict | None = None, timeout: int = 30) -> tuple[int, bytes]:
    query = urllib.parse.urlencode(params or {})
    full = f"{url}?{query}" if query else url
    request = urllib.request.Request(
        full, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return 204, b""
        raise UpdaterError(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise UpdaterError(f"网络错误：{exc.reason}") from exc


def parse_release(payload: bytes) -> Release | None:
    if not payload.strip():
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise UpdaterError(f"接口返回无法解析：{exc}") from exc
    if not isinstance(data, dict):
        raise UpdaterError("接口返回格式异常")
    if data.get("code"):
        raise UpdaterError(str(data.get("msg") or f"接口错误 code={data['code']}"))
    url = str(data.get("url") or "").strip()
    if not url:
        return None
    if not url.lower().startswith("https://"):
        raise UpdaterError(f"下载地址不是 HTTPS：{url}")
    version = str(data.get("version") or data.get("productVersion") or "")
    return Release(
        version=version,
        url=url,
        sha256=str(data.get("sha256hash") or "").lower(),
        product_version=str(data.get("productVersion") or version),
    )


def check_latest(installed: str | None = None) -> Release | None:
    """返回可用的新版本；已是最新时返回 None。"""
    installed = installed_version() if installed is None else installed
    params: dict[str, str] = {"platform": PLATFORM}
    if installed:
        params["version"] = installed
    status, body = _http_request(API_URL, params)
    if status == 204:
        return None
    release = parse_release(body)
    if release and installed and is_same_build(installed, release.version):
        return None
    return release


# ------------------------------------------------------------------ 下载/安装

def sha256_file(path: str | os.PathLike[str], chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def download(release: Release, progress=None, timeout: int = 60) -> Path:
    """下载 deb（带 SHA256 校验），progress(done, total, speed) 可为 None。"""
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / release.filename

    if dest.exists() and release.sha256 and sha256_file(dest) == release.sha256:
        if progress:
            progress(dest.stat().st_size, dest.stat().st_size, 0)
        return dest

    tmp = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(release.url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            start = time.time()
            last = 0.0
            with open(tmp, "wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if progress and (now - last > 0.2 or done == total):
                        last = now
                        progress(done, total, done / max(now - start, 0.001))
        tmp.replace(dest)
    except (OSError, urllib.error.URLError) as exc:
        tmp.unlink(missing_ok=True)
        raise UpdaterError(f"下载失败：{exc}") from exc

    if release.sha256:
        actual = sha256_file(dest)
        if actual != release.sha256:
            dest.unlink(missing_ok=True)
            raise UpdaterError(
                f"SHA256 校验失败（期望 {release.sha256[:12]}…，实际 {actual[:12]}…）"
            )
    return dest


def install_deb(
    deb: str | os.PathLike[str],
    *,
    use_pkexec: bool = False,
    on_output=None,
) -> int:
    """用 debinstaller 安装/升级 deb，返回进程退出码。"""
    path = Path(deb)
    if not path.is_file():
        raise UpdaterError(f"安装包不存在：{path}")

    tool = DEBINSTALL if DEBINSTALL.exists() else shutil.which("debinstall")
    if not tool:
        raise UpdaterError("未找到 debinstall（debinstaller）工具")

    command: list[str] = []
    if os.geteuid() != 0:
        if use_pkexec:
            pkexec = shutil.which("pkexec")
            if not pkexec:
                raise UpdaterError("需要 pkexec 获取 root 权限（请安装 polkit）")
            command.append(pkexec)
        else:
            command.append("sudo")

    command += [str(tool), "install", "-y", "--install-deps", "--run-scripts", str(path)]
    proc = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if on_output:
            on_output(line)
    code = proc.wait()
    if code == 0:
        version = parse_filename_version(path.name)
        record_install(version or "", path)
        log(f"安装完成：{path.name}（版本 {version or '未知'}）")
    return code


def parse_filename_version(name: str) -> str:
    """WorkBuddy-linux-x64-deb-5.5.4.38151288-1ca4889a.deb -> 5.5.4.38151288"""
    match = re.search(r"WorkBuddy-linux-x64-deb-(.+?)-[0-9a-f]{6,}\.deb$", name, re.I)
    if match:
        return match.group(1)
    match = re.search(r"(\d+(?:\.\d+){2,})", name)
    return match.group(1) if match else ""


# -------------------------------------------------------------- 定时器/通知

def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
    except OSError as exc:
        raise UpdaterError(f"systemctl 调用失败：{exc}") from exc


def timer_enabled() -> bool:
    return _systemctl("is-enabled", TIMER_UNIT).stdout.strip() == "enabled"


def set_timer(enabled: bool) -> None:
    _systemctl("daemon-reload")
    if enabled:
        _systemctl("enable", "--now", TIMER_UNIT)
    else:
        _systemctl("disable", "--now", TIMER_UNIT)


def notify(title: str, body: str) -> None:
    if not shutil.which("notify-send"):
        return
    subprocess.run(
        ["notify-send", "-a", "WorkBuddy 更新助手", "-i", "workbuddy", title, body],
        check=False,
    )


def human_size(num: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(num) < 1024 or unit == "GiB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GiB"
