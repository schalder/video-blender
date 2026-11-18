"""Local Video Blender API — pick a clip on disk (no copy), export Long_ beside it."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .blender import BlenderError, CancelToken, CancelledError, blend_to_length, probe
from . import license as license_mod
from .paths import data_dir, frontend_dir, resource_root

ROOT = resource_root()
DATA = data_dir()
FRONTEND = frontend_dir()
DATA.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}

jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()

# clip_id -> absolute source path on disk (no duplicate copy)
clips: dict[str, Path] = {}
# latest selection for Finder buttons
session: dict[str, Optional[Path]] = {"input": None, "output": None}

app = FastAPI(title="Video Blender", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _set_job(job_id: str, **fields: Any) -> None:
    with jobs_lock:
        job = jobs.setdefault(job_id, {})
        job.update(fields)


def _get_job(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return dict(job)


def _safe_stem(name: str) -> str:
    stem = Path(name).stem.strip() or "video"
    stem = stem.replace("/", "-").replace("\\", "-").replace("\0", "")
    stem = re.sub(r"[^\w\s.\-()+=@#&]", "_", stem, flags=re.UNICODE)
    stem = re.sub(r"\s+", " ", stem).strip(" ._") or "video"
    return stem


def _long_output_path(source: Path) -> Path:
    """Save next to source as Long_<originalStem>.mp4"""
    stem = _safe_stem(source.name)
    if stem.lower().startswith("long_"):
        out_name = f"{stem}.mp4"
    else:
        out_name = f"Long_{stem}.mp4"
    dest = source.parent / out_name
    if not dest.exists():
        return dest
    n = 1
    while True:
        candidate = source.parent / f"{Path(out_name).stem} ({n}).mp4"
        if not candidate.exists():
            return candidate
        n += 1


def _reveal_in_finder(path: Path) -> None:
    """Open Finder with this file selected."""
    if not path.exists():
        raise HTTPException(404, f"File not found: {path}")
    try:
        subprocess.run(["open", "-R", str(path)], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(500, f"Could not reveal in Finder: {exc}") from exc


def _open_file(path: Path) -> None:
    """Open file with the default Mac app."""
    if not path.is_file():
        raise HTTPException(404, f"File not found: {path}")
    try:
        subprocess.run(["open", str(path)], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(500, f"Could not open file: {exc}") from exc


def _pick_video_path() -> Path:
    """Native macOS file chooser — returns absolute path, no copy."""
    script = """
