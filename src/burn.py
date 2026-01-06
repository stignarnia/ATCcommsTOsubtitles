import shutil
import subprocess
import sys
import hashlib
import tempfile
from pathlib import Path
from typing import Optional

from ass_generator import generate_ass

def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None

def burn_from_ini(mode: str, ini_path: Path, video_path: Optional[Path], output_path: Path) -> None:
    if not _ffmpeg_available():
        print("ffmpeg is not available on PATH.", file=sys.stderr)
        sys.exit(1)

    if not ini_path.exists():
        print(f"INI file not found: {ini_path}", file=sys.stderr)
        sys.exit(1)

    # generate ASS file to temporary {sha1}.ass
    ini_bytes = ini_path.read_bytes()
    hash_name = hashlib.sha1(ini_bytes).hexdigest()
    tmp_path = Path(tempfile.gettempdir()) / f"{hash_name}.ass"
    try:
        metadata = generate_ass(str(ini_path), str(tmp_path))
    except Exception as e:
        print("Failed to generate ASS file:", e, file=sys.stderr)
        sys.exit(1)
    # metadata returned by generate_ass contains "start","end","playres"; ASS is written to tmp_path

    mode = mode.lower()
    # Ensure output filename has an appropriate extension depending on mode.
    out_path = output_path
    if out_path.suffix == "":
        if mode == "transparent":
            out_path = output_path.with_suffix(".webm")
        else:
            out_path = output_path.with_suffix(".mp4")

    if mode == "default":
        if video_path is None or not video_path.exists():
            print("Video input is required for default mode (--video / -v).", file=sys.stderr)
            sys.exit(1)
        # use temporary ASS file written by generate_ass
        escaped = str(tmp_path.as_posix()).replace(":", r"\:").replace("'", r"\'")
        vf = f"subtitles=filename='{escaped}'"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            vf,
            "-c:a",
            "copy",
            str(out_path),
        ]
        print("Running:", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print("ffmpeg failed with exit code", e.returncode, file=sys.stderr)
            sys.exit(e.returncode)
        try:
            tmp_path.unlink()
        except Exception:
            pass
        print("Wrote:", out_path)
    elif mode == "trim":
        if video_path is None or not video_path.exists():
            print("Video input is required for trim mode (--video / -v).", file=sys.stderr)
            sys.exit(1)
        start = metadata.get("start_seconds") if metadata and metadata.get("start_seconds") is not None else None
        end = metadata.get("end_seconds") if metadata and metadata.get("end_seconds") is not None else None
        if start is None or end is None:
            print("Could not determine start/end from generated ASS; generator must provide metadata.", file=sys.stderr)
            sys.exit(1)
        # use temporary ASS file written by generate_ass
        escaped = str(tmp_path.as_posix()).replace(":", r"\:").replace("'", r"\'")
        vf = f"subtitles=filename='{escaped}'"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-ss",
            str(start),
            "-to",
            str(end),
            "-vf",
            vf,
            "-c:a",
            "copy",
            str(out_path),
        ]
        print("Running:", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print("ffmpeg failed with exit code", e.returncode, file=sys.stderr)
            sys.exit(e.returncode)
        try:
            tmp_path.unlink()
        except Exception:
            pass
        print("Wrote:", out_path)
    elif mode == "transparent":
        # Render subtitles on transparent background (no source video)
        end = metadata.get("end_seconds") if metadata and metadata.get("end_seconds") is not None else None
        if end is None:
            print("Could not determine duration from generated ASS; generator must provide metadata.", file=sys.stderr)
            sys.exit(1)
        duration = float(end)
        w, h = metadata.get("playres", (1920, 1080))
        # default framerate
        r = 30
        color_input = f"color=c=black@0:s={w}x{h}:r={r}:d={duration}"
        # use temporary ASS file written by generate_ass
        escaped = str(tmp_path.as_posix()).replace(":", r"\:").replace("'", r"\'")
        vf = f"format=yuva420p,subtitles=filename='{escaped}'"
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            color_input,
            "-vf",
            vf,
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "30",
            "-b:v",
            "0",
            "-deadline",
            "realtime",
            "-cpu-used",
            "8",
            "-pix_fmt",
            "yuva420p",
            str(out_path),
        ]
        print("Running:", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print("ffmpeg failed with exit code", e.returncode, file=sys.stderr)
            sys.exit(e.returncode)
        try:
            tmp_path.unlink()
        except Exception:
            pass
        print("Wrote transparent overlay:", out_path)
    else:
        print("Unknown burn mode: " + mode, file=sys.stderr)
        sys.exit(1)
