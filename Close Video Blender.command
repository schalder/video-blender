#!/bin/bash
# Double-click in Finder to stop Video Blender.

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8765}"
PIDFILE="$ROOT/data/server.pid"
STOPPED=0

# Prefer the pid we saved on open
if [[ -f "$PIDFILE" ]]; then
  PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    sleep 0.4
    kill -9 "$PID" 2>/dev/null || true
    STOPPED=1
  fi
  rm -f "$PIDFILE"
fi

# Also clear anything still bound to the port (uvicorn workers, old runs)
PIDS="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
if [[ -n "$PIDS" ]]; then
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
  sleep 0.3
  # shellcheck disable=SC2086
  kill -9 $PIDS 2>/dev/null || true
  STOPPED=1
fi

if [[ "$STOPPED" -eq 1 ]]; then
  osascript -e 'display notification "Video Blender stopped." with title "Video Blender"'
else
  osascript -e 'display notification "Video Blender was not running." with title "Video Blender"'
fi

exit 0
