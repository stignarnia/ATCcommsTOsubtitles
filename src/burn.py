import shutil
import subprocess
import sys
import hashlib
import tempfile
import time
import signal
from pathlib import Path
from typing import Optional

from ass_generator import generate_ass

def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None

def _ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None

def _get_video_fps_duration(video_path: Path):
    """
    Return (fps, duration_seconds) for the given video file using ffprobe.
    Returns (None, None) on failure.
    """
    if not _ffprobe_available():
        return None, None
    try:
        # get duration
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            check=True, capture_output=True, text=True
        )
        duration_str = res.stdout.strip().splitlines()[0] if res.stdout.strip() else ""
        duration = float(duration_str) if duration_str else None
        # get avg_frame_rate
        res2 = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            check=True, capture_output=True, text=True
        )
        fr_str = res2.stdout.strip().splitlines()[0] if res2.stdout.strip() else ""
        if fr_str and "/" in fr_str:
            num, den = fr_str.split("/")
            fps = float(num) / float(den) if float(den) != 0 else None
        else:
            fps = float(fr_str) if fr_str else None
        return fps, duration
    except Exception:
        return None, None

def _run_ffmpeg_with_progress(cmd, total_frames, progress=True):
    """
    Run ffmpeg command. If progress is True and total_frames is provided, run ffmpeg
    with -progress pipe and display a nicer terminal progress UI. Handles Ctrl+C
    (SIGINT) gracefully by terminating ffmpeg and exiting with code 130.
    Falls back to normal ffmpeg invocation when progress is disabled or total_frames is unknown.
    """
    def _format_time(s: float) -> str:
        if s is None or s != s or s == float("inf"):
            return "--:--:--"
        s = int(max(0, round(s)))
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:d}:{m:02d}:{sec:02d}"

    # If no progress UI, run ffmpeg normally but still handle Ctrl+C to terminate child.
    if not progress or not total_frames:
        proc = None
        try:
            proc = subprocess.Popen(cmd)
            def _handler(signum, frame):
                try:
                    if proc and proc.poll() is None:
                        proc.terminate()
                except Exception:
                    pass
                print("\nTerminated by user.", file=sys.stderr)
                sys.exit(130)
            prev = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, _handler)
            proc.wait()
            signal.signal(signal.SIGINT, prev)
            if proc.returncode != 0:
                print("ffmpeg failed with exit code", proc.returncode, file=sys.stderr)
                sys.exit(proc.returncode)
        except KeyboardInterrupt:
            try:
                if proc and proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
            print("\nTerminated by user.", file=sys.stderr)
            sys.exit(130)
        except Exception as e:
            print("ffmpeg failed:", e, file=sys.stderr)
            sys.exit(1)
        return

    # Progress UI mode: spawn ffmpeg with -progress pipe and render a nicer line with ETA/fps.
    cmd_progress = cmd[:1] + ["-hide_banner", "-loglevel", "error"] + cmd[1:] + ["-progress", "pipe:1"]
    proc = None
    prev = None
    try:
        proc = subprocess.Popen(cmd_progress, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        def _sigint_handler(signum, frame):
            try:
                if proc and proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
            print("\nTerminated by user.", file=sys.stderr)
            sys.exit(130)
        prev = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _sigint_handler)

        start_time = time.time()
        current_frame = 0
        bar_len = 30
        last_render = ""
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("frame="):
                try:
                    current_frame = int(line.split("=", 1)[1])
                except Exception:
                    continue
                pct = min(max(current_frame / total_frames, 0.0), 1.0)
                filled = int(round(pct * bar_len))
                empty = bar_len - filled
                bar = "█" * filled + "─" * empty
                elapsed = time.time() - start_time
                fps_curr = (current_frame / elapsed) if elapsed > 0 else 0.0
                remaining_frames = max(total_frames - current_frame, 0)
                eta = (remaining_frames / fps_curr) if fps_curr > 0 else float("inf")
                left = _format_time(elapsed)
                eta_s = _format_time(eta)
                percent_display = pct * 100
                render = f"\r[{bar}] {percent_display:6.2f}%  {current_frame}/{total_frames}  {fps_curr:5.1f} fps  elapsed {left}  eta {eta_s}"
                if render != last_render:
                    sys.stdout.write(render)
                    sys.stdout.flush()
                    last_render = render
            elif line.startswith("progress=") and line.split("=", 1)[1] == "end":
                break
        proc.wait()
        # ensure final 100% render
        elapsed = time.time() - start_time
        left = _format_time(elapsed)
        final_bar = "█" * bar_len
        sys.stdout.write(f"\r[{final_bar}] {100.00:6.2f}%  {total_frames}/{total_frames}  { (total_frames/elapsed) if elapsed>0 else 0.0:5.1f } fps  elapsed {left}  eta 0:00:00\n")
        sys.stdout.flush()
        if proc.returncode != 0:
            print("ffmpeg failed with exit code", proc.returncode, file=sys.stderr)
            sys.exit(proc.returncode)
    except KeyboardInterrupt:
        try:
            if proc and proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
        print("\nTerminated by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print("ffmpeg failed:", e, file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            if prev is not None:
                signal.signal(signal.SIGINT, prev)
        except Exception:
            pass

def burn_from_ini(mode: str, ini_path: Path, video_path: Optional[Path], output_path: Path, progress: bool = True) -> None:
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
        # compute total_frames for progress if possible
        total_frames = None
        if progress:
            fps, duration = _get_video_fps_duration(video_path)
            if fps is not None and duration is not None:
                total_frames = int(round(fps * duration))
        _run_ffmpeg_with_progress(cmd, total_frames, progress)
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
        total_frames = None
        if progress:
            duration_trim = float(end) - float(start)
            fps, _ = _get_video_fps_duration(video_path)
            if fps is not None and duration_trim is not None:
                total_frames = int(round(fps * duration_trim))
        _run_ffmpeg_with_progress(cmd, total_frames, progress)
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
        total_frames = int(round(duration * r)) if (duration is not None) else None
        _run_ffmpeg_with_progress(cmd, total_frames, progress)
        try:
            tmp_path.unlink()
        except Exception:
            pass
        print("Wrote transparent overlay:", out_path)
    else:
        print("Unknown burn mode: " + mode, file=sys.stderr)
        sys.exit(1)