set theFile to choose file with prompt "Choose a video clip for Video Blender" of type {"public.movie", "public.mpeg-4", "com.apple.quicktime-movie", "mpg", "mp4", "mov", "m4v", "mkv", "avi", "webm"}
return POSIX path of theFile
"""
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise HTTPException(500, f"Could not open file picker: {exc}") from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if "User canceled" in err or "User cancelled" in err or proc.returncode == 1:
            raise HTTPException(400, "File selection cancelled")
        raise HTTPException(500, err or "File picker failed")

    raw = (proc.stdout or "").strip()
    if not raw:
        raise HTTPException(400, "File selection cancelled")
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(400, f"Selected path is not a file: {path}")
    if path.suffix.lower() not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported format. Use: {', '.join(sorted(ALLOWED_EXT))}")
    return path


def _register_clip(path: Path) -> dict[str, Any]:
    try:
        info = probe(path)
    except BlenderError as exc:
        raise HTTPException(400, str(exc)) from exc

    clip_id = uuid.uuid4().hex[:12]
    clips[clip_id] = path
    session["input"] = path
    return {
        "clip_id": clip_id,
        "filename": path.name,
        "path": str(path),
        "folder": str(path.parent),
        "duration": round(info.duration, 3),
        "width": info.width,
        "height": info.height,
        "fps": round(info.fps, 3),
        "has_audio": info.has_audio,
    }


def _resolve_clip(clip_id: str) -> Path:
    path = clips.get(clip_id)
    if path is None or not path.is_file():
        raise HTTPException(404, "Clip not found. Choose a file again.")
    return path


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "Video Blender"}


@app.get("/api/license")
def license_status() -> dict[str, Any]:
    return license_mod.status()


class LicenseActivateBody(BaseModel):
    key: str


@app.post("/api/license/activate")
def license_activate(body: LicenseActivateBody) -> dict[str, Any]:
    result = license_mod.activate(body.key)
    if not result.get("ok"):
        raise HTTPException(400, result.get("message") or "Activation failed")
    return result


@app.post("/api/license/clear")
def license_clear() -> dict[str, Any]:
    license_mod.clear_license()
    return {"ok": True, **license_mod.status()}


@app.post("/api/pick-clip")
async def pick_clip() -> dict[str, Any]:
    """Choose a video on this Mac — no duplicate copy into the app folder."""
    path = _pick_video_path()
    return _register_clip(path)


def _parse_length(raw: str) -> float:
    raw = (raw or "").strip().lower().replace(" ", "")
    if not raw:
        raise ValueError("Enter a target length")
    if ":" in raw:
        parts = raw.split(":")
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        raise ValueError("Use mm:ss or hh:mm:ss")
    if raw.endswith("h"):
        return float(raw[:-1]) * 3600
    if raw.endswith("m"):
        return float(raw[:-1]) * 60
    if raw.endswith("s"):
        return float(raw[:-1])
    return float(raw)


@app.post("/api/create")
async def create(
    clip_id: str = Form(...),
    length: str = Form(...),
    fade: float = Form(0.75),
) -> dict[str, Any]:
    lic = license_mod.require_licensed()
    if not lic.get("licensed"):
        raise HTTPException(
            403,
            lic.get("message") or "Activate a Video Blender license to create long videos.",
        )

    source = _resolve_clip(clip_id)

    try:
        target = _parse_length(length)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if target < 1:
        raise HTTPException(400, "Target length must be at least 1 second")
    if not (0.15 <= fade <= 3.0):
        raise HTTPException(400, "Fade must be between 0.15 and 3 seconds")

    job_id = uuid.uuid4().hex[:12]
    out_path = _long_output_path(source)
    cancel = CancelToken()
    session["input"] = source
    _set_job(
        job_id,
        status="running",
        progress=0,
        message="Starting",
        output=None,
        output_path=None,
        download_name=out_path.name,
        source_name=source.name,
        source_path=str(source),
        error=None,
        result=None,
        cancel=cancel,
    )

    def worker() -> None:
        try:
            os.nice(10)
        except OSError:
            pass
        try:

            def on_progress(pct: float, message: str) -> None:
                if cancel.cancelled:
                    return
                _set_job(job_id, progress=round(pct, 1), message=message, status="running")

            result = blend_to_length(
                source,
                out_path,
                target,
                fade_seconds=fade,
                on_progress=on_progress,
                cancel=cancel,
            )
            if cancel.cancelled:
                out_path.unlink(missing_ok=True)
                _set_job(
                    job_id,
                    status="cancelled",
                    message="Cancelled",
                    error=None,
                    output=None,
                    output_path=None,
                    result=None,
                )
                return
            result = dict(result)
            result["filename"] = out_path.name
            result["folder"] = str(out_path.parent)
            session["output"] = out_path
            _set_job(
                job_id,
                status="done",
                progress=100,
                message="Done",
                output=out_path.name,
                output_path=str(out_path),
                download_name=out_path.name,
                result=result,
            )
        except CancelledError:
            out_path.unlink(missing_ok=True)
            _set_job(
                job_id,
                status="cancelled",
                message="Cancelled",
                error=None,
                output=None,
                output_path=None,
                result=None,
            )
        except BlenderError as exc:
            if cancel.cancelled:
                out_path.unlink(missing_ok=True)
                _set_job(job_id, status="cancelled", message="Cancelled", error=None, output=None)
            else:
                _set_job(job_id, status="error", message=str(exc), error=str(exc))
        except Exception as exc:  # noqa: BLE001
            if cancel.cancelled:
                out_path.unlink(missing_ok=True)
                _set_job(job_id, status="cancelled", message="Cancelled", error=None, output=None)
            else:
                _set_job(job_id, status="error", message="Unexpected error", error=str(exc))

    threading.Thread(target=worker, daemon=True, name=f"blend-{job_id}").start()
    return {"job_id": job_id, "output_name": out_path.name, "output_path": str(out_path)}


@app.post("/api/cancel/{job_id}")
async def cancel_job(job_id: str) -> dict[str, Any]:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job.get("status") != "running":
            return {"job_id": job_id, "status": job.get("status"), "cancelled": False}
        token = job.get("cancel")
        job["status"] = "cancelled"
        job["message"] = "Cancelling…"
    if isinstance(token, CancelToken):
        token.cancel()
    return {"job_id": job_id, "status": "cancelled", "cancelled": True}


@app.get("/api/job/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    job.pop("cancel", None)
    return job


@app.get("/api/download/{job_id}")
async def download(job_id: str, inline: Optional[int] = 0) -> FileResponse:
    job = _get_job(job_id)
    if job.get("status") != "done":
        raise HTTPException(400, "Export not ready")
    raw = job.get("output_path")
    if not raw:
        raise HTTPException(404, "File missing")
    path = Path(raw)
    if not path.is_file():
        raise HTTPException(404, "File missing")
    download_name = job.get("download_name") or path.name
    if inline:
        safe = download_name.replace('"', "")
        return FileResponse(
            path,
            media_type="video/mp4",
            headers={"Content-Disposition": f'inline; filename="{safe}"'},
        )
    return FileResponse(path, media_type="video/mp4", filename=download_name)


@app.get("/api/clip/{clip_id}")
async def clip_preview(clip_id: str) -> FileResponse:
    path = _resolve_clip(clip_id)
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )


@app.post("/api/reveal/{kind}")
async def reveal(kind: str) -> dict[str, str]:
    """
    Reveal input/output in Finder with the file selected (open -R).
    kind: input | output | input-file | output-file
    """
    key = "input" if kind.startswith("input") else "output" if kind.startswith("output") else None
    if key is None:
        raise HTTPException(400, "Use input or output")
    path = session.get(key)
    if path is None:
        raise HTTPException(404, f"No {key} file yet")
    _reveal_in_finder(Path(path))
    return {"revealed": str(path), "kind": kind}


@app.post("/api/open-file/{kind}")
async def open_media_file(kind: str) -> dict[str, str]:
    """Open input/output video with the default Mac app."""
    if kind not in {"input", "output"}:
        raise HTTPException(400, "Use input or output")
    path = session.get(kind)
    if path is None:
        raise HTTPException(404, f"No {kind} file yet")
    _open_file(Path(path))
    return {"opened": str(path), "kind": kind}


# Back-compat aliases used by older UI
@app.post("/api/open-folder/{kind}")
async def open_folder(kind: str) -> dict[str, str]:
    mapped = {"input": "input", "output": "output", "uploads": "input", "outputs": "output"}.get(kind)
    if not mapped:
        raise HTTPException(400, "Use input or output")
    return await reveal(mapped)


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
