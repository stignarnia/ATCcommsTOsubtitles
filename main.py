import configparser
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
    """Format a timedelta into ASS time format (H:MM:SS.mmm)."""
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:01d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

def get_speaker_style(
    speaker_key: str, speakers: dict[str, dict[str, str]], types: dict[str, dict[str, str]]
) -> dict[str, str]:
    """Get effective style attributes for a speaker (type defaults + speaker overrides)."""
    speaker_info = speakers.get(speaker_key, {})
    speaker_type = speaker_info.get("type")
    type_info = types.get(speaker_type, {})

    return {
        "display_name": speaker_info.get("name", speaker_key),
        "position": type_info.get("position", "Left"),
        "color": speaker_info.get("color", type_info.get("color", "white")),
    }

def parse_comms_lines(path: str) -> list[tuple[str, str]]:
    """
    Parse the [comms] section preserving repeated keys and original order.

    Returns: list[tuple[str, str]] of (KEY, VALUE) where KEY is uppercased.
    """
    lines = []
    in_comms = False
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
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
            lines.append((k.strip().upper(), v.strip()))
    return lines

def parse_ini_non_comms(path: str) -> configparser.ConfigParser:
    """
    Parse everything except [comms].

    We can't directly use ConfigParser on the whole file because [comms]
    contains repeated keys (APP=..., APP=...) which triggers DuplicateOptionError
    when strict=True. So we manually strip out the [comms] section first.
    """
    kept_lines = []
    in_comms = False
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                in_comms = (section == "comms")
                if not in_comms:
                    kept_lines.append(raw)
                continue

            if in_comms:
                continue

            kept_lines.append(raw)

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

def estimate_spoken_length(text: str, acronyms: dict[str, str] | None = None) -> int:
    """
    Estimate "spoken character length" (unitless) based on:
      - acronym expansions from [acronyms.*] computed FIRST (e.g. "FL350" -> "Flight Level 350")
      - digits spoken as words (2 -> "two")
      - ALL-UPPERCASE tokens (A-Z0-9) spoken as NATO letters (DLH97V -> delta lima hotel nine seven victor)
        (but if an uppercase letter is followed by a lowercase one, that token is not treated as ALL-UPPERCASE)
      - otherwise count characters as-is

    This is a heuristic used for duration estimation (cps).
    """
    acronyms = acronyms or {}

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
            # Speak the expansion (normal words) + then process the suffix (often digits).
            total += estimate_spoken_length(acronyms[prefix], acronyms={})
            if suffix:
                total += 1  # word boundary
                total += estimate_spoken_length(suffix, acronyms={})
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

        if is_all_caps_token:
            for ch in stripped:
                if ch.isdigit():
                    total += _DIGIT_WORD_LEN.get(ch, 1) + 1  # + space
                elif ch.isupper():
                    total += _NATO_LEN.get(ch, 1) + 1  # + space
            continue

        # Normal token: expand digits only
        for ch in token:
            if ch.isdigit():
                total += _DIGIT_WORD_LEN.get(ch, 1)
            else:
                total += 1

        # Add a space boundary
        total += 1

    return max(0, total)

def estimate_duration(
    text: str, cps: float = 15.0, acronyms: dict[str, str] | None = None
) -> timedelta:
    """
    Estimate speaking duration using characters-per-second.
    No minimum.
    """
    spoken_len = estimate_spoken_length(text, acronyms=acronyms)
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

