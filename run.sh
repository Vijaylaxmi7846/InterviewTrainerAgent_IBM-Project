#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  run.sh  —  Always-correct launcher for InterviewTrainer Agent
#  Usage:  bash run.sh          (or: chmod +x run.sh && ./run.sh)
# ─────────────────────────────────────────────────────────────────────────────

# Navigate to the project directory (works even if called from elsewhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"

# ── 1. Check venv exists ─────────────────────────────────────────────────────
if [ ! -f "$VENV_PYTHON" ]; then
  echo "ERROR: venv not found. Creating it now..."
  python3 -m venv venv
  venv/bin/pip install --quiet -r requirements.txt
  echo "Done."
fi

# ── 2. Check Flask is installed inside venv ──────────────────────────────────
if ! "$VENV_PYTHON" -c "import flask" 2>/dev/null; then
  echo "Installing dependencies into venv..."
  venv/bin/pip install --quiet -r requirements.txt
fi

# ── 3. Copy .env.example → .env if .env missing ─────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
  echo "Created .env from .env.example — add your IBM credentials when ready."
fi

# ── 4. Find a free port (avoids AirPlay 5000, 5001, 8080) ───────────────────
find_free_port() {
  for port in 8081 8082 8888 9000 9001 3001; do
    lsof -ti :$port > /dev/null 2>&1 || { echo $port; return; }
  done
  echo 8081  # fallback
}

PORT="${PORT:-$(find_free_port)}"
export PORT

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   IBM InterviewTrainer Agent — starting up...        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Python  : $VENV_PYTHON"
echo "  Port    : $PORT"
echo "  URL     : http://localhost:$PORT"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

# ── 5. Launch ─────────────────────────────────────────────────────────────────
exec "$VENV_PYTHON" app.py
