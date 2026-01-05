from datetime import timedelta

import webcolors

def escape_ass_text(text: str) -> str:
    """Escape text for ASS Dialogue lines (minimal escaping)."""
    # Curly braces start override blocks in ASS.
    return text.replace("{", r"\{").replace("}", r"\}")

def ass_color(color_value: str, *, keep_alpha: bool = False) -> str:
    """
    Convert a CSS-ish color string into ASS color format (&H[AABBGGRR]).

    Supports:
      - #RRGGBB
      - #RRGGBBAA (RGBA). Alpha is optionally preserved by setting keep_alpha=True.
      - named colors via `webcolors`

    Notes:
      - ASS alpha is inverted vs. common RGBA notation: 00 = opaque, FF = transparent.
      - When keep_alpha=False, alpha is always forced to 00 (opaque).
    """
    if not color_value:
        return "&H00FFFFFF"

    s = color_value.strip()
    if s.startswith("#"):
        hexv = s[1:]
        alpha = "00"

        # RGBA: #RRGGBBAA
        if len(hexv) == 8:
            css_alpha = int(hexv[6:8], 16)
            if keep_alpha:
                ass_alpha = 255 - css_alpha
                alpha = f"{ass_alpha:02X}"
            hexv = hexv[0:6]

        if len(hexv) == 6:
            r = int(hexv[0:2], 16)
            g = int(hexv[2:4], 16)
            b = int(hexv[4:6], 16)
            return f"&H{alpha}{b:02X}{g:02X}{r:02X}"

        return "&H00FFFFFF"

    try:
        rgb = webcolors.name_to_rgb(s.lower())
        return f"&H00{rgb.blue:02X}{rgb.green:02X}{rgb.red:02X}"
    except Exception:
        return "&H00FFFFFF"

def split_ass_color(ass: str) -> tuple[str, str]:
    """
    Split an ASS color string (&HAABBGGRR) into (AA, BBGGRR) for use with overrides:
      - \\1a&HAA&
      - \\1c&HBBGGRR&
    """
    s = (ass or "").strip()
    if s.startswith("&H"):
        s = s[2:]
    if len(s) == 8:
        return s[0:2], s[2:8]
    return "00", "000000"

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
