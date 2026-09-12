"""PyQt6 桌面界面。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, core

APP_NAME = "WorkBuddy 更新助手"
WEBSITE = "https://www.codebuddy.cn/work/"


class CheckWorker(QThread):
    result = pyqtSignal(object)
    error = pyqtSignal(str)

    def run(self) -> None:  # noqa: D102
        try:
            self.result.emit(core.check_latest())
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class DownloadWorker(QThread):
    progress = pyqtSignal(int, int, float)
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, release: core.Release) -> None:
        super().__init__()
        self.release = release

    def run(self) -> None:  # noqa: D102
        try:
            self.done.emit(
                core.download(
                    self.release,
                    lambda done, total, speed: self.progress.emit(done, total, speed),
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class InstallWorker(QThread):
    line = pyqtSignal(str)
    done = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, deb: Path) -> None:
        super().__init__()
        self.deb = deb

    def run(self) -> None:  # noqa: D102
        try:
            self.done.emit(
                core.install_deb(self.deb, use_pkexec=True, on_output=self.line.emit)
            )
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


def app_icon() -> QIcon:
    for name in ("workbuddy", "workbuddy-updater", "system-software-update"):
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QIcon()


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.release: core.Release | None = None
        self.deb: Path | None = None
        self.worker: QThread | None = None
        self._install_after_download = False
        self._busy_count = 0

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(640, 560)
        self._build_ui()
        self.refresh_versions()
        if not os.environ.get("WORKBUDDY_UPDATER_NO_AUTOCHECK"):
            QTimer.singleShot(400, self.check_updates)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 12)
        layout.setSpacing(12)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(app_icon().pixmap(56, 56))
        header.addWidget(icon_label)
        title_box = QVBoxLayout()
        title = QLabel("WorkBuddy")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        subtitle = QLabel("更新助手 · 官方 deb 更新源")
        subtitle.setStyleSheet("color: palette(mid);")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        layout.addLayout(header)

        status_box = QGroupBox("版本状态")
        form = QFormLayout(status_box)
        self.lbl_installed = QLabel("—")
        self.lbl_latest = QLabel("—")
        self.lbl_state = QLabel("尚未检查")
        self.lbl_state.setStyleSheet("font-weight: 600;")
        form.addRow("已安装版本", self.lbl_installed)
        form.addRow("最新版本", self.lbl_latest)
        form.addRow("状态", self.lbl_state)
        layout.addWidget(status_box)

        buttons = QHBoxLayout()
        self.btn_check = QPushButton("检查更新")
        self.btn_download = QPushButton("下载安装包")
        self.btn_install = QPushButton("安装 / 更新")
        self.btn_launch = QPushButton("启动 WorkBuddy")
        for button in (self.btn_check, self.btn_download, self.btn_install, self.btn_launch):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.chk_auto = QCheckBox("每日自动检查更新（后台 systemd 定时器）")
        layout.addWidget(self.chk_auto)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(190)
        self.log_view.setPlaceholderText("日志…")
        layout.addWidget(self.log_view)

        footer = QHBoxLayout()
        link = QLabel(f'<a href="{WEBSITE}">codebuddy.cn</a> · 数据来自官方更新接口')
        link.setOpenExternalLinks(False)
        link.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        link.setStyleSheet("color: palette(mid);")
        footer.addWidget(link)
        footer.addStretch(1)
        version = QLabel(f"v{__version__}")
        version.setStyleSheet("color: palette(mid);")
        footer.addWidget(version)
        layout.addLayout(footer)

        self.btn_check.clicked.connect(self.check_updates)
        self.btn_download.clicked.connect(lambda: self.start_download(False))
        self.btn_install.clicked.connect(lambda: self.start_download(True))
        self.btn_launch.clicked.connect(self.launch_app)
        self.chk_auto.toggled.connect(self.toggle_timer)

        try:
            self.chk_auto.blockSignals(True)
            self.chk_auto.setChecked(core.timer_enabled())
        except core.UpdaterError:
            self.chk_auto.setEnabled(False)
        finally:
            self.chk_auto.blockSignals(False)

        self._update_buttons()

    def _log(self, message: str) -> None:
        self.log_view.appendPlainText(core.log(message))

    def _set_busy_ui(self, busy: bool) -> None:
        for button in (self.btn_check, self.btn_download, self.btn_install, self.btn_launch):
            button.setEnabled(not busy)
        if not busy:
            self._update_buttons()

    def _enter_busy(self) -> None:
        self._busy_count += 1
        self._set_busy_ui(True)

    def _leave_busy(self) -> None:
        self._busy_count = max(0, self._busy_count - 1)
        if self._busy_count == 0:
            self._set_busy_ui(False)

    def _update_buttons(self) -> None:
        installed = core.installed_version()
        self.btn_launch.setEnabled(bool(installed))
        has_update = self.release is not None
        self.btn_download.setEnabled(has_update and self.deb is None)
        self.btn_install.setEnabled(has_update)
        if not installed:
            self.btn_install.setText("安装 WorkBuddy")
        elif has_update and self.release:
            self.btn_install.setText(f"更新到 {self.release.version}")
        else:
            self.btn_install.setText("已是最新")

    def refresh_versions(self) -> None:
        installed = core.installed_version()
        self.lbl_installed.setText(installed or "未安装")

    # -------------------------------------------------------------- actions

    def check_updates(self) -> None:
        self._enter_busy()
        self.lbl_state.setText("正在检查…")
        self._log("开始检查更新…")
        self.worker = CheckWorker()
        self.worker.result.connect(self._on_check_result)  # type: ignore[attr-defined]
        self.worker.error.connect(self._on_error)  # type: ignore[attr-defined]
        self.worker.finished.connect(self._leave_busy)  # type: ignore[attr-defined]
        self.worker.start()  # type: ignore[attr-defined]

    def _on_check_result(self, release: core.Release | None) -> None:
        self.refresh_versions()
        self.release = release
        if release is None:
            self.lbl_latest.setText(core.installed_version() or "—")
            self.lbl_state.setText("✅ 已是最新")
            self._log("已是最新版本")
        else:
            self.lbl_latest.setText(release.version)
            self.lbl_state.setText(f"⬆ 发现新版本 {release.version}")
            self._log(f"发现新版本：{release.version}  {release.url}")
        self.deb = None
        self._update_buttons()

    def start_download(self, install_after: bool) -> None:
        if self.release is None:
            return
        self._install_after_download = install_after
        self._enter_busy()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._log(f"开始下载 {self.release.filename}")
        self.worker = DownloadWorker(self.release)
        self.worker.progress.connect(self._on_download_progress)  # type: ignore[attr-defined]
        self.worker.done.connect(self._on_download_done)  # type: ignore[attr-defined]
        self.worker.error.connect(self._on_error)  # type: ignore[attr-defined]
        self.worker.finished.connect(self._leave_busy)  # type: ignore[attr-defined]
        self.worker.start()  # type: ignore[attr-defined]

    def _on_download_progress(self, done: int, total: int, speed: float) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.progress.setFormat(
                f"下载中 {done * 100 // total}%  "
                f"{core.human_size(done)}/{core.human_size(total)}  "
                f"{core.human_size(speed)}/s"
            )
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat(f"下载中 {core.human_size(done)}")

    def _on_download_done(self, path) -> None:
        self.deb = Path(path)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("下载完成")
        self._log(f"下载完成：{path}")
        self._update_buttons()
        pending = self._install_after_download
        self._install_after_download = False
        if pending:
            self.start_install()

    def start_install(self) -> None:
        if self.deb is None:
            self._install_after_download = True
            self.start_download(True)
            return
        if not self.deb.is_file():
            QMessageBox.warning(self, APP_NAME, f"安装包不存在：{self.deb}")
            return
        answer = QMessageBox.question(
            self,
            APP_NAME,
            "将安装/更新 WorkBuddy。\n\n安装过程中 WorkBuddy 会被关闭（由安装脚本处理），"
            "需要输入管理员密码（polkit）。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._enter_busy()
        self.progress.setRange(0, 0)
        self.progress.setFormat("正在安装…（可能需要几分钟）")
        self._log("开始安装，等待管理员授权…")
        self.worker = InstallWorker(self.deb)
        self.worker.line.connect(lambda line: self.log_view.appendPlainText(line))  # type: ignore[attr-defined]
        self.worker.done.connect(self._on_install_done)  # type: ignore[attr-defined]
        self.worker.error.connect(self._on_error)  # type: ignore[attr-defined]
        self.worker.finished.connect(self._leave_busy)  # type: ignore[attr-defined]
        self.worker.start()  # type: ignore[attr-defined]

    def _on_install_done(self, code: int) -> None:
        self.progress.setRange(0, 100)
        if code == 0:
            self.progress.setValue(100)
            self.progress.setFormat("安装完成")
            self._log("安装完成 ✔")
            self.deb = None
            self.refresh_versions()
            QTimer.singleShot(500, self.check_updates)
        else:
            self.progress.setValue(0)
            self.progress.setFormat(f"安装失败（退出码 {code}）")
            self._log(f"安装失败，退出码 {code}")

    def _on_error(self, message: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("出错")
        self._log(f"错误：{message}")
        QMessageBox.warning(self, APP_NAME, message)

    def launch_app(self) -> None:
        binary = core.APP_BIN
        if not binary.exists():
            QMessageBox.warning(self, APP_NAME, "未找到 /usr/bin/workbuddy，WorkBuddy 可能未安装")
            return
        try:
            subprocess.Popen([str(binary)], start_new_session=True)
            self._log("已启动 WorkBuddy")
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"启动失败：{exc}")

    def toggle_timer(self, checked: bool) -> None:
        try:
            core.set_timer(checked)
            self._log(f"每日自动检查已{'开启' if checked else '关闭'}")
        except core.UpdaterError as exc:
            QMessageBox.warning(self, APP_NAME, f"设置定时器失败：{exc}")
            self.chk_auto.blockSignals(True)
            self.chk_auto.setChecked(not checked)
            self.chk_auto.blockSignals(False)


def run() -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    return app.exec()


def smoke_test() -> int:
    """无头环境下验证界面可以正常构建。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("WORKBUDDY_UPDATER_NO_AUTOCHECK", "1")
    app = QApplication(sys.argv[:1])
    window = MainWindow()
    window.show()
    QTimer.singleShot(600, app.quit)
    return app.exec()
