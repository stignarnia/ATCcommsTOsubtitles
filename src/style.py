def get_speaker_style(
    speaker_key: str,
    speakers: dict[str, dict[str, str]],
    types: dict[str, dict[str, str]],
    meta: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """Get effective style attributes for a speaker/meta key.

    Precedence (highest to lowest):
    1) Per-key overrides under [speakers.<KEY>] or [meta.<KEY>]
    2) Type defaults under [speakerTypes.<Type>] or [metaTypes.<Type>]
    3) Hard-coded defaults
    """
    meta = meta or {}

    def _pick(*values: object, default: str) -> str:
        """Return the first non-empty string among values, else default."""
        for v in values:
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        return default

    # Prefer explicit speaker entry if present; else use meta.<KEY> as a "virtual speaker".
    speaker_info = speakers.get(speaker_key)
    if not speaker_info and speaker_key in meta:
        speaker_info = dict(meta[speaker_key])

    speaker_info = speaker_info or {}

    speaker_type = _pick(speaker_info.get("type"), default="")
    type_info = types.get(speaker_type, {}) if speaker_type else {}

    # Position normalization is handled separately so callers can map to ASS alignments.
    return {
        "display_name": _pick(speaker_info.get("name"), default=speaker_key),
        "position": _pick(speaker_info.get("position"), type_info.get("position"), default="bottom-left"),
        "color": _pick(speaker_info.get("color"), type_info.get("color"), default="white"),
        "background": _pick(speaker_info.get("background"), type_info.get("background"), default="none"),
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

def position_to_alignment(pos: str | None) -> int:
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
