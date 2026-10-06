#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="$HOME/.local/share/caelestia/plugin-runtime/openrgb"
mkdir -p "$RUNTIME" "$HOME/.config/systemd/user" "$HOME/.local/bin"
python3 -m venv "$RUNTIME/venv"
"$RUNTIME/venv/bin/python" -m pip install --upgrade pip >/dev/null
"$RUNTIME/venv/bin/python" -m pip install --upgrade openrgb-python >/dev/null
ln -sfn "$ROOT/scripts/openrgb-control" "$HOME/.local/bin/caelestia-openrgb"
cp "$ROOT/systemd/openrgb-server.service" "$HOME/.config/systemd/user/openrgb-server.service"
cp "$ROOT/systemd/caelestia-openrgb-restore.service" "$HOME/.config/systemd/user/caelestia-openrgb-restore.service"
systemctl --user daemon-reload
systemctl --user disable --now kagami-rgb-restore.service >/dev/null 2>&1 || true
systemctl --user enable --now openrgb-server.service
systemctl --user enable --now caelestia-openrgb-restore.service
printf 'OpenRGB plugin runtime installed.\n'