def main() -> None:
    # Parse non-[comms] sections normally, but parse [comms] manually to preserve
    # repeated keys and ordering.
    config = parse_ini_non_comms('comms.ini')
    comms_lines = parse_comms_lines('comms.ini')

    ass_file = []

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

    types = {s.split('.')[-1]: dict(config.items(s)) for s in config.sections() if s.startswith('types.')}
    speakers = {s.split('.')[-1]: dict(config.items(s)) for s in config.sections() if s.startswith('speakers.')}
    acronyms = _load_acronyms(config)
    
    # Use stable ASS style names (speaker keys), not display names that may contain spaces.
    for speaker_key in speakers:
        style = get_speaker_style(speaker_key, speakers, types)

        color = ass_color(style["color"])

        # Determine alignment
        alignment = 1  # Left
        if style["position"] == "Right":
            alignment = 3
        elif style["position"] == "Center":
            alignment = 2

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

    # Timestamp format from INI is used only for interpreting T tags.
    t_fmt = types.get("Timestamp", {}).get("format", "mm:ss")
    speech_cps = float(types.get("Timestamp", {}).get("cps", "15"))

    # First pass: collect all explicit T markers (index + time)
    markers: list[tuple[int, timedelta]] = []
    for idx, (key, value) in enumerate(comms_lines):
        if key == "T":
            markers.append((idx, parse_timestamp_to_timedelta(value, t_fmt)))

    # Helper: find the next marker time after a given index
    def next_marker_time(after_idx: int):
        for i, t in markers:
            if i > after_idx:
                return t
        return None

    # Validate comms speaker keys early (ignore T markers).
    known_speakers = set(speakers.keys())
    for idx, (k, _v) in enumerate(comms_lines):
        if k != "T" and k not in known_speakers:
            raise ValueError(f"Unknown speaker key {k!r} in [comms] at index {idx}")

    # Second pass: generate dialogue lines.
    # Timing behavior:
    # - Within a block (from a T to the next T), allocate the available time
    #   across the messages in that block.
    # - If the block has no next T, fall back to fixed 5s per message.
    i = 0
    while i < len(comms_lines):
        key, value = comms_lines[i]

        if key != "T":
            # Disallow implicit timing without a preceding T; otherwise we'd need a global
            # timeline and rules for where it should start.
            raise ValueError("First [comms] entry must be T=... (timestamp).")

        # key == "T": start of a timed block
        block_start = parse_timestamp_to_timedelta(value, t_fmt)
        current_time = block_start

        block_end = next_marker_time(i)
        # Collect messages until next T (or EOF)
        j = i + 1
        block_msgs = []
        while j < len(comms_lines) and comms_lines[j][0] != "T":
            block_msgs.append(comms_lines[j])
            j += 1

        if not block_msgs:
            i = j
            continue

        # Estimate per-line durations (smart), then clamp to fit before next T.
        est = [estimate_duration(mval, cps=speech_cps, acronyms=acronyms) for _, mval in block_msgs]

        if block_end is None or block_end <= block_start:
            # No max bound: just use estimated durations, but ensure monotonic progress
            for (mkey, mval), dur in zip(block_msgs, est, strict=True):
                start_time = current_time
                end_time = start_time + (dur if dur.total_seconds() > 0 else fallback_duration)

                ass_file.append(
                    f"Dialogue: 0,{format_time(start_time)},{format_time(end_time)},{mkey},{escape_ass_text(get_speaker_style(mkey, speakers, types)['display_name'])},0,0,0,,{escape_ass_text(mval)}"
                )
                current_time = end_time
        else:
            max_total = block_end - block_start
            max_ms = int(max_total.total_seconds() * 1000)

            est_ms = [max(1, int(d.total_seconds() * 1000)) for d in est]  # avoid 0ms lines
            sum_est = sum(est_ms)

            if sum_est <= max_ms:
                scaled_ms = est_ms
            else:
                # Linear reduction: scale all durations by same factor so they fit before next T.
                scale = max_ms / max(1, sum_est)
                scaled_ms = [max(1, int(ms * scale)) for ms in est_ms]

                # Fix rounding drift so total fits exactly (or as close as possible) without exceeding.
                drift = sum(scaled_ms) - max_ms
                k = 0
                while drift > 0 and k < len(scaled_ms):
                    if scaled_ms[k] > 1:
                        scaled_ms[k] -= 1
                        drift -= 1
                    else:
                        k += 1

            for (mkey, mval), dur_ms in zip(block_msgs, scaled_ms, strict=True):
                start_time = current_time
                end_time = start_time + timedelta(milliseconds=dur_ms)

                ass_file.append(
                    f"Dialogue: 0,{format_time(start_time)},{format_time(end_time)},{mkey},{escape_ass_text(get_speaker_style(mkey, speakers, types)['display_name'])},0,0,0,,{escape_ass_text(mval)}"
                )
                current_time = end_time

        i = j


    with open("comms.ass", "w", encoding="utf-8") as f:
        f.write("\n".join(ass_file))

if __name__ == "__main__":
    main()
