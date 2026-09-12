"""命令行入口（GUI 为默认模式）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, core

EXIT_UP_TO_DATE = 0
EXIT_UPDATE_AVAILABLE = 10
EXIT_ERROR = 1


def _emit(payload: dict, as_json: bool, text: str) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(text)


def _cmd_check(as_json: bool) -> int:
    installed = core.installed_version()
    release = core.check_latest()
    if release is None:
        _emit(
            {"status": "up-to-date", "installed": installed},
            as_json,
            f"已是最新版本：{installed or '（未安装）'}",
        )
        return EXIT_UP_TO_DATE
    _emit(
        {"status": "update-available", "installed": installed, **release.to_dict()},
        as_json,
        f"发现新版本：{installed or '未安装'} -> {release.version}\n{release.url}",
    )
    return EXIT_UPDATE_AVAILABLE


def _cmd_auto(as_json: bool) -> int:
    installed = core.installed_version()
    try:
        release = core.check_latest()
    except core.UpdaterError as exc:
        core.log(f"自动检查失败：{exc}")
        _emit({"status": "error", "message": str(exc)}, as_json, f"检查失败：{exc}")
        return EXIT_ERROR
    if release is None:
        core.log("自动检查：已是最新")
        _emit({"status": "up-to-date", "installed": installed}, as_json, "已是最新")
        return EXIT_UP_TO_DATE
    core.log(f"自动检查：发现新版本 {release.version}")
    core.notify(
        "WorkBuddy 有可用更新",
        f"{installed or '未安装'} → {release.version}\n打开「WorkBuddy 更新助手」进行更新",
    )
    _emit({"status": "update-available", "installed": installed, **release.to_dict()}, as_json,
          f"发现新版本：{release.version}")
    return EXIT_UPDATE_AVAILABLE


def _cmd_download(as_json: bool) -> int:
    release = core.check_latest()
    if release is None:
        _emit({"status": "up-to-date"}, as_json, "已是最新，无需下载")
        return EXIT_UP_TO_DATE

    def progress(done: int, total: int, speed: float) -> None:
        if not as_json:
            if total:
                sys.stderr.write(
                    f"\r下载中 {done * 100 // total}%  "
                    f"{core.human_size(done)}/{core.human_size(total)}  "
                    f"{core.human_size(speed)}/s"
                )
            else:
                sys.stderr.write(f"\r下载中 {core.human_size(done)}")
            sys.stderr.flush()

    path = core.download(release, progress)
    if not as_json:
        sys.stderr.write("\n")
    _emit({"status": "downloaded", "path": str(path), **release.to_dict()}, as_json, str(path))
    return 0


def _cmd_install_latest(as_json: bool) -> int:
    release = core.check_latest()
    if release is None:
        _emit({"status": "up-to-date"}, as_json, "已是最新，无需安装")
        return EXIT_UP_TO_DATE
    path = core.download(release)
    code = core.install_deb(path, on_output=None if as_json else print)
    if code != 0:
        _emit({"status": "error", "exit_code": code}, as_json, f"安装失败（退出码 {code}）")
        return code
    _emit({"status": "installed", "version": release.version, "path": str(path)}, as_json,
          f"已安装 {release.version}")
    return 0


def _cmd_install_file(deb: str, as_json: bool) -> int:
    path = Path(deb).expanduser()
    code = core.install_deb(path, on_output=None if as_json else print)
    if code != 0:
        _emit({"status": "error", "exit_code": code}, as_json, f"安装失败（退出码 {code}）")
        return code
    _emit({"status": "installed", "path": str(path)}, as_json, f"已安装：{path.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workbuddy-updater",
        description="WorkBuddy 更新助手：检查、下载并安装官方 deb 更新",
    )
    parser.add_argument("-V", "--version", action="version", version=f"WorkBuddy 更新助手 {__version__}")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="检查更新（退出码 10 表示有更新）")
    group.add_argument("--auto", action="store_true", help="静默检查并有更新时发通知（供定时器使用）")
    group.add_argument("--download", action="store_true", help="下载最新版 deb")
    group.add_argument("--install-latest", action="store_true", help="下载并安装最新版")
    group.add_argument("--install", metavar="DEB", help="安装指定的 deb 文件")
    group.add_argument("--installed", action="store_true", help="显示已安装版本")
    group.add_argument("--record-install", metavar="VERSION", help=argparse.SUPPRESS)
    group.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.installed:
        version = core.installed_version()
        _emit({"installed": version}, args.json, version or "未安装")
        return 0

    if args.record_install:
        core.record_install(args.record_install, source="manual")
        _emit({"recorded": args.record_install}, args.json, f"已记录安装版本 {args.record_install}")
        return 0

    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from .gui import smoke_test

        return smoke_test()

    try:
        if args.check:
            return _cmd_check(args.json)
        if args.auto:
            return _cmd_auto(args.json)
        if args.download:
            return _cmd_download(args.json)
        if args.install_latest:
            return _cmd_install_latest(args.json)
        if args.install:
            return _cmd_install_file(args.install, args.json)
    except core.UpdaterError as exc:
        if args.json:
            print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_ERROR

    from .gui import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
