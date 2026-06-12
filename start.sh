#!/bin/bash
# Lattice — launcher (post-refactor)
#
# The frontend is now a STATIC build served by the backend at http://<pi>:8000/
# (no Vite dev server). Backend + bot run as systemd services that ALSO autostart
# on boot, so after a reboot you normally don't need to run anything. This script
# (re)starts them on demand and rebuilds the frontend if it hasn't been built yet.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# One-time (or post-update) frontend build — static files served by the backend.
if [ ! -f "$SCRIPT_DIR/frontend/build/index.html" ]; then
  echo "No frontend build found — building (~1 min)..."
  (cd "$SCRIPT_DIR/frontend" && npm run build)
fi

echo "Starting Lattice (backend + bot) via systemd..."
sudo systemctl restart lattice-backend lattice-bot
sleep 4

if systemctl is-active --quiet lattice-backend; then
  echo "  backend: active"
else
  echo "  backend: FAILED — check: journalctl -u lattice-backend -e"
fi
if systemctl is-active --quiet lattice-bot; then
  echo "  bot:     active"
else
  echo "  bot:     FAILED — check: journalctl -u lattice-bot -e"
fi

IP="$(hostname -I | awk '{print $1}')"
echo ""
echo "UI:     http://$IP:8000/"
echo "Health: http://$IP:8000/api/health"
echo "Logs:   journalctl -u lattice-backend -f   (or -u lattice-bot)"
echo "Stop:   sudo systemctl stop lattice-backend lattice-bot"
