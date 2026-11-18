#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${VERSION:-1.0.0}"
DIST="$ROOT/dist"
STAGE="$DIST/dmg-stage"
DMG="$DIST/Video-Blender-${VERSION}-mac-arm64.dmg"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt pyinstaller

bash packaging/fetch_binaries.sh darwin-arm64

rm -rf build dist/Video\ Blender dist/Video\ Blender.app "$STAGE" "$DMG"
pyinstaller --noconfirm packaging/VideoBlender.spec

APP="$DIST/Video Blender.app"
if [[ ! -d "$APP" ]]; then
  echo "Missing $APP"
  exit 1
fi

# Ad-hoc sign so Gatekeeper is less angry on local machines
codesign --force --deep --sign - "$APP" || true

mkdir -p "$STAGE"
rm -rf "$STAGE"/*
cp -R "$APP" "$STAGE/"
ln -sf /Applications "$STAGE/Applications"

# Simple readme inside the DMG
cat > "$STAGE/Read Me.txt" <<EOF
Video Blender ${VERSION}

1. Drag Video Blender into Applications.
2. Open it (right-click → Open the first time if macOS warns).
3. Activate with your license key from:
   https://flagbattle.powerkits.net/dashboard.html#/video-blender
EOF

hdiutil create -volname "Video Blender" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"

echo ""
echo "Built: $APP"
echo "Built: $DMG"
ls -lh "$DMG"
