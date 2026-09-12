# Maintainer: SpiritHerb <spiritherb@users.noreply.github.com>
pkgname=workbuddy-updater
pkgver=1.0.0
pkgrel=1
pkgdesc="WorkBuddy Linux 版安装与更新助手 — 一键安装/更新 WorkBuddy 官方 Linux 版（.deb）"
arch=('any')
url="https://github.com/spiritherb02/workbuddy-updater"
license=('MIT')
depends=('python' 'python-pyqt6')
optdepends=(
  'debinstaller: 安装/更新 WorkBuddy 本体（deb → pacman 转换器）'
  'polkit: GUI 下弹出授权窗口'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

package() {
  cd "$srcdir/$pkgname-$pkgver"

  install -d "$pkgdir/usr/lib/workbuddy-updater" \
             "$pkgdir/usr/bin" \
             "$pkgdir/usr/share/applications" \
             "$pkgdir/usr/share/icons/hicolor/256x256/apps"

  # Python 包
  cp -r workbuddy_updater "$pkgdir/usr/lib/workbuddy-updater/"
  find "$pkgdir/usr/lib/workbuddy-updater" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

  # 入口（指向系统安装路径）
  cat > "$pkgdir/usr/bin/workbuddy-updater" <<'ENTRY'
#!/usr/bin/env python3
import sys
sys.path.insert(0, "/usr/lib/workbuddy-updater")
from workbuddy_updater.cli import main
sys.exit(main())
ENTRY
  chmod 755 "$pkgdir/usr/bin/workbuddy-updater"

  # 桌面项 + 图标
  sed 's|@ICON@|workbuddy-updater|' workbuddy-updater.desktop \
    > "$pkgdir/usr/share/applications/workbuddy-updater.desktop"
  install -Dm644 icon.png \
    "$pkgdir/usr/share/icons/hicolor/256x256/apps/workbuddy-updater.png"
}
