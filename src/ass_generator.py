import os
from datetime import timedelta

from ass_format import ass_color, escape_ass_text, format_time
from ass_renderer import create_bg_event, wrap_ass_text, get_max_units_per_line
from config_validation import ensure_no_timing_keys, ensure_no_visual_keys, is_timestamp_name
from effective_config import get_effective_speaker_bool, get_effective_speaker_int
from ini_parsing import (
    load_acronyms,
    load_waypoints,
    parse_comms_lines,
    parse_ini_non_comms,
)
from speech_estimation import estimate_duration
from style import get_speaker_style, position_to_alignment
from timestamp import parse_timestamp_to_timedelta
from visual_substitution import apply_visual_substitutions

def generate_ass(input_path: str = "comms.ini", output_path: str = "comms.ass") -> dict:
    # Read INI into memory once
    with open(input_path, "r", encoding="utf-8") as _f:
        ini_lines = _f.readlines()

    config = parse_ini_non_comms(lines=ini_lines)
    comms_lines = parse_comms_lines(lines=ini_lines)

    # Global rendering options
    render_section = "render"
    play_res_x = int(config.get(render_section, "play_res_x", fallback="1920"))
    play_res_y = int(config.get(render_section, "play_res_y", fallback="1080"))
    wrap_width_ratio = float(config.get(render_section, "wrap_width_ratio", fallback="0.75"))
    wrap_width_ratio = min(1.0, max(0.10, wrap_width_ratio))

    ass_file: list[str] = []

    # [Script Info]
    ass_file.append("[Script Info]")
    ass_file.append("Title: Comms Subtitles")
    ass_file.append("ScriptType: v4.00+")
    ass_file.append("WrapStyle: 2")
    ass_file.append(f"PlayResX: {play_res_x}")
    ass_file.append(f"PlayResY: {play_res_y}")
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

    types = {}
    for s in config.sections():
        if s.startswith("metaTypes.") or s.startswith("speakerTypes."):
            types[s.split(".", 1)[1].strip()] = dict(config.items(s))

    # Validate types
    for tname, tinfo in types.items():
        if is_timestamp_name(tname):
            ensure_no_visual_keys(tinfo, f"Type '{tname}'")
        else:
            ensure_no_timing_keys(tinfo, f"Type '{tname}'")

    speakers = {
        s.split(".")[-1]: dict(config.items(s)) for s in config.sections() if s.startswith("speakers.")
    }

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

    meta = {s.split(".")[-1]: dict(config.items(s)) for s in config.sections() if s.startswith("meta.")}

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
    waypoints = load_waypoints(lines=ini_lines)
    literal_waypoints = set()
    for s in waypoints.values():
        literal_waypoints.update(w.upper() for w in s)

    max_units_per_line = get_max_units_per_line(play_res_x, wrap_width_ratio)

    style_render: dict[str, dict[str, object]] = {}

    style_keys = list(speakers.keys()) + [k for k in meta.keys() if k not in timestamp_meta_keys]
    for speaker_key in style_keys:
        style = get_speaker_style(speaker_key, speakers, types, meta)

        color = ass_color(style["color"])

        bg_raw = (style.get("background") or "").strip().lower()
        has_bg = bool(bg_raw and bg_raw != "none")
        bg_ass = ass_color(style.get("background", ""), keep_alpha=True) if has_bg else "&H00000000"

        # Background drawn as separate event, avoiding BorderStyle=3 issues
        back_colour = "&H00000000"
        border_style = 1
        outline = 2
        shadow = 2

        alignment = position_to_alignment(style.get("position"))

        style_render[speaker_key] = {
            "has_bg": has_bg,
            "bg_ass": bg_ass,
            "alignment": alignment,
            "background_lines_threshold": get_effective_speaker_int(
                speaker_key,
                "background_lines_threshold",
                speakers=speakers,
                types=types,
                meta=meta,
                default=1,
            ),
        }

        ass_file.append(
            f"Style: {speaker_key},Arial,56,{color},&H000000FF,&H00000000,{back_colour},0,0,0,0,100,100,0,0,{border_style},{outline},{shadow},{alignment},20,20,20,1"
        )

    ass_file.append("")

    # [Events]
    ass_file.append("[Events]")
    ass_file.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")

    current_time = timedelta()
    fallback_duration = timedelta(milliseconds=1)

    # First pass: timestamp markers
    ts_info = {k: types.get((meta[k].get("type") or "").strip(), {}) for k in timestamp_meta_keys}
    markers: list[tuple[int, timedelta, float]] = []
    for idx, (key, value) in enumerate(comms_lines):
        info = ts_info.get(key)
        if not info:
            continue
        t_fmt = info.get("format", "mm:ss")
        cps = float(info.get("cps", "15"))
        markers.append((idx, parse_timestamp_to_timedelta(value, t_fmt), cps))

    marker_indices = {midx for midx, _t, _c in markers}

    comms_lines_prepared = apply_visual_substitutions(
        comms_lines=comms_lines,
        marker_indices=marker_indices,
        speakers=speakers,
        types=types,
        meta=meta,
        speaker_keys_with_name_prefix=speaker_keys_with_name_prefix,
    )

    def next_marker_time(after_idx: int):
        for midx, t, _ in markers:
            if midx > after_idx:
                return t
        return None

    known_speakers = set(speakers.keys()) | (set(meta.keys()) - timestamp_meta_keys)
    for idx, (k, _v) in enumerate(comms_lines_prepared):
        if idx in marker_indices:
            continue
        if k not in known_speakers:
            raise ValueError(f"Unknown speaker key {k!r} in [comms] at index {idx}")

    markers_by_index = {midx: (t, cps) for midx, t, cps in markers}

    # Second pass: generate dialogue lines with rails
    meta_non_timestamp_keys = set(meta.keys()) - timestamp_meta_keys
    speaker_keys = set(speakers.keys())

    def _scale_durations_to_fit(durations: list[timedelta], max_ms: int) -> list[int]:
        est_ms = [max(1, int(d.total_seconds() * 1000)) for d in durations]
        sum_est = sum(est_ms)

        if max_ms <= 0 or sum_est <= max_ms:
            return est_ms if max_ms > 0 else [1 for _ in est_ms]

        scale = max_ms / max(1, sum_est)
        scaled_ms = [max(1, int(ms * scale)) for ms in est_ms]

        drift = sum(scaled_ms) - max_ms
        k = 0
        while drift > 0 and k < len(scaled_ms):
            if scaled_ms[k] > 1:
                scaled_ms[k] -= 1
                drift -= 1
            else:
                k += 1

        return scaled_ms

    pending_events: list[tuple[timedelta, int, str]] = []

    # track earliest start and latest end for metadata
    earliest_start = None
    latest_end = None

    i = 0
    while i < len(comms_lines_prepared):
        if i not in markers_by_index:
            raise ValueError("First [comms] entry must be a timestamp marker (e.g. T=...).")

        block_start, block_cps = markers_by_index[i]
        block_end = next_marker_time(i)

        j = i + 1
        block_msgs: list[tuple[str, str]] = []
        while j < len(comms_lines_prepared) and j not in marker_indices:
            block_msgs.append(comms_lines_prepared[j])
            j += 1

        if not block_msgs:
            i = j
            continue

        speaker_msgs: list[tuple[str, str]] = []
        meta_msgs: list[tuple[str, str]] = []
        for mkey, mval in block_msgs:
            if mkey in meta_non_timestamp_keys and mkey not in speaker_keys:
                meta_msgs.append((mkey, mval))
            else:
                speaker_msgs.append((mkey, mval))

        is_bounded = block_end is not None and block_end > block_start
        max_ms = int((block_end - block_start).total_seconds() * 1000) if is_bounded else 0

        # Speakers rail
        speaker_est = [
            estimate_duration(mval, cps=block_cps, acronyms=acronyms, waypoints=literal_waypoints)
            for _, mval in speaker_msgs
        ]
        if is_bounded:
            speaker_ms = _scale_durations_to_fit(speaker_est, max_ms)
        else:
            speaker_ms = [max(1, int(d.total_seconds() * 1000)) for d in speaker_est]

        # Meta rail
        meta_est: list[timedelta] = []
        for mkey, mval in meta_msgs:
            mtype = (meta.get(mkey, {}).get("type") or "").strip().lower()
            if mtype == "comment":
                text = mval or ""
                seconds = len(text) / max(0.001, block_cps)
                meta_est.append(timedelta(milliseconds=int(seconds * 1000)))
            else:
                meta_est.append(
                    estimate_duration(mval, cps=block_cps, acronyms=acronyms, waypoints=literal_waypoints)
                )
        if is_bounded:
            meta_ms = _scale_durations_to_fit(meta_est, max_ms)
        else:
            meta_ms = [max(1, int(d.total_seconds() * 1000)) for d in meta_est]

        # Emit speaker rail
        speakers_current = block_start
        for (mkey, mval), dur_ms in zip(speaker_msgs, speaker_ms, strict=True):
            start_time = speakers_current
            end_time = start_time + timedelta(
                milliseconds=dur_ms if dur_ms > 0 else int(fallback_duration.total_seconds() * 1000)
            )

            # update metadata tracking
            if earliest_start is None or start_time < earliest_start:
                earliest_start = start_time
            if latest_end is None or end_time > latest_end:
                latest_end = end_time

            text_val = mval
            wrapped_text, line_count, max_units = wrap_ass_text(text_val, max_units_per_line)

            sr = style_render.get(mkey) or {}
            
            bg_ev = create_bg_event(
                sr=sr,
                line_count=line_count,
                max_line_units=max_units,
                start=start_time,
                end=end_time,
                play_res_x=play_res_x,
                play_res_y=play_res_y,
            )
            if bg_ev:
                pending_events.append(bg_ev)

            line = (
                f"Dialogue: 0,{format_time(start_time)},{format_time(end_time)},{mkey},"
                f"{escape_ass_text(get_speaker_style(mkey, speakers, types, meta)['display_name'])},0,0,0,,"
                f"{{\\q2}}{escape_ass_text(wrapped_text)}"
            )
            pending_events.append((start_time, 0, line))
            speakers_current = end_time

        # Emit meta rail
        meta_current = block_start
        for (mkey, mval), dur_ms in zip(meta_msgs, meta_ms, strict=True):
            start_time = meta_current
            end_time = start_time + timedelta(
                milliseconds=dur_ms if dur_ms > 0 else int(fallback_duration.total_seconds() * 1000)
            )

            # update metadata tracking
            if earliest_start is None or start_time < earliest_start:
                earliest_start = start_time
            if latest_end is None or end_time > latest_end:
                latest_end = end_time

            text_val = mval
            wrapped_text, line_count, max_units = wrap_ass_text(text_val, max_units_per_line)

            sr = style_render.get(mkey) or {}

            bg_ev = create_bg_event(
                sr=sr,
                line_count=line_count,
                max_line_units=max_units,
                start=start_time,
                end=end_time,
                play_res_x=play_res_x,
                play_res_y=play_res_y,
            )
            if bg_ev:
                pending_events.append(bg_ev)

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

    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    ass_text = "\n".join(ass_file)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_text)

    metadata = {
        "start_seconds": earliest_start.total_seconds() if earliest_start is not None else None,
        "end_seconds": latest_end.total_seconds() if latest_end is not None else None,
        "playres": (play_res_x, play_res_y),
    }

    return metadata
