#!/usr/bin/env bash
# stop.sh — kills all chooon-viz processes cleanly
# Usage: ./stop.sh

kill_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti:"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "  Killing processes on port $port ..."
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}

echo ""
echo "  Stopping chooon-viz ..."
kill_port 8765
kill_port 8080
echo "  Done."
echo ""
