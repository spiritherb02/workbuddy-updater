# WorkBuddy Linux版安装与更新助手

给 Linux 的 **一键式安装 / 更新工具**——检查、下载并安装 WorkBuddy 官方 Linux 版（deb）。

## 为什么开发这个

WorkBuddy 官方**不在官网直接提供 Linux 版安装包**——只向统信 UOS 应用商店和银河麒麟应用商店提供官方版本。但实际上，**官网的服务端上是存在 Linux 版本的**。

本项目利用了这一点：直接对接 WorkBuddy 官方的更新 / 分发接口，把"官方 Linux 版"原样交到你手上——**一条命令完成安装，之后一键更新**。不依赖任何第三方镜像，下载地址来自腾讯官方 CDN，SHA256 由官方接口给出并逐包校验。

### 技术细节

更新接口（官方）：

```
https://copilot.tencent.com/v2/update?platform=workbuddy-linux-x64-deb&version=<已安装版本>
```

- 有新版本：返回 JSON（版本、deb 直链、SHA256）
- 已是最新：HTTP 204
- 下载地址来自 `download.codebuddy.cn`（官方 CDN），安装走本机的 `debinstall`（debinstaller，deb → pacman 包转换器）

## 功能

- 检查更新（启动时自动检查 + 手动检查）
- 显示已安装 / 最新版本
- 下载安装包（带 SHA256 校验、断点续传由 CDN 支持，缓存避免重复下载）
- 一键安装 / 更新：自动安装依赖、执行官方 postinst（软链、chrome-sandbox 权限、桌面数据库刷新），安装过程日志实时显示
- 安装 WorkBuddy（未安装时按钮自动变成「安装 WorkBuddy」）
- 每日自动检查（systemd 用户定时器 + 桌面通知）
- 无 GUI 的 CLI 模式，方便脚本和定时器调用

## 安装

```bash
sudo ./install.sh          # 安装到 /usr/local（含桌面图标和菜单项）
./install.sh --user        # 以桌面用户身份启用每日自动检查
```

依赖：Python 3 + PyQt6（`pacman -S python-pyqt6`）、`debinstall`（debinstaller，已装于 `/usr/local/bin/debinstall`）、polkit（pkexec）。

## 使用

图形界面（开始菜单搜索「WorkBuddy 更新助手」），或命令行：

```bash
workbuddy-updater --check            # 检查更新：退出码 10 = 有更新
workbuddy-updater --check --json     # 机器可读
workbuddy-updater --installed        # 显示已安装版本
workbuddy-updater --download         # 只下载最新 deb
workbuddy-updater --install-latest   # 下载并安装
workbuddy-updater --install foo.deb  # 安装指定 deb
workbuddy-updater --auto             # 静默检查，有更新则发系统通知（定时器用）
```

## 工作原理 / 文件位置

| 内容 | 路径 |
| --- | --- |
| 状态（已安装完整版本号） | `~/.local/share/workbuddy-updater/state.json` |
| 日志 | `~/.local/share/workbuddy-updater/updater.log` |
| deb 缓存 | `~/.cache/workbuddy-updater/` |
| 每日检查定时器 | `~/.config/systemd/user/workbuddy-updater-check.{service,timer}` |

从 app.asar 读到的版本只有 `5.5.4` 这种短版本，完整构建号（`5.5.4.38151288`）由安装时记录在 state.json 里，用于和接口精确比较；首次遇到短版本时会自动按前缀判断，不会误报更新。

## 卸载

```bash
sudo ./install.sh --uninstall        # 移除程序（定时器一并停用）
rm -rf ~/.local/share/workbuddy-updater ~/.cache/workbuddy-updater
```

## 注意

- 安装/更新需要 root 权限，GUI 下通过 polkit（pkexec）弹窗授权
- 更新时 WorkBuddy 会被安装脚本自动关闭
- 接口和 CDN 都是腾讯官方地址，SHA256 由接口给出并在下载后校验
- 本项目只做「取回官方包 + 帮你装好」，不修改、不重新打包 WorkBuddy 本身

## 测试

```bash
python3 tests/run_tests.py
```

## License

MIT
