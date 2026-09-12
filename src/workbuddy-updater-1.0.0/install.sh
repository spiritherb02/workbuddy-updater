#!/usr/bin/env bash
# WorkBuddy 更新助手 安装脚本
#
#   sudo ./install.sh            # 安装程序到 /usr/local
#   ./install.sh --user          # （桌面用户执行）安装并启用每日自动检查定时器
#   sudo ./install.sh --uninstall
#
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
prefix="${PREFIX:-/usr/local}"

install_root() {
    install -d "$prefix/lib/workbuddy-updater" "$prefix/bin" "$prefix/share/applications"
    rm -rf "$prefix/lib/workbuddy-updater/workbuddy_updater"
    cp -r "$here/workbuddy_updater" "$prefix/lib/workbuddy-updater/"
    find "$prefix/lib/workbuddy-updater" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

    cat > "$prefix/bin/workbuddy-updater" <<EOF
#!/usr/bin/env python3
import sys
sys.path.insert(0, "$prefix/lib/workbuddy-updater")
from workbuddy_updater.cli import main
sys.exit(main())
EOF
    chmod 0755 "$prefix/bin/workbuddy-updater"

    local icon="system-software-update"
    for src in /usr/share/icons/hicolor/256x256/apps/workbuddy.png \
               /opt/WorkBuddy/workbuddy.png \
               /opt/WorkBuddy/resources/app.png; do
        if [[ -f "$src" ]]; then
            install -Dm644 "$src" "$prefix/share/icons/hicolor/256x256/apps/workbuddy-updater.png"
            icon="workbuddy-updater"
            gtk-update-icon-cache -q -t -f "$prefix/share/icons/hicolor" 2>/dev/null || true
            break
        fi
    done
    sed "s|@ICON@|$icon|" "$here/workbuddy-updater.desktop" \
        > "$prefix/share/applications/workbuddy-updater.desktop"
    update-desktop-database "$prefix/share/applications" 2>/dev/null || true

    "$prefix/bin/workbuddy-updater" --installed >/dev/null
    echo "installed: $prefix/bin/workbuddy-updater"
    echo "run './install.sh --user' as your desktop user to enable the daily check timer"
}

install_user() {
    command -v systemctl >/dev/null || { echo "systemd not found" >&2; exit 1; }
    local unit_dir="$HOME/.config/systemd/user"
    mkdir -p "$unit_dir"

    cat > "$unit_dir/workbuddy-updater-check.service" <<EOF
[Unit]
Description=Check for WorkBuddy updates

[Service]
Type=oneshot
ExecStart=$prefix/bin/workbuddy-updater --auto
EOF

    cat > "$unit_dir/workbuddy-updater-check.timer" <<EOF
[Unit]
Description=Daily WorkBuddy update check

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable --now workbuddy-updater-check.timer
    systemctl --user list-timers workbuddy-updater-check.timer --no-pager | head -3
    echo "enabled: workbuddy-updater-check.timer"
}

uninstall_all() {
    rm -f "$prefix/bin/workbuddy-updater"
    rm -rf "$prefix/lib/workbuddy-updater"
    rm -f "$prefix/share/applications/workbuddy-updater.desktop"
    rm -f "$prefix/share/icons/hicolor/256x256/apps/workbuddy-updater.png"
    update-desktop-database "$prefix/share/applications" 2>/dev/null || true
    if [[ -n "${HOME:-}" ]]; then
        systemctl --user disable --now workbuddy-updater-check.timer 2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/workbuddy-updater-check."{service,timer}
        systemctl --user daemon-reload 2>/dev/null || true
    fi
    echo "uninstalled"
}

case "${1:-}" in
    "")            install_root ;;
    --user)        install_user ;;
    --uninstall)   uninstall_all ;;
    *)             echo "usage: $0 [--user|--uninstall]" >&2; exit 2 ;;
esac
