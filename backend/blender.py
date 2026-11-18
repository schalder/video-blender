"""Loop a short clip into a long 1080p MP4 — CapCut-style fast path.

Strategy (same visual job, far less work):
  1. Normalize the source once to 1080p (short encode).
  2. Bake edge-out → edge-in into one loopable unit (short encode).
  3. Concat that unit with stream-copy to the target length (near-instant).

That matches: first copy edges out, middle copies edge in+out at the seams,
last copy edges in — without re-encoding the full multi-hour timeline.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

WIDTH = 1920
HEIGHT = 1080
DEFAULT_FADE = 0.75
MIN_FADE = 0.15
WORKER_THREADS = max(2, min(6, (os.cpu_count() or 8) // 2))
NICE_DELTA = 12

ProgressCb = Callable[[float, str], None]


class BlenderError(Exception):
    pass


class CancelledError(BlenderError):
    """Raised when the user cancels a running blend job."""


@dataclass
class CancelToken:
    _event: threading.Event = field(default_factory=threading.Event, repr=False)
    _proc_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _proc: Optional[subprocess.Popen] = field(default=None, repr=False)

    def cancel(self) -> None:
        self._event.set()
        with self._proc_lock:
            proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise CancelledError("Cancelled by user")

    def attach(self, proc: subprocess.Popen) -> None:
        with self._proc_lock:
            self._proc = proc
        if self.cancelled:
            self.cancel()

    def detach(self, proc: subprocess.Popen) -> None:
        with self._proc_lock:
            if self._proc is proc:
                self._proc = None


@dataclass
class ProbeInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str
    audio_codec: Optional[str]


def _which_ffmpeg() -> str:
    from .paths import bundled_bin

    bundled = bundled_bin("ffmpeg")
    candidates: list[str] = []
    if bundled:
        candidates.append(str(bundled))
    candidates.extend(
        [
            "ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/Users/dizilance/bin/ffmpeg",
        ]
    )
    for candidate in candidates:
        path = shutil.which(candidate) if candidate == "ffmpeg" else candidate
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise BlenderError("FFmpeg not found. Reinstall Video Blender or run: brew install ffmpeg")


def _which_ffprobe() -> str:
    from .paths import bundled_bin

    bundled = bundled_bin("ffprobe")
    candidates: list[str] = []
    if bundled:
        candidates.append(str(bundled))
    candidates.extend(
        [
            "ffprobe",
            "/opt/homebrew/bin/ffprobe",
            "/usr/local/bin/ffprobe",
            "/Users/dizilance/bin/ffprobe",
        ]
    )
    for candidate in candidates:
        path = shutil.which(candidate) if candidate == "ffprobe" else candidate
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise BlenderError("ffprobe not found. Reinstall Video Blender or run: brew install ffmpeg")


def get_ffmpeg() -> str:
    return _which_ffmpeg()


def get_ffprobe() -> str:
    return _which_ffprobe()


# Lazily resolved so bundled paths work after freeze extract


def probe(path: str | Path) -> ProbeInfo:
    path = str(path)
    cmd = [
        get_ffprobe(),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    try:
        raw = subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as exc:
        raise BlenderError(f"Could not read video: {path}") from exc

    data = json.loads(raw)
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video:
        raise BlenderError("No video stream found in the uploaded file.")

    duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise BlenderError("Could not determine clip duration.")

    fps = _parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1")
    return ProbeInfo(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=fps,
        has_audio=audio is not None,
        video_codec=video.get("codec_name") or "unknown",
        audio_codec=(audio or {}).get("codec_name"),
    )


def _parse_fps(rate: str) -> float:
    if "/" in rate:
        a, b = rate.split("/", 1)
        try:
            num, den = float(a), float(b)
            return num / den if den else 30.0
        except ValueError:
            return 30.0
    try:
        return float(rate) or 30.0
    except ValueError:
        return 30.0


def choose_fade(clip_dur: float, requested: float = DEFAULT_FADE) -> float:
    max_fade = max(MIN_FADE, clip_dur * 0.25)
    fade = min(requested, max_fade)
    if clip_dur <= fade * 2.2:
        fade = max(MIN_FADE, clip_dur * 0.12)
    return round(fade, 3)


def copies_needed(clip_dur: float, target: float, fade: float = 0.0) -> int:
    """How many loopable units of length clip_dur are needed to cover target."""
    del fade  # seams are baked into each unit; timeline length is N * clip_dur
    if target <= clip_dur:
        return 1
    return max(1, int(math.ceil(target / clip_dur)))


def _estimate_bytes(target_seconds: float) -> int:
    # Single final file (+ tiny loopable). ~5 Mbps with margin.
    return int(target_seconds * 5_500_000 / 8 * 1.25)


def _ensure_disk_space(path: Path, needed: int) -> None:
    free = shutil.disk_usage(str(path)).free
    if free < needed:
        raise BlenderError(
            f"Not enough free disk space for this job. Need about {needed / (1024**3):.1f} GB free, "
            f"but only {free / (1024**3):.1f} GB is available. Free some space and try again."
        )


def _thread_args() -> list[str]:
    return [
        "-threads",
        str(WORKER_THREADS),
        "-filter_threads",
        str(WORKER_THREADS),
        "-filter_complex_threads",
        str(WORKER_THREADS),
    ]


def _encoder_args(has_audio: bool, *, soft: bool = False) -> list[str]:
    if soft:
        args = [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-force_key_frames",
            "0",
        ]
    else:
        args = [
            "-c:v",
            "h264_videotoolbox",
            "-b:v",
            "5M",
            "-allow_sw",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-force_key_frames",
            "0",
        ]
    if has_audio:
        args += ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
    else:
        args += ["-an"]
    return args


def _nice_worker() -> None:
    try:
        os.nice(NICE_DELTA)
    except OSError:
        pass


def _supports_videotoolbox() -> bool:
    try:
        out = subprocess.check_output([get_ffmpeg(), "-hide_banner", "-encoders"], text=True, stderr=subprocess.STDOUT)
        return "h264_videotoolbox" in out
    except Exception:
        return False


USE_VTB = _supports_videotoolbox()


def _prefer_soft_encoder() -> None:
    global USE_VTB
    USE_VTB = False


def _hwaccel_prefix(soft: bool) -> list[str]:
    if soft:
        return []
    return ["-hwaccel", "videotoolbox"]


def _run_ffmpeg(
    cmd: list[str],
    *,
    duration_hint: Optional[float] = None,
    on_progress: Optional[ProgressCb] = None,
    label: str = "Encoding",
    cancel: Optional[CancelToken] = None,
) -> None:
    if cancel:
        cancel.check()
    if "-threads" not in cmd:
        cmd = [cmd[0], *_thread_args(), *cmd[1:]]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        preexec_fn=_nice_worker,
    )
    if cancel:
        cancel.attach(proc)
    assert proc.stdout is not None
    time_re = re.compile(r"out_time_ms=(\d+)")
    time_alt = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
    last_pct = -1.0
    tail: list[str] = []
    code = -1
    try:
        for line in proc.stdout:
            if cancel and cancel.cancelled:
                try:
                    proc.terminate()
                except OSError:
                    pass
                raise CancelledError("Cancelled by user")
            tail.append(line.rstrip())
            if len(tail) > 40:
                tail.pop(0)
            pct = None
            m = time_re.search(line)
            if m and duration_hint and duration_hint > 0:
                ms = int(m.group(1))
                pct = min(99.0, (ms / 1_000_000) / duration_hint * 100)
            else:
                m2 = time_alt.search(line)
                if m2 and duration_hint and duration_hint > 0:
                    h, mi, s = int(m2.group(1)), int(m2.group(2)), float(m2.group(3))
                    t = h * 3600 + mi * 60 + s
                    pct = min(99.0, t / duration_hint * 100)
            if pct is not None and on_progress and pct - last_pct >= 0.5:
                last_pct = pct
                on_progress(pct, label)
        code = proc.wait()
    finally:
        if cancel:
            cancel.detach(proc)
    if cancel and cancel.cancelled:
        raise CancelledError("Cancelled by user")
    if code != 0:
        detail = "\n".join(tail[-12:]) if tail else "no ffmpeg output"
        free = shutil.disk_usage(".").free
        hint = ""
        if free < 3 * 1024**3 or "Conversion failed" in detail:
            hint = f"\n\nDisk space now: {free / (1024**3):.1f} GB free."
        raise BlenderError(f"FFmpeg failed while {label.lower()} (exit {code}).\n{detail}{hint}")


def _run_ffmpeg_with_fallback(
    build_cmd,
    *,
    duration_hint: Optional[float] = None,
    on_progress: Optional[ProgressCb] = None,
    label: str = "Encoding",
    cancel: Optional[CancelToken] = None,
) -> None:
    soft = not USE_VTB
    try:
        _run_ffmpeg(
            build_cmd(soft),
            duration_hint=duration_hint,
            on_progress=on_progress,
            label=label,
            cancel=cancel,
        )
    except CancelledError:
        raise
    except BlenderError:
        if soft:
            raise
        if cancel:
            cancel.check()
        _prefer_soft_encoder()
        if on_progress:
            on_progress(1, f"{label} (software encoder)")
        _run_ffmpeg(
            build_cmd(True),
            duration_hint=duration_hint,
            on_progress=on_progress,
            label=label,
            cancel=cancel,
        )


def _scale_chain(label_in: str = "0:v", label_out: str = "vfull") -> str:
    """1080p cover crop @ 30fps — single shared prep for all paths."""
    return (
        f"[{label_in}]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},setsar=1,fps=30,format=yuv420p,setpts=PTS-STARTPTS[{label_out}]"
    )


def _fit_scaled(
    src: Path,
    dest: Path,
    target_seconds: float,
    has_audio: bool,
    on_progress: Optional[ProgressCb],
    cancel: Optional[CancelToken] = None,
) -> ProbeInfo:
    """One encode: scale to 1080p30 and trim to target (no loop needed)."""
    if cancel:
        cancel.check()
    if on_progress:
        on_progress(8, "Preparing 1080p clip")

    def build(soft: bool) -> list[str]:
        fc = _scale_chain()
        cmd = [
            get_ffmpeg(),
            "-y",
            "-hide_banner",
            "-progress",
            "pipe:1",
            "-nostats",
            *_hwaccel_prefix(soft),
            "-i",
            str(src),
            "-filter_complex",
            fc,
            "-map",
            "[vfull]",
            "-t",
            f"{target_seconds:.3f}",
        ]
        if has_audio:
            cmd += [
                "-map",
                "0:a:0?",
                "-af",
                "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo",
            ]
        return cmd + _encoder_args(has_audio, soft=soft) + [str(dest)]

    def wrapped(pct: float, label: str) -> None:
        if on_progress:
            on_progress(8 + (pct / 100) * 50, label)

    _run_ffmpeg_with_fallback(
        build,
        duration_hint=target_seconds,
        on_progress=wrapped,
        label="Preparing 1080p clip",
        cancel=cancel,
    )
    return probe(dest)


def _make_loopable_one_pass(
    src: Path,
    dest: Path,
    clip_dur: float,
    fade: float,
    has_audio: bool,
    on_progress: Optional[ProgressCb],
    cancel: Optional[CancelToken] = None,
) -> ProbeInfo:
    """
    ONE encode: 4K/any → 1080p30 + edge-out/edge-in bake.

    Avoids the old double pass (normalize, then bake).
    """
    if cancel:
        cancel.check()
    if on_progress:
        on_progress(8, "Building loop unit (1080p + edge blend)")

    d = clip_dur
    c = fade
    body = max(0.05, d - c)

    # Scale once, then split for body / tail→head crossfade
    vprep = _scale_chain("0:v", "vfull")
    if has_audio:
        fc = (
            f"{vprep};"
            f"[vfull]split=3[vs0][vs1][vs2];"
            f"[vs0]trim=0:{body:.3f},setpts=PTS-STARTPTS[vbegin];"
            f"[vs1]trim={body:.3f}:{d:.3f},setpts=PTS-STARTPTS[vtail];"
            f"[vs2]trim=0:{c:.3f},setpts=PTS-STARTPTS[vhead];"
            f"[vtail][vhead]xfade=transition=fade:duration={c:.3f}:offset=0[vfade];"
            f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"asetpts=PTS-STARTPTS,asplit=3[as0][as1][as2];"
            f"[as0]atrim=0:{body:.3f},asetpts=PTS-STARTPTS[abegin];"
            f"[as1]atrim={body:.3f}:{d:.3f},asetpts=PTS-STARTPTS[atail];"
            f"[as2]atrim=0:{c:.3f},asetpts=PTS-STARTPTS[ahead];"
            f"[atail][ahead]acrossfade=d={c:.3f}:c1=tri:c2=tri[afade];"
            f"[vbegin][abegin][vfade][afade]concat=n=2:v=1:a=1[vout][aout]"
        )
        maps = ["-map", "[vout]", "-map", "[aout]"]
    else:
        fc = (
            f"{vprep};"
            f"[vfull]split=3[vs0][vs1][vs2];"
            f"[vs0]trim=0:{body:.3f},setpts=PTS-STARTPTS[vbegin];"
            f"[vs1]trim={body:.3f}:{d:.3f},setpts=PTS-STARTPTS[vtail];"
            f"[vs2]trim=0:{c:.3f},setpts=PTS-STARTPTS[vhead];"
            f"[vtail][vhead]xfade=transition=fade:duration={c:.3f}:offset=0[vfade];"
            f"[vbegin][vfade]concat=n=2:v=1:a=0[vout]"
        )
        maps = ["-map", "[vout]"]

    def build(soft: bool) -> list[str]:
        return [
            get_ffmpeg(),
            "-y",
            "-hide_banner",
            "-progress",
            "pipe:1",
            "-nostats",
            *_hwaccel_prefix(soft),
            "-i",
            str(src),
            "-filter_complex",
            fc,
            *maps,
            *_encoder_args(has_audio, soft=soft),
            str(dest),
        ]

    def wrapped(pct: float, label: str) -> None:
        if on_progress:
            on_progress(8 + (pct / 100) * 52, label)

    _run_ffmpeg_with_fallback(
        build,
        duration_hint=d,
        on_progress=wrapped,
        label="Building loop unit",
        cancel=cancel,
    )
    return probe(dest)


def _concat_path_line(path: Path) -> str:
    # ffmpeg concat demuxer: quote and escape single quotes
    text = str(path.resolve()).replace("'", r"'\''")
    return f"file '{text}'\n"


def _fast_concat(
    loopable: Path,
    copies: int,
    target_seconds: float,
    dest: Path,
    work: Path,
    has_audio: bool,
    on_progress: Optional[ProgressCb],
    cancel: Optional[CancelToken] = None,
) -> None:
    """Repeat the loopable unit with stream-copy — CapCut-like speed."""
    if cancel:
        cancel.check()
    if on_progress:
        on_progress(62, "Stitching long video (fast copy)")

    list_file = work / "concat.txt"
    with list_file.open("w", encoding="utf-8") as fh:
        for _ in range(copies):
            fh.write(_concat_path_line(loopable))

    def try_copy() -> None:
        cmd = [
            get_ffmpeg(),
            "-y",
            "-hide_banner",
            "-progress",
            "pipe:1",
            "-nostats",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-t",
            f"{target_seconds:.3f}",
            "-c",
            "copy",
            str(dest),
        ]
        _run_ffmpeg(
            cmd,
            duration_hint=min(8.0, target_seconds),
            on_progress=(
                (lambda pct, label: on_progress(62 + (pct / 100) * 30, "Stitching long video (fast copy)"))
                if on_progress
                else None
            ),
            label="Stitching long video (fast copy)",
            cancel=cancel,
        )

    try:
        try_copy()
    except CancelledError:
        raise
    except BlenderError:
        # Rare MP4 copy quirk — one VideoToolbox pass, still no multi-hour xfade
        if on_progress:
            on_progress(65, "Stitching long video (hardware encode)")

        def build(soft: bool) -> list[str]:
            return [
                get_ffmpeg(),
                "-y",
                "-hide_banner",
                "-progress",
                "pipe:1",
                "-nostats",
                *_hwaccel_prefix(soft),
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-t",
                f"{target_seconds:.3f}",
                *_encoder_args(has_audio, soft=soft),
                str(dest),
            ]

        def wrapped(pct: float, label: str) -> None:
            if on_progress:
                on_progress(65 + (pct / 100) * 28, label)

        _run_ffmpeg_with_fallback(
            build,
            duration_hint=target_seconds,
            on_progress=wrapped,
            label="Stitching long video",
            cancel=cancel,
        )


def blend_to_length(
    source: str | Path,
    output: str | Path,
    target_seconds: float,
    *,
    fade_seconds: float = DEFAULT_FADE,
    on_progress: Optional[ProgressCb] = None,
    cancel: Optional[CancelToken] = None,
) -> dict:
    """
    Build a long-form 1080p MP4 by looping `source` to `target_seconds`.

    Fast path: bake edge blends into one unit, then stream-copy concat.
    """
    source = Path(source)
    output = Path(output)
    if not source.is_file():
        raise BlenderError(f"Source not found: {source}")
    if target_seconds < 1:
        raise BlenderError("Target length must be at least 1 second.")
    if target_seconds > 6 * 3600:
        raise BlenderError("Target length max is 6 hours.")

    output.parent.mkdir(parents=True, exist_ok=True)
    info = probe(source)
    fade = choose_fade(info.duration, fade_seconds)

    if cancel:
        cancel.check()
    _ensure_disk_space(output.parent, _estimate_bytes(target_seconds))
    if on_progress:
        on_progress(1, "Analyzing clip")

    work_root = output.parent / ".work"
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="videoblender_", dir=str(work_root)) as tmp:
        work = Path(tmp)
        clip_dur = info.duration
        fade = choose_fade(clip_dur, fade_seconds)
        has_audio = info.has_audio

        if cancel:
            cancel.check()

        if target_seconds <= clip_dur + 0.05:
            # One pass: scale + trim (no loop seams needed)
            _fit_scaled(source, output, target_seconds, has_audio, on_progress, cancel=cancel)
            n = 1
        else:
            # One pass: scale to 1080p30 + bake edge blend, then stream-copy stitch
            loopable = work / "loopable.mp4"
            loop_info = _make_loopable_one_pass(
                source, loopable, clip_dur, fade, has_audio, on_progress, cancel=cancel
            )
            unit = loop_info.duration
            n = copies_needed(unit, target_seconds)
            _fast_concat(
                loopable, n, target_seconds, output, work, has_audio, on_progress, cancel=cancel
            )

        if cancel:
            cancel.check()

    final = probe(output)
    if on_progress:
        on_progress(100, "Done")

    return {
        "output": str(output),
        "source_duration": round(info.duration, 3),
        "target_duration": target_seconds,
        "output_duration": round(final.duration, 3),
        "copies": n,
        "fade_seconds": fade,
        "width": final.width,
        "height": final.height,
        "fps": final.fps,
        "has_audio": final.has_audio,
        "engine": "fast-loop-onepass",
    }
