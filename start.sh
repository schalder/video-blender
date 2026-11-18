#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

export PYTHONPATH="$ROOT"
PORT="${PORT:-8765}"

echo "Video Blender → http://127.0.0.1:${PORT}"
echo "Leave this terminal open. Press Ctrl+C to stop."
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port "$PORT"
