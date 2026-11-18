#!/bin/bash
# Double-click in Finder to start Video Blender and open it in your browser.

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
PORT="${PORT:-8765}"
URL="http://127.0.0.1:${PORT}"

# Already running? Just open the browser.
if curl -sf "${URL}/api/health" >/dev/null 2>&1; then
  open "$URL"
  osascript -e 'display notification "Video Blender is already running." with title "Video Blender"'
  exit 0
fi

if [[ ! -d .venv ]]; then
  /usr/bin/python3 -m venv .venv || {
    osascript -e 'display alert "Video Blender" message "Could not create Python virtualenv." as critical'
    exit 1
  }
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

export PYTHONPATH="$ROOT"

# Start server in background, log to data/
mkdir -p data
LOG="$ROOT/data/server.log"
PIDFILE="$ROOT/data/server.pid"

nohup python3 -m uvicorn backend.main:app --host 127.0.0.1 --port "$PORT" \
  >"$LOG" 2>&1 &
echo $! >"$PIDFILE"

# Wait until health responds
for _ in $(seq 1 40); do
  if curl -sf "${URL}/api/health" >/dev/null 2>&1; then
    open "$URL"
    osascript -e 'display notification "App opened in your browser." with title "Video Blender"'
    exit 0
  fi
  sleep 0.25
done

osascript -e 'display alert "Video Blender" message "Server did not start. Check data/server.log" as critical'
exit 1
