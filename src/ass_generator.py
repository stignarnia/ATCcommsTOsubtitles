import os
from datetime import timedelta

from ass_format import ass_color, escape_ass_text, format_time, split_ass_color
from config_validation import ensure_no_timing_keys, ensure_no_visual_keys, is_timestamp_name
from ini_parsing import (
    load_acronyms,
    load_waypoints,
    parse_comms_lines,
    parse_ini_non_comms,
)
from effective_config import get_effective_speaker_bool
from speech_estimation import estimate_duration
from style import get_speaker_style, position_to_alignment
from timestamp import parse_timestamp_to_timedelta
from visual_substitution import apply_visual_substitutions

def generate_ass(input_path: str = "comms.ini", output_path: str = "comms.ass") -> None:
    # Parse non-[comms] sections normally, but parse [comms] manually to preserve
    # repeated keys and ordering.
    # Read the INI file once into memory and pass the lines to all parsers.
    with open(input_path, "r", encoding="utf-8") as _f:
        ini_lines = _f.readlines()

    config = parse_ini_non_comms(lines=ini_lines)
    comms_lines = parse_comms_lines(lines=ini_lines)

    ass_file: list[str] = []

    # [Script Info]
    ass_file.append("[Script Info]")
    ass_file.append("Title: Comms Subtitles")
    ass_file.append("ScriptType: v4.00+")
    ass_file.append("WrapStyle: 2")
    ass_file.append("PlayResX: 1920")
    ass_file.append("PlayResY: 1080")
    ass_file.append("")

    # [V4+ Styles]
    ass_file.append("[V4+ Styles]")
    ass_file.append(
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )

    # Default Style
    ass_file.append(
        "Style: Default,Arial,56,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,1,10,10,10,1"
    )

    # Collect type definitions. Use the new "metaTypes." and "speakerTypes.".
    types = {}
    for s in config.sections():
        if s.startswith("metaTypes.") or s.startswith("speakerTypes."):
            types[s.split(".", 1)[1].strip()] = dict(config.items(s))

    # Validate types: only the 'Timestamp' type may define timing keys;
    # and the 'Timestamp' type must not define visual keys like position/color.
    for tname, tinfo in types.items():
        if is_timestamp_name(tname):
            ensure_no_visual_keys(tinfo, f"Type '{tname}'")
        else:
            ensure_no_timing_keys(tinfo, f"Type '{tname}'")

    # Speakers remain under [speakers.*]
    speakers = {
        s.split(".")[-1]: dict(config.items(s)) for s in config.sections() if s.startswith("speakers.")
    }

    # Speaker name prefix option (centralized precedence resolution):
    # 1) [speakers.<KEY>].show_name
    # 2) [speakerTypes.<Type>].show_name
    # 3) default false
    speaker_keys_with_name_prefix: set[str] = set()
    for sk in speakers.keys():
        if get_effective_speaker_bool(
            sk,
            "show_name",
            speakers=speakers,
            types=types,
            meta=None,
            default=False,
        ):
            speaker_keys_with_name_prefix.add(sk)

    # Meta mappings (short tags used in [comms], e.g. [meta.T] or [meta.C])
    meta = {s.split(".")[-1]: dict(config.items(s)) for s in config.sections() if s.startswith("meta.")}

    # Validate meta entries:
    # - Only metas of type 'Timestamp' may provide timing keys (format/cps).
    # - Timestamp metas must not define visual keys (position/color).
    timestamp_meta_keys = set()
    for mk, mv in meta.items():
        mtype = (mv.get("type") or "").strip()
        if not mtype:
            continue
        if is_timestamp_name(mtype):
            ensure_no_visual_keys(mv, f"Meta '{mk}' is a Timestamp")
            timestamp_meta_keys.add(mk)
        else:
            ensure_no_timing_keys(mv, f"Meta '{mk}' has type '{mtype}'")

    acronyms = load_acronyms(config)
    # Load declared waypoints (e.g. [waypoints.RNAV]) so they are spoken literally, not as NATO.
    waypoints = load_waypoints(lines=ini_lines)
    # Flatten all waypoint tokens into a set of uppercased tokens for quick membership checks.
    literal_waypoints = set()
    for s in waypoints.values():
        literal_waypoints.update(w.upper() for w in s)

    # Background rendering: draw a solid rectangle as a separate ASS drawing event.
    # This avoids relying on BorderStyle=3 behavior which varies between renderers.
    #
    # Important: ASS doesn't expose text-measurement, so rectangle width is an approximation.
    play_res_x = 1920
    play_res_y = 1080
    font_size = 56
    margin_l = 20
    margin_r = 20
    margin_v = 20

    # Approximate font metrics for multi-line boxes.
    # ASS auto-wrap is renderer-dependent; we use a crude word-wrap simulation to estimate it.
    # Tuned to avoid overly tall/wide boxes.
    bg_line_h = int(font_size * 1.10)  # approx line height at fontsize=56
    bg_pad_y = 8  # vertical padding inside the rectangle (top+bottom)

    # Horizontal padding inside the rectangle (left+right).
    bg_pad_x = 20

    width_scale = (
        1  # Knob to grow or shrink the box width if it's consistently too small or big
    )
    bg_corner_r = 18  # rounded corner radius (px) for background boxes

    # Deterministic wrapping target.
    # Aim for ~3/4 the screen width so lines fill more of the frame before wrapping.
    usable_px = max(1, play_res_x - margin_l - margin_r)
    wrap_width_ratio = 0.75
    target_wrap_px = max(1, int(usable_px * wrap_width_ratio))
    max_units_per_line = target_wrap_px / max(1, font_size)

    def bg_y_top(alignment: int, height: int) -> int:
        # top row: 7,8,9 ; middle row: 4,5,6 ; bottom row: 1,2,3
        if alignment in (7, 8, 9):
            return margin_v
        if alignment in (4, 5, 6):
            return (play_res_y // 2) - (height // 2)
        return play_res_y - margin_v - height

    def _char_width_units(ch: str) -> float:
        # 1. Punctuation (Tiny)
        if ch in " .,:;!|'`":
            return 0.24
        if ch in "ilI1[]()":
            return 0.30

        # 2. Extra Wide Chars (Safety bump)
        if ch in "MW@#%":
            return 0.85

        # 3. Uppercase & Digits (THE FIX)
        # These are much wider than lowercase. This prevents the box from being too small on X.
        if ch.isupper() or ch.isdigit():
            return 0.62

        # 4. Standard Lowercase
        # Keeps normal sentences tight.
        return 0.46

    def wrap_ass_text(text: str) -> tuple[str, int, float]:
        """
        Word-wrap the subtitle text deterministically and return:

        - wrapped_text: with explicit ASS line breaks (\\N)
        - line_count: number of lines in wrapped_text
        - max_line_units: max line width in "char units" (for background sizing)

        This allows emitting `\\q2` (no auto wrap) and still getting consistent layout
        across players/renderers.
        """
        # Normalize newlines and map them to explicit ASS line breaks.
        raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")

        out_lines: list[str] = []
        max_units_seen = 0.0

        for seg in raw.split("\\N"):
            words = seg.split()
            if not words:
                out_lines.append("")
                continue

            current_words: list[str] = []
            current_units = 0.0

            for w in words:
                w_units = sum(_char_width_units(ch) for ch in w)
                space_units = _char_width_units(" ")

                if not current_words:
                    current_words = [w]
                    current_units = w_units
                    continue

                if current_units + space_units + w_units <= max_units_per_line:
                    current_words.append(w)
                    current_units += space_units + w_units
                else:
                    out_lines.append(" ".join(current_words))
                    max_units_seen = max(max_units_seen, current_units)
                    current_words = [w]
                    current_units = w_units

            out_lines.append(" ".join(current_words))
            max_units_seen = max(max_units_seen, current_units)

        line_count = max(1, len(out_lines))
        return "\\N".join(out_lines), line_count, max_units_seen

    def box_height_px(line_count: int) -> int:
        return (max(1, int(line_count)) * bg_line_h) + (2 * bg_pad_y)

    def text_core_width_px(max_units: float) -> int:
        """Approximate width of the rendered text core (no padding) from wrapped max units."""
        return max(1, int(max(0.0, float(max_units)) * font_size * width_scale))

    def bg_box_x(alignment: int, text_w: int) -> tuple[int, int]:
        """Return (x_left, box_width) for the background rectangle."""
        # Determine approximate text left/right based on alignment + margins.
        if alignment in (1, 4, 7):  # left
            text_left = margin_l
        elif alignment in (2, 5, 8):  # center
            text_left = (play_res_x // 2) - (text_w // 2)
        else:  # right
            text_left = play_res_x - margin_r - text_w

        text_right = text_left + text_w

        # Desired padded rectangle.
        box_left = text_left - bg_pad_x
        box_right = text_right + bg_pad_x

        # Clamp within the video frame; if we overflow on the right, shift left.
        if box_right > play_res_x:
            shift = box_right - play_res_x
            box_left -= shift
            box_right = play_res_x

        # Clamp on the left; if we overflow, shift right.
        if box_left < 0:
            shift = -box_left
            box_left = 0
            box_right = min(play_res_x, box_right + shift)

        box_width = max(1, int(box_right - box_left))
        box_left = max(0, min(int(box_left), play_res_x - box_width))
        return box_left, box_width

    style_render: dict[str, dict[str, object]] = {}

    # Use stable ASS style names (speaker keys and non-timestamp meta keys), not display names that may contain spaces.
    style_keys = list(speakers.keys()) + [k for k in meta.keys() if k not in timestamp_meta_keys]
    for speaker_key in style_keys:
        style = get_speaker_style(speaker_key, speakers, types, meta)

        color = ass_color(style["color"])

        bg_raw = (style.get("background") or "").strip().lower()
        has_bg = bool(bg_raw and bg_raw != "none")
        bg_ass = ass_color(style.get("background", ""), keep_alpha=True) if has_bg else "&H00000000"

        # Keep text styling consistent; background is drawn separately as a rectangle event.
        back_colour = "&H00000000"
        border_style = 1
        outline = 2
        shadow = 2

        # Determine alignment (map normalized positions to ASS 1-9)
        alignment = position_to_alignment(style.get("position"))

        style_render[speaker_key] = {
            "has_bg": has_bg,
            "bg_ass": bg_ass,
            "alignment": alignment,
        }

        ass_file.append(
            f"Style: {speaker_key},Arial,56,{color},&H000000FF,&H00000000,{back_colour},0,0,0,0,100,100,0,0,{border_style},{outline},{shadow},{alignment},20,20,20,1"
        )

    ass_file.append("")

    # [Events]
    ass_file.append("[Events]")
    ass_file.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")

    current_time = timedelta()

    # Used only if a computed/estimated duration would be 0ms (guard rail).
    fallback_duration = timedelta(milliseconds=1)

    # First pass: collect all explicit timestamp markers (index + parsed time + cps)
    # Only meta keys whose [meta.<KEY>] declares type = Timestamp are valid timestamp markers.
    # Prebuild a map from timestamp meta keys to their timing info for a single-pass lookup.
    ts_info = {k: types.get((meta[k].get("type") or "").strip(), {}) for k in timestamp_meta_keys}
    markers: list[tuple[int, timedelta, float]] = []
    for idx, (key, value) in enumerate(comms_lines):
        info = ts_info.get(key)
        if not info:
            continue
        t_fmt = info.get("format", "mm:ss")
        cps = float(info.get("cps", "15"))
        markers.append((idx, parse_timestamp_to_timedelta(value, t_fmt), cps))
    # Note: bare "T" markers without a corresponding [meta.T] entry are invalid and will be caught
    # by the comms speaker-key validation below.

    marker_indices = {midx for midx, _t, _c in markers}

    # One-time visual substitution pass (single entrypoint):
    # This prepares comms lines for both CPS/duration estimation and final ASS rendering.
    comms_lines_prepared = apply_visual_substitutions(
        comms_lines=comms_lines,
        marker_indices=marker_indices,
        speakers=speakers,
        types=types,
        meta=meta,
        speaker_keys_with_name_prefix=speaker_keys_with_name_prefix,
    )

    # Helper: find the next marker time after a given index
    def next_marker_time(after_idx: int):
        for midx, t, _ in markers:
            if midx > after_idx:
                return t
        return None

    # Validate comms speaker keys early (ignore timestamp markers).
    known_speakers = set(speakers.keys()) | (set(meta.keys()) - timestamp_meta_keys)
    for idx, (k, _v) in enumerate(comms_lines_prepared):
        if idx in marker_indices:
            continue
        if k not in known_speakers:
            raise ValueError(f"Unknown speaker key {k!r} in [comms] at index {idx}")

    # Map markers by their index for quick lookup during processing
    markers_by_index = {midx: (t, cps) for midx, t, cps in markers}

    # Second pass: generate dialogue lines.
    #
    # Timing behavior (two rails):
    # - Speaker lines are sequential on the "speakers rail".
    # - Non-timestamp meta lines (e.g. C=Comment) are sequential on the "meta rail".
    # - Both rails start at the block's timestamp marker and run independently (can overlap).
    # - For a bounded block (there is a next timestamp marker), each rail is scaled down
    #   independently if it would exceed the available time (so comments never steal time
    #   from speakers).
    # - Block duration is max(end_speakers_rail, end_meta_rail). Next blocks still start
    #   at their own timestamp markers (overlap is allowed in ASS).
    meta_non_timestamp_keys = set(meta.keys()) - timestamp_meta_keys
    speaker_keys = set(speakers.keys())

    def _scale_durations_to_fit(durations: list[timedelta], max_ms: int) -> list[int]:
        """Convert durations to ms, and if their sum exceeds max_ms, scale them down (>=1ms each)."""
        est_ms = [max(1, int(d.total_seconds() * 1000)) for d in durations]
        sum_est = sum(est_ms)

        if max_ms <= 0:
            return [1 for _ in est_ms]

        if sum_est <= max_ms:
            return est_ms

        scale = max_ms / max(1, sum_est)
        scaled_ms = [max(1, int(ms * scale)) for ms in est_ms]

        # Fix rounding drift so total fits without exceeding max_ms.
        drift = sum(scaled_ms) - max_ms
        k = 0
        while drift > 0 and k < len(scaled_ms):
            if scaled_ms[k] > 1:
                scaled_ms[k] -= 1
                drift -= 1
            else:
                k += 1

        return scaled_ms

    # Collect Dialogue lines first, then emit them sorted by start time for robustness.
    pending_events: list[tuple[timedelta, int, str]] = []

    def _rounded_rect_path(width: int, height: int, r: int) -> str:
        """
        ASS vector drawing path for a filled rounded rectangle.

        Uses cubic Beziers to approximate quarter-circles (kappa approximation).
        """
        r = max(0, min(int(r), int(width // 2), int(height // 2)))
        if r <= 0:
            return f"m 0 0 l {width} 0 l {width} {height} l 0 {height} l 0 0"

        k = int(round(r * 0.5522847498))  # circle kappa approximation

        return (
            f"m {r} 0 "
            f"l {width - r} 0 "
            f"b {width - r + k} 0 {width} {r - k} {width} {r} "
            f"l {width} {height - r} "
            f"b {width} {height - r + k} {width - r + k} {height} {width - r} {height} "
            f"l {r} {height} "
            f"b {r - k} {height} 0 {height - r + k} 0 {height - r} "
            f"l 0 {r} "
            f"b 0 {r - k} {r - k} 0 {r} 0"
        )

    def _maybe_add_bg_event(
        *,
        sr: dict[str, object],
        line_count: int,
        max_line_units: float,
        start: timedelta,
        end: timedelta,
    ) -> None:
        """If the style declares a background, add a rectangle-drawing event behind the text."""
        if not sr.get("has_bg"):
            return

        bg_alpha, bg_bbggrr = split_ass_color(str(sr.get("bg_ass", "&H00000000")))
        alignment = int(sr.get("alignment", 1))

        height = box_height_px(line_count)
        y_top = bg_y_top(alignment, height)

        text_w = text_core_width_px(max_line_units)
        x_left, width = bg_box_x(alignment, text_w)

        path = _rounded_rect_path(width, height, bg_corner_r)

        bg_text = (
            f"{{\\p1\\pos({x_left},{y_top})\\an7\\bord0\\shad0\\1c&H{bg_bbggrr}&\\1a&H{bg_alpha}&}}"
            f"{path}"
            f"{{\\p0}}"
        )

        # Write with Layer=0 but force ordering (sort layer = -1) so it is behind same-start text.
        bg_line = f"Dialogue: 0,{format_time(start)},{format_time(end)},Default,,0,0,0,,{bg_text}"
        pending_events.append((start, -1, bg_line))

    i = 0
    while i < len(comms_lines_prepared):
        if i not in markers_by_index:
            # Disallow implicit timing without a preceding timestamp marker.
            raise ValueError("First [comms] entry must be a timestamp marker (e.g. T=...).")

        # Start of a timed block
        block_start, block_cps = markers_by_index[i]

        block_end = next_marker_time(i)

        # Collect messages until next timestamp marker (or EOF)
        j = i + 1
        block_msgs: list[tuple[str, str]] = []
        while j < len(comms_lines_prepared) and j not in marker_indices:
            block_msgs.append(comms_lines_prepared[j])
            j += 1

        if not block_msgs:
            i = j
            continue

        # Split into rails
        speaker_msgs: list[tuple[str, str]] = []
        meta_msgs: list[tuple[str, str]] = []
        for mkey, mval in block_msgs:
            if mkey in meta_non_timestamp_keys and mkey not in speaker_keys:
                meta_msgs.append((mkey, mval))
            else:
                speaker_msgs.append((mkey, mval))

        is_bounded = block_end is not None and block_end > block_start
        max_ms = int((block_end - block_start).total_seconds() * 1000) if is_bounded else 0

        # Speakers rail durations
        speaker_est = [
            estimate_duration(mval, cps=block_cps, acronyms=acronyms, waypoints=literal_waypoints)
            for _, mval in speaker_msgs
        ]
        if is_bounded:
            speaker_ms = _scale_durations_to_fit(speaker_est, max_ms)
        else:
            speaker_ms = [max(1, int(d.total_seconds() * 1000)) for d in speaker_est]

        # Meta rail durations (reuse the block's Timestamp CPS, per requirement)
        meta_est = [
            estimate_duration(mval, cps=block_cps, acronyms=acronyms, waypoints=literal_waypoints)
            for _, mval in meta_msgs
        ]
        if is_bounded:
            meta_ms = _scale_durations_to_fit(meta_est, max_ms)
        else:
            meta_ms = [max(1, int(d.total_seconds() * 1000)) for d in meta_est]

        # Emit speaker rail (layer 0)
        speakers_current = block_start
        for (mkey, mval), dur_ms in zip(speaker_msgs, speaker_ms, strict=True):
            start_time = speakers_current
            end_time = start_time + timedelta(
                milliseconds=dur_ms if dur_ms > 0 else int(fallback_duration.total_seconds() * 1000)
            )

            text_val = mval
            wrapped_text, line_count, max_units = wrap_ass_text(text_val)

            sr = style_render.get(mkey) or {}
            _maybe_add_bg_event(
                sr=sr,
                line_count=line_count,
                max_line_units=max_units,
                start=start_time,
                end=end_time,
            )

            line = (
                f"Dialogue: 0,{format_time(start_time)},{format_time(end_time)},{mkey},"
                f"{escape_ass_text(get_speaker_style(mkey, speakers, types, meta)['display_name'])},0,0,0,,"
                f"{{\\q2}}{escape_ass_text(wrapped_text)}"
            )
            pending_events.append((start_time, 0, line))
            speakers_current = end_time

        # Emit meta rail (layer 1 so it draws above speakers if overlapping)
        meta_current = block_start
        for (mkey, mval), dur_ms in zip(meta_msgs, meta_ms, strict=True):
            start_time = meta_current
            end_time = start_time + timedelta(
                milliseconds=dur_ms if dur_ms > 0 else int(fallback_duration.total_seconds() * 1000)
            )

            text_val = mval
            wrapped_text, line_count, max_units = wrap_ass_text(text_val)

            sr = style_render.get(mkey) or {}
            _maybe_add_bg_event(
                sr=sr,
                line_count=line_count,
                max_line_units=max_units,
                start=start_time,
                end=end_time,
            )

            line = (
                f"Dialogue: 1,{format_time(start_time)},{format_time(end_time)},{mkey},"
                f"{escape_ass_text(get_speaker_style(mkey, speakers, types, meta)['display_name'])},0,0,0,,"
                f"{{\\q2}}{escape_ass_text(wrapped_text)}"
            )
            pending_events.append((start_time, 1, line))
            meta_current = end_time

        i = j

    pending_events.sort(key=lambda t: (t[0], t[1]))
    for _start, _layer, line in pending_events:
        ass_file.append(line)

    # Ensure output directory exists
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ass_file))
