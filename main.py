import argparse
import configparser
import os
from datetime import timedelta
import webcolors

def escape_ass_text(text: str) -> str:
    """Escape text for ASS Dialogue lines (minimal escaping)."""
    # Curly braces start override blocks in ASS.
    return text.replace("{", r"\{").replace("}", r"\}")

def ass_color(color_value: str) -> str:
    """
    Convert a CSS-ish color string into ASS color format (&H00BBGGRR).

    Supports:
      - #RRGGBB
      - #AARRGGBB (alpha ignored)
      - named colors via `webcolors`
    """
    if not color_value:
        return "&H00FFFFFF"

    s = color_value.strip()
    if s.startswith("#"):
        hexv = s[1:]
        if len(hexv) == 8:  # AARRGGBB
            hexv = hexv[2:]
        if len(hexv) == 6:
            r = int(hexv[0:2], 16)
            g = int(hexv[2:4], 16)
            b = int(hexv[4:6], 16)
            return f"&H00{b:02X}{g:02X}{r:02X}"
        return "&H00FFFFFF"

    try:
        rgb = webcolors.name_to_rgb(s.lower())
        return f"&H00{rgb.blue:02X}{rgb.green:02X}{rgb.red:02X}"
    except Exception:
        return "&H00FFFFFF"

