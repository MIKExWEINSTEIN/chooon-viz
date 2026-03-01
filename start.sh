#!/usr/bin/env bash
# start.sh — launches chooon-viz 2.0
# Usage: ./start.sh
# Press Ctrl+C to stop everything cleanly.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"

# ── Helpers ──────────────────────────────────────────────────────────────────
kill_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti:"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "  Clearing port $port ..."
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}

# ── Sanity check ─────────────────────────────────────────────────────────────
if [ ! -f "$PYTHON" ]; then
  echo ""
  echo "ERROR: virtual environment not found at .venv/"
  echo "Run this first:"
  echo "  cd \"$SCRIPT_DIR\""
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/pip install -r requirements.txt"
  echo ""
  exit 1
fi

echo ""
echo "  chooon-viz 2.0"
echo "  ──────────────"

# ── Clear any stale processes on our ports ───────────────────────────────────
kill_port 8765
kill_port 8080
sleep 0.3

# ── Start audio_server.py in the background ──────────────────────────────────
echo "  Starting audio_server.py ..."
"$PYTHON" "$SCRIPT_DIR/audio_server.py" &
SERVER_PID=$!

# ── Cleanup handler — runs on Ctrl+C or TERM ─────────────────────────────────
cleanup() {
  echo ""
  echo "  Shutting down ..."
  kill "$SERVER_PID" 2>/dev/null || true
  # Belt-and-suspenders: clear ports in case anything lingered
  kill_port 8765
  kill_port 8080
  echo "  Done."
  echo ""
  exit 0
}
trap cleanup INT TERM

# ── Wait for server to come up ───────────────────────────────────────────────
echo "  Waiting for server to initialize ..."
sleep 2

# ── Verify the server actually started ───────────────────────────────────────
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo ""
  echo "ERROR: audio_server.py failed to start. Check output above."
  echo ""
  exit 1
fi

# ── Open Chrome ──────────────────────────────────────────────────────────────
echo "  Opening Chrome ..."
open -a "Google Chrome" "http://localhost:8080/visualizer.html"
open -a "Google Chrome" "http://localhost:8080/controls.html"

# ── Status banner ─────────────────────────────────────────────────────────────
echo ""
echo "  [OK] chooon-viz is running"
echo ""
echo "      WebSocket  :  ws://localhost:8765"
echo "      HTTP       :  http://localhost:8080"
echo "      Visualizer :  http://localhost:8080/visualizer.html"
echo "      Controls   :  http://localhost:8080/controls.html"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

# ── Stay alive and stream server logs to the terminal ────────────────────────
wait "$SERVER_PID"

# If audio_server.py exits on its own (crash), report it
echo ""
echo "  audio_server.py exited unexpectedly."
echo ""
