#!/usr/bin/env bash
# Download static ffmpeg/ffprobe for the current (or requested) platform.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/packaging/bin"
TAG="b6.0"
BASE="https://github.com/eugeneware/ffmpeg-static/releases/download/${TAG}"

OS="${1:-}"
if [[ -z "$OS" ]]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) OS=darwin-arm64 ;;
    Darwin-x86_64) OS=darwin-x64 ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT) OS=win32-x64 ;;
    Linux-x86_64) OS=linux-x64 ;;
    *) echo "Unsupported platform; pass darwin-arm64|darwin-x64|win32-x64|linux-x64"; exit 1 ;;
  esac
fi

mkdir -p "$BIN"
rm -f "$BIN/ffmpeg" "$BIN/ffprobe" "$BIN/ffmpeg.exe" "$BIN/ffprobe.exe"

echo "Fetching ffmpeg (${OS})…"
if [[ "$OS" == win32-x64 ]]; then
  curl -fsSL -o "$BIN/ffmpeg.exe" "${BASE}/ffmpeg-${OS}"
  curl -fsSL -o "$BIN/ffprobe.exe" "${BASE}/ffprobe-${OS}"
  ls -lh "$BIN/ffmpeg.exe" "$BIN/ffprobe.exe"
else
  curl -fsSL -o "$BIN/ffmpeg" "${BASE}/ffmpeg-${OS}"
  curl -fsSL -o "$BIN/ffprobe" "${BASE}/ffprobe-${OS}"
  chmod +x "$BIN/ffmpeg" "$BIN/ffprobe"
  ls -lh "$BIN/ffmpeg" "$BIN/ffprobe"
  "$BIN/ffmpeg" -version | head -1
fi

echo "Binaries ready in packaging/bin"