def format_time(td: timedelta) -> str:
    """Format a timedelta into ASS/SSA time format (H:MM:SS.cc).

    Note: ASS event timestamps use centiseconds (1/100s), not milliseconds.
    VLC/libass may misinterpret a `.mmm` suffix as centiseconds, causing large overlaps.
    """
    # Work in integer milliseconds to avoid float rounding.
    total_ms = td.days * 86_400_000 + td.seconds * 1000 + (td.microseconds // 1000)

    total_seconds, ms_remainder = divmod(total_ms, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    centiseconds = ms_remainder // 10  # floor to 0..99
    return f"{hours:01d}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"

def get_speaker_style(
    speaker_key: str,
    speakers: dict[str, dict[str, str]],
    types: dict[str, dict[str, str]],
    meta: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """Get effective style attributes for a speaker (type defaults + speaker overrides).
    Supports "meta" mappings (e.g. C -> Comment) for non-speaker keys declared under [meta.*]."""
    meta = meta or {}
    # Prefer explicit speaker entry if present
    speaker_info = speakers.get(speaker_key)
    if not speaker_info and speaker_key in meta:
        # Synthesize minimal speaker_info from meta mapping (meta.* sections may only declare type/name).
        m = meta[speaker_key]
        speaker_info = {"name": m.get("name", speaker_key), "type": m.get("type")}

    speaker_info = speaker_info or {}
    speaker_type = speaker_info.get("type")
    type_info = types.get(speaker_type, {})

    # Position normalization is handled separately so callers can map to ASS alignments.
    return {
        "display_name": speaker_info.get("name", speaker_key),
        "position": type_info.get("position", "bottom-left"),
        "color": speaker_info.get("color", type_info.get("color", "white")),
    }

def _normalize_position(pos: str | None) -> str:
    """Normalize a position string into one of the nine canonical tokens:
    '<vertical>-<horizontal>' where vertical in (top,middle,bottom) and
    horizontal in (left,center,right). Defaults to 'bottom-left'.

    Rules:
    - Case-insensitive.
    - If only a vertical token is provided (top/middle/bottom), assume '-left'.
    - If only a horizontal token is provided (left/center/right), assume 'bottom-'.
    """
    if not pos:
        return "bottom-left"

    p = pos.strip().lower()
    p = p.replace("_", "-")

    vertical_map = {"top": "top", "middle": "middle", "center": "middle", "bottom": "bottom"}
    horizontal_map = {"left": "left", "center": "center", "right": "right", "middle": "center"}

    parts = [part for part in p.split("-") if part]
    if len(parts) == 1:
        token = parts[0]
        # Prefer horizontal tokens (e.g. "center") so that "center" -> "bottom-center".
        # Fall back to vertical tokens (e.g. "middle") which map to "<vertical>-left".
        if token in horizontal_map:
            return f"bottom-{horizontal_map[token]}"
        if token in vertical_map:
            return f"{vertical_map[token]}-left"
        return "bottom-left"

    # Prefer first two parts when more provided
    v, h = parts[0], parts[1]
    v = vertical_map.get(v, None)
    h = horizontal_map.get(h, None)
    if v and h:
        return f"{v}-{h}"

    # Try swapping in case order was reversed
    v2 = vertical_map.get(parts[1], None)
    h2 = horizontal_map.get(parts[0], None)
    if v2 and h2:
        return f"{v2}-{h2}"

    return "bottom-left"

def _position_to_alignment(pos: str | None) -> int:
    """Map normalized position to ASS alignment (1-9).

    ASS alignment mapping:
      bottom-left=1, bottom-center=2, bottom-right=3,
      middle-left=4, middle-center=5, middle-right=6,
      top-left=7, top-center=8, top-right=9
    """
    norm = _normalize_position(pos)
    mapping = {
        "bottom-left": 1,
        "bottom-center": 2,
        "bottom-right": 3,
        "middle-left": 4,
        "middle-center": 5,
        "middle-right": 6,
        "top-left": 7,
        "top-center": 8,
        "top-right": 9,
    }
    return mapping.get(norm, 1)

def parse_comms_lines(path: str | None = None, lines: list[str] | None = None) -> list[tuple[str, str]]:
    """
    Parse the [comms] section preserving repeated keys and original order.

    Returns: list[tuple[str, str]] of (KEY, VALUE) where KEY is uppercased.
    """
    lines_out = []
    in_comms = False
    iterator = lines if lines is not None else open(path, "r", encoding="utf-8")
    try:
        for raw in iterator:
            line = raw.strip()
            if not line or line.startswith(";") or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                in_comms = (line[1:-1].strip().lower() == "comms")
                continue
            if not in_comms:
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().upper()
            v = v.strip()
            # If the value is wrapped in quotes (to allow apostrophes), remove the outer quotes.
            if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
                v = v[1:-1]
            # Unescape any escaped quotes inside the value.
            v = v.replace('\\"', '"').replace("\\'", "'")
            lines_out.append((k, v))
    finally:
        if lines is None:
            iterator.close()

    return lines_out

def strip_outer_quotes(s: str) -> str:
    """Remove surrounding quotes if present and unescape internal escaped quotes."""
    if not s:
        return s
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        s = s[1:-1]
    return s.replace('\\"', '"').replace("\\'", "'")

def parse_ini_non_comms(path: str | None = None, lines: list[str] | None = None) -> configparser.ConfigParser:
    """
    Parse everything except [comms].

    We can't directly use ConfigParser on the whole file because [comms]
    contains repeated keys (APP=..., APP=...) which triggers DuplicateOptionError
    when strict=True. So we manually strip out the [comms] section first.

    Also exclude any [waypoints.*] sections from the ConfigParser input since
    they contain freeform tokens (one per line) rather than key=value pairs.
    """
    kept_lines = []
    in_comms = False
    iterator = lines if lines is not None else open(path, "r", encoding="utf-8")
    try:
        for raw in iterator:
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                # Exclude both [comms] and [waypoints.*] from the ConfigParser input
                in_comms = (section == "comms" or section.startswith("waypoints."))
                if not in_comms:
                    kept_lines.append(raw)
                continue

            if in_comms:
                continue

            kept_lines.append(raw)
    finally:
        if lines is None:
            iterator.close()

    config = configparser.ConfigParser()
    config.read_string("".join(kept_lines))
    return config

_DIGIT_WORD_LEN = {
    "0": 4,  # zero
    "1": 3,  # one
    "2": 3,  # two
    "3": 5,  # three
    "4": 4,  # four
    "5": 4,  # five
    "6": 3,  # six
    "7": 5,  # seven
    "8": 5,  # eight
    "9": 5,  # niner
}

# NATO phonetic alphabet approximate letter-name lengths (lowercase strings)
_NATO_LEN = {
    "A": 5,  # alfa
    "B": 5,  # bravo
    "C": 7,  # charlie
    "D": 5,  # delta
    "E": 4,  # echo
    "F": 7,  # foxtrot
    "G": 5,  # golf
    "H": 5,  # hotel
    "I": 5,  # india
    "J": 7,  # juliett
    "K": 4,  # kilo
    "L": 4,  # lima
    "M": 4,  # mike
    "N": 6,  # november
    "O": 6,  # oscar
    "P": 4,  # papa
    "Q": 7,  # quebec
    "R": 5,  # romeo
    "S": 6,  # sierra
    "T": 5,  # tango
    "U": 7,  # uniform
    "V": 6,  # victor
    "W": 7,  # whiskey
    "X": 6,  # xray (x-ray)
    "Y": 6,  # yankee
    "Z": 4,  # zulu
}

def _load_acronyms(config: configparser.ConfigParser) -> dict[str, str]:
    """
    Load [acronyms.*] sections.

    Example:
      [acronyms.FL]
      extension = Flight Level

    Returns: {"FL": "Flight Level", ...} with keys uppercased.
    """
    acr = {}
    for s in config.sections():
        if not s.startswith("acronyms."):
            continue
        key = s.split(".", 1)[1].strip().upper()
        ext = config.get(s, "extension", fallback="").strip()
        if key and ext:
            acr[key] = ext
    return acr

def _load_waypoints(path: str | None = None, lines: list[str] | None = None) -> dict[str, set[str]]:
    """
    Load [waypoints.*] sections where each non-empty non-comment line is a waypoint token.
    Returns e.g. {"RNAV": {"LAZET", "RULOX"}} with tokens preserved as written.
    """
    waypoints = {}
    in_section = False
    current = None
    iterator = lines if lines is not None else open(path, "r", encoding="utf-8")
    try:
        for raw in iterator:
            line = raw.strip()
            if not line or line.startswith(";") or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                sec = line[1:-1].strip()
                if sec.lower().startswith("waypoints."):
                    in_section = True
                    current = sec.split(".", 1)[1].strip().upper()
                    waypoints[current] = set()
                else:
                    in_section = False
                    current = None
                continue
            if in_section and current:
                parts = [p.strip() for p in line.split(",") if p.strip()]
                for p in parts:
                    waypoints[current].add(p)
    finally:
        if lines is None:
            iterator.close()

    return waypoints

def _is_timestamp_name(name: str) -> bool:
    return (name or "").strip().lower() == "timestamp"

def _ensure_no_timing_keys(info: dict, subject: str) -> None:
    if "format" in info or "cps" in info:
        raise ValueError(f"{subject} may not define 'format' or 'cps' (only 'Timestamp' may)")

def _ensure_no_visual_keys(info: dict, subject: str) -> None:
    if "position" in info or "color" in info:
        raise ValueError(f"{subject} must not define 'position' or 'color'")

def estimate_spoken_length(text: str, acronyms: dict[str, str] | None = None, waypoints: set[str] | None = None, visited_acronyms: set[str] | None = None) -> int:
    """
    Estimate "spoken character length" (unitless) based on:
      - acronym expansions from [acronyms.*] computed FIRST (e.g. "FL350" -> "Flight Level 350")
      - digits spoken as words (2 -> "two")
      - ALL-UPPERCASE tokens (A-Z0-9) spoken as NATO letters (DLH97V -> delta lima hotel nine seven victor)
        (but if an uppercase letter is followed by a lowercase one, that token is not treated as ALL-UPPERCASE)
      - otherwise count characters as-is

    This is a heuristic used for duration estimation (cps).

    The `waypoints` set (uppercase tokens) disables NATO expansion for matching tokens so
    RNAV waypoints are spoken literally.
    """
    acronyms = acronyms or {}
    waypoints = set(w.upper() for w in (waypoints or set()))
    visited = set(visited_acronyms or ())

    total = 0
    for token in text.split():
        # Strip surrounding punctuation for token classification, but keep punctuation in base count below.
        stripped = token.strip(".,!?;:()[]{}\"'")

        # 1) Acronym expansion timing comes first (before any NATO/digit logic).
        # Support both exact token matches ("FL") and common prefix+digits patterns ("FL350").
        prefix = ""
        suffix = ""
        if stripped:
            k = 0
            while k < len(stripped) and stripped[k].isalpha() and stripped[k].isupper():
                k += 1
            prefix = stripped[:k]
            suffix = stripped[k:]

        if prefix and prefix in acronyms:
            # Avoid infinite recursion when acronym expansions reference each other.
            if prefix in visited:
                # Already expanding this acronym in the current chain — treat literally (fall through).
                pass
            else:
                # Speak the expansion (normal words) + then process the suffix (often digits).
                # Preserve the acronyms mapping so nested expansions work, tracking visited keys.
                visited.add(prefix)
                total += estimate_spoken_length(acronyms[prefix], acronyms=acronyms, waypoints=waypoints, visited_acronyms=visited)
                if suffix:
                    total += 1  # word boundary
                    total += estimate_spoken_length(suffix, acronyms=acronyms, waypoints=waypoints, visited_acronyms=visited)
                total += 1  # space boundary after token
                continue

        # 2) NATO expansion for ALL-UPPERCASE tokens only.
        # Avoid NATO when any uppercase letter is followed by a lowercase letter (e.g. "A321neo").
        has_upper_followed_by_lower = any(
            stripped[i].isupper() and stripped[i + 1].islower()
            for i in range(len(stripped) - 1)
        )

        is_all_caps_token = (
            stripped
            and not has_upper_followed_by_lower
            and all(ch.isupper() or ch.isdigit() for ch in stripped)
            and any(ch.isalpha() for ch in stripped)
        )

        # If this token is a declared waypoint, treat it literally (no NATO expansion).
        if is_all_caps_token and stripped.upper() not in waypoints:
            for ch in stripped:
                if ch.isdigit():
                    total += _DIGIT_WORD_LEN.get(ch, 1) + 1  # + space
                elif ch.isupper():
                    total += _NATO_LEN.get(ch, 1) + 1  # + space
            continue

        # Normal token: expand digits only
        # Treat any dot between two digits as the spoken word "decimal".
        for idx, ch in enumerate(token):
            # Handle dot between two digits as "decimal"
            if ch == "." and idx > 0 and idx < len(token) - 1 and token[idx - 1].isdigit() and token[idx + 1].isdigit():
                total += len("decimal")
                continue
            if ch.isdigit():
                total += _DIGIT_WORD_LEN.get(ch, 1)
            else:
                total += 1

        # Add a space boundary
        total += 1

    return max(0, total)

def estimate_duration(
    text: str, cps: float = 15.0, acronyms: dict[str, str] | None = None, waypoints: set[str] | None = None
) -> timedelta:
    """
    Estimate speaking duration using characters-per-second.
    No minimum.
    """
    spoken_len = estimate_spoken_length(text, acronyms=acronyms, waypoints=waypoints)
    seconds = spoken_len / max(0.001, cps)
    return timedelta(milliseconds=int(seconds * 1000))

def parse_timestamp_to_timedelta(value: str, fmt: str) -> timedelta:
    """
    Parse a T=... tag timestamp according to the INI-defined format.

    Supported fmt tokens:
      - ss
      - mm:ss
      - hh:mm:ss
    Optional fractional milliseconds are supported by appending .ms to the value.
    """
    s = value.strip()
    if not s:
        raise ValueError("Empty timestamp")

    ms = 0
    if "." in s:
        left, frac = s.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit())
        if frac:
            if len(frac) >= 3:
                ms = int(frac[:3])
            else:
                ms = int(frac.ljust(3, "0"))
        s = left

    parts = s.split(":")
    fmt = fmt.strip().lower()

    if fmt == "ss":
        if len(parts) != 1:
            raise ValueError(f"Timestamp {value!r} does not match format {fmt!r}")
        return timedelta(seconds=int(parts[0]), milliseconds=ms)

    if fmt == "mm:ss":
        if len(parts) != 2:
            raise ValueError(f"Timestamp {value!r} does not match format {fmt!r}")
        return timedelta(minutes=int(parts[0]), seconds=int(parts[1]), milliseconds=ms)

    if fmt == "hh:mm:ss":
        if len(parts) != 3:
            raise ValueError(f"Timestamp {value!r} does not match format {fmt!r}")
        return timedelta(
            hours=int(parts[0]),
            minutes=int(parts[1]),
            seconds=int(parts[2]),
            milliseconds=ms,
        )

    raise ValueError(f"Unsupported timestamp format in INI: {fmt!r}")

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
    ass_file.append("WrapStyle: 0")
    ass_file.append("PlayResX: 1920")
    ass_file.append("PlayResY: 1080")
    ass_file.append("")

    # [V4+ Styles]
    ass_file.append("[V4+ Styles]")
    ass_file.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
    
    # Default Style
    ass_file.append("Style: Default,Arial,56,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,1,10,10,10,1")

    # Collect type definitions. Use the new "metaTypes." and "speakerTypes.".
    types = {}
    for s in config.sections():
        if s.startswith("metaTypes.") or s.startswith("speakerTypes."):
            types[s.split(".", 1)[1].strip()] = dict(config.items(s))

    # Validate types: only the 'Timestamp' type may define timing keys;
    # and the 'Timestamp' type must not define visual keys like position/color.
    for tname, tinfo in types.items():
        if _is_timestamp_name(tname):
            _ensure_no_visual_keys(tinfo, f"Type '{tname}'")
        else:
            _ensure_no_timing_keys(tinfo, f"Type '{tname}'")

    # Speakers remain under [speakers.*]
    speakers = {s.split('.')[-1]: dict(config.items(s)) for s in config.sections() if s.startswith('speakers.')}

    # Meta mappings (short tags used in [comms], e.g. [meta.T] or [meta.C])
    meta = {s.split('.')[-1]: dict(config.items(s)) for s in config.sections() if s.startswith('meta.')}

    # Validate meta entries:
    # - Only metas of type 'Timestamp' may provide timing keys (format/cps).
    # - Timestamp metas must not define visual keys (position/color).
    timestamp_meta_keys = set()
    for mk, mv in meta.items():
        mtype = (mv.get("type") or "").strip()
        if not mtype:
            continue
        if _is_timestamp_name(mtype):
            _ensure_no_visual_keys(mv, f"Meta '{mk}' is a Timestamp")
            timestamp_meta_keys.add(mk)
        else:
            _ensure_no_timing_keys(mv, f"Meta '{mk}' has type '{mtype}'")

    acronyms = _load_acronyms(config)
    # Load declared waypoints (e.g. [waypoints.RNAV]) so they are spoken literally, not as NATO.
    waypoints = _load_waypoints(lines=ini_lines)
    # Flatten all waypoint tokens into a set of uppercased tokens for quick membership checks.
    literal_waypoints = set()
    for s in waypoints.values():
        literal_waypoints.update(w.upper() for w in s)

    # Use stable ASS style names (speaker keys and non-timestamp meta keys), not display names that may contain spaces.
    style_keys = list(speakers.keys()) + [k for k in meta.keys() if k not in timestamp_meta_keys]
    for speaker_key in style_keys:
        style = get_speaker_style(speaker_key, speakers, types, meta)

        color = ass_color(style["color"])

        # Determine alignment (map normalized positions to ASS 1-9)
        alignment = _position_to_alignment(style.get("position"))

        ass_file.append(
            f"Style: {speaker_key},Arial,56,{color},&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,{alignment},20,20,20,1"
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

    # Helper: find the next marker time after a given index
    def next_marker_time(after_idx: int):
        for midx, t, _ in markers:
            if midx > after_idx:
                return t
        return None

    # Validate comms speaker keys early (ignore timestamp markers).
    known_speakers = set(speakers.keys()) | (set(meta.keys()) - timestamp_meta_keys)
    for idx, (k, _v) in enumerate(comms_lines):
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

    i = 0
    while i < len(comms_lines):
        if i not in markers_by_index:
            # Disallow implicit timing without a preceding timestamp marker.
            raise ValueError("First [comms] entry must be a timestamp marker (e.g. T=...).")

        # Start of a timed block
        block_start, block_cps = markers_by_index[i]

        block_end = next_marker_time(i)

        # Collect messages until next timestamp marker (or EOF)
        j = i + 1
        block_msgs: list[tuple[str, str]] = []
        while j < len(comms_lines) and j not in marker_indices:
            block_msgs.append(comms_lines[j])
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
            end_time = start_time + timedelta(milliseconds=dur_ms if dur_ms > 0 else int(fallback_duration.total_seconds() * 1000))

            text_val = strip_outer_quotes(mval)
            line = (
                f"Dialogue: 0,{format_time(start_time)},{format_time(end_time)},{mkey},"
                f"{escape_ass_text(get_speaker_style(mkey, speakers, types, meta)['display_name'])},0,0,0,,"
                f"{escape_ass_text(text_val)}"
            )
            pending_events.append((start_time, 0, line))
            speakers_current = end_time

        # Emit meta rail (layer 1 so it draws above speakers if overlapping)
        meta_current = block_start
        for (mkey, mval), dur_ms in zip(meta_msgs, meta_ms, strict=True):
            start_time = meta_current
            end_time = start_time + timedelta(milliseconds=dur_ms if dur_ms > 0 else int(fallback_duration.total_seconds() * 1000))

            text_val = strip_outer_quotes(mval)
            line = (
                f"Dialogue: 1,{format_time(start_time)},{format_time(end_time)},{mkey},"
                f"{escape_ass_text(get_speaker_style(mkey, speakers, types, meta)['display_name'])},0,0,0,,"
                f"{escape_ass_text(text_val)}"
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

def init_template(name: str = "comms.ini") -> None:
    """Create a starter INI file at `name` if it doesn't exist."""
    if os.path.exists(name):
        print(f"File already exists: {name}")
        return

    sample = """; Meta types
[metaTypes.Timestamp]
; Every combination of hours, minutes, seconds and milliseconds is supported for *input parsing*.
; Important: ASS/SSA event timestamps are centiseconds (H:MM:SS.cc), not milliseconds. If an ASS file
; uses ".mmm", VLC/libass can treat that suffix as centiseconds and display events overlapping.
; This project therefore writes centisecond-precision timestamps to the output ASS.
format = mm:ss
; Characters-per-second used for subtitle duration estimation when fitting lines between T markers
cps = 15

[metaTypes.Comment]
position = top-left
color = gray

; Speaker types
[speakerTypes.ATC]
position = bottom-left
color = white

[speakerTypes.Pilot]
position = bottom-right
color = cyan

; Meta tags
[meta.T]
type = Timestamp

[meta.C]
type = Comment

; Speakers
[speakers.APP]
name = Lisboa Approach
type = ATC

[speakers.LH]
name = DLH97V
type = Pilot
color = blue

; Acronyms
[acronyms.FL]
extension = Flight Level

; Waypoints
[waypoints.RNAV]
LAZET

; Comms
; Special characters like the ' in don't should be escaped by wrapping the string in double quotes ("). These will not be rendered in the subtitles
[comms]
T = 00:00
C = Time: 18:50 UTC on December 30, 2025, ATIS K in effect, QNH 1020 hPa
LH = Lisboa Arrival good evening, DLH97V, FL350, inbound to INBOM, Information K
"""

    with open(name, "w", encoding="utf-8") as f:
        f.write(sample)
    print(f"Wrote template INI to {name}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Compile comms INI to ASS or initialize a template INI.")
    parser.add_argument("command", nargs="?", choices=["compile", "init"], default="compile", help="Command to run (default: compile)")
    parser.add_argument("-i", "--input", default="comms.ini", help="Input INI file (for compile)")
    parser.add_argument("-o", "--output", default="comms.ass", help="Output ASS file (for compile)")
    parser.add_argument("--name", default="comms.ini", help="Name for initialized INI file (for init)")

    args = parser.parse_args()

    if args.command == "init":
        init_template(args.name)
    else:
        # compile (default)
        generate_ass(args.input, args.output)

if __name__ == "__main__":
    main()
