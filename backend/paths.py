"""Resolve app / resource paths for source runs and frozen installs."""

from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """Install root: project folder in dev, folder next to the executable when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _macos_contents() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if exe.parent.name == "MacOS" and exe.parent.parent.name == "Contents":
        return exe.parent.parent
    return None


def resource_root() -> Path:
    """Where frontend / bundled binaries live (PyInstaller extract dir when frozen)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return app_root()


def frontend_dir() -> Path:
    roots = []
    contents = _macos_contents()
    if contents is not None:
        roots.append(contents / "Resources")
        roots.append(contents / "Frameworks")
    roots.append(resource_root())
    roots.append(app_root())
    for root in roots:
        candidate = root / "frontend"
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
    return resource_root() / "frontend"


def data_dir() -> Path:
    """Writable data beside the app (or in Application Support when packaged as .app)."""
    if getattr(sys, "frozen", False):
        contents = _macos_contents()
        if contents is not None:
            support = Path.home() / "Library" / "Application Support" / "Video Blender"
            support.mkdir(parents=True, exist_ok=True)
            return support
        d = Path(sys.executable).resolve().parent / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = app_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_bin(name: str) -> Path | None:
    """Return a bundled ffmpeg/ffprobe path if present."""
    roots = [resource_root(), app_root()]
    contents = _macos_contents()
    if contents is not None:
        roots.extend([contents / "Frameworks", contents / "Resources", contents / "MacOS"])
    for root in roots:
        for candidate in (root / "bin" / name, root / "bin" / f"{name}.exe", root / name, root / f"{name}.exe"):
            if candidate.is_file():
                return candidate
    return None
