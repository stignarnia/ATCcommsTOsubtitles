import re
from collections.abc import Mapping

from ini_parsing import strip_outer_quotes
from style import get_speaker_style

def build_speaker_display_name_map(
    speakers: dict[str, dict[str, str]],
    types: dict[str, dict[str, str]],
    meta: dict[str, dict[str, str]],
) -> dict[str, str]:
    """
    Build a mapping of speaker keys (IDs used in [comms]) to their display names.

    This is used for *visual* substitutions inside subtitle text (and therefore affects
    CPS/duration estimation too, because we run substitutions before duration estimation).
    """
    out: dict[str, str] = {}
    for speaker_key in speakers.keys():
        style = get_speaker_style(speaker_key, speakers, types, meta)
        out[speaker_key] = str(style.get("display_name") or speaker_key)
    return out

def substitute_speaker_ids(text: str, speaker_id_to_name: Mapping[str, str]) -> str:
    """
    Replace any occurrence of a speaker ID in the text with that speaker's display name.

    Matching rule: replace only when the ID is not part of a larger alphanumeric token.
    This avoids replacing inside other words/callsigns.
    """
    if not text:
        return text
    if not speaker_id_to_name:
        return text

    # Replace longer keys first to avoid partial replacements (e.g., "ATC1" before "ATC").
    keys = sorted((k for k in speaker_id_to_name.keys() if k), key=len, reverse=True)

    out = text
    for k in keys:
        name = speaker_id_to_name.get(k) or k
        if not name or name == k:
            continue

        # Boundary = not adjacent to an alphanumeric character.
        # This allows punctuation around the key: "ATC1," "(ATC1)" etc.
        pattern = rf"(?<![A-Za-z0-9]){re.escape(k)}(?![A-Za-z0-9])"
        out = re.sub(pattern, str(name), out)

    return out

def apply_visual_substitutions(
    *,
    comms_lines: list[tuple[str, str]],
    marker_indices: set[int],
    speakers: dict[str, dict[str, str]],
    types: dict[str, dict[str, str]],
    meta: dict[str, dict[str, str]],
) -> list[tuple[str, str]]:
    """
    Apply all visual substitutions to the comms lines, exactly once.

    This returns a prepared list of (key, value) tuples where:
    - timestamp marker lines are unchanged
    - non-marker text values are unquoted and have substitutions applied

    Future substitutions should be added here without touching generate_ass().
    """
    speaker_id_to_name = build_speaker_display_name_map(speakers, types, meta)

    prepared: list[tuple[str, str]] = []
    for idx, (k, v) in enumerate(comms_lines):
        if idx in marker_indices:
            prepared.append((k, v))
            continue

        text = strip_outer_quotes(v)
        text = substitute_speaker_ids(text, speaker_id_to_name)
        prepared.append((k, text))

    return prepared
