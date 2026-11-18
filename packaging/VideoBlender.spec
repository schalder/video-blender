# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Video Blender (macOS / Windows)

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
BIN = ROOT / "packaging" / "bin"
FRONTEND = ROOT / "frontend"

datas = [
    (str(FRONTEND), "frontend"),
]

binaries = []
for name in ("ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe"):
    p = BIN / name
    if p.is_file():
        binaries.append((str(p), "bin"))

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "email.mime.text",
    "certifi",
]

a = Analysis(
    [str(ROOT / "desktop" / "run_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Video Blender",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Video Blender",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Video Blender.app",
        icon=None,
        bundle_identifier="net.powerkits.videoblender",
        info_plist={
            "CFBundleName": "Video Blender",
            "CFBundleDisplayName": "Video Blender",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSAppleEventsUsageDescription": "Video Blender needs AppleEvents to open the file picker.",
        },
    )
