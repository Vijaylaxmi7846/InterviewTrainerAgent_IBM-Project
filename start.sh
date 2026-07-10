#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  start.sh — Start InterviewTrainer Agent and open browser automatically
# ─────────────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")"

VENV_PYTHON="$(pwd)/venv/bin/python3"
PORT=8081
URL="http://localhost:$PORT"

# ── Kill anything on port 8081 ───────────────────────────────────────────────
OLD_PID=$(lsof -ti :$PORT 2>/dev/null)
if [ -n "$OLD_PID" ]; then
  echo "  Stopping old process on port $PORT (PID $OLD_PID)..."
  kill -9 $OLD_PID 2>/dev/null
  sleep 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║        IBM InterviewTrainer Agent — Starting...          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  ⏳ Loading AI model (~12 seconds, please wait)..."
echo ""

# ── Start app in background ──────────────────────────────────────────────────
PORT=$PORT "$VENV_PYTHON" app.py &
APP_PID=$!

# ── Wait until port is actually listening ────────────────────────────────────
MAX_WAIT=60
WAITED=0
while ! lsof -ti :$PORT > /dev/null 2>&1; do
  sleep 1
  WAITED=$((WAITED + 1))
  if [ $WAITED -ge $MAX_WAIT ]; then
    echo "  ❌ App failed to start after ${MAX_WAIT}s. Check for errors above."
    exit 1
  fi
done

# Give Flask 1 extra second to fully bind
sleep 1

echo "  ✅ App is LIVE on $URL"
echo ""
echo "  Opening browser..."
echo ""
echo "  ┌─────────────────────────────────────────────────────┐"
echo "  │   URL → $URL                         │"
echo "  │   Press Ctrl+C here to stop the server              │"
echo "  └─────────────────────────────────────────────────────┘"
echo ""

# ── Open browser automatically ───────────────────────────────────────────────
open "$URL" 2>/dev/null || echo "  Open your browser manually: $URL"

# ── Keep script alive (logs will stream here) ────────────────────────────────
wait $APP_PID
