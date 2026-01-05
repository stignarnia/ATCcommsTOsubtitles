from collections.abc import Mapping

def parse_bool(value: object) -> bool | None:
    """
    Parse common INI booleans.
    Returns True/False when value is recognized, else None.
    """
    s = str(value or "").strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None

def pick_str(*values: object, default: str) -> str:
    """Return the first non-empty string among values, else default."""
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return default

def pick_bool(*values: object, default: bool) -> bool:
    """Return the first parseable bool among values, else default."""
    for v in values:
        parsed = parse_bool(v)
        if parsed is None:
            continue
        return parsed
    return bool(default)

def _speaker_info_for_key(
    speaker_key: str,
    speakers: Mapping[str, Mapping[str, str]],
    meta: Mapping[str, Mapping[str, str]] | None,
) -> Mapping[str, str]:
    info = speakers.get(speaker_key)
    if info is not None:
        return info
    if meta and speaker_key in meta:
        return meta[speaker_key]
    return {}

def _type_info_for_speaker_info(
    speaker_info: Mapping[str, str],
    types: Mapping[str, Mapping[str, str]],
) -> Mapping[str, str]:
    stype = (speaker_info.get("type") or "").strip()
    if not stype:
        return {}
    return types.get(stype, {})

def get_effective_speaker_str(
    speaker_key: str,
    attr: str,
    *,
    speakers: Mapping[str, Mapping[str, str]],
    types: Mapping[str, Mapping[str, str]],
    meta: Mapping[str, Mapping[str, str]] | None = None,
    default: str = "",
) -> str:
    """
    Resolve a speaker/meta attribute with standard precedence:

    1) [speakers.<KEY>].<attr> or [meta.<KEY>].<attr>
    2) [speakerTypes.<Type>].<attr> or [metaTypes.<Type>].<attr>
    3) default
    """
    speaker_info = _speaker_info_for_key(speaker_key, speakers, meta)
    type_info = _type_info_for_speaker_info(speaker_info, types)
    return pick_str(speaker_info.get(attr), type_info.get(attr), default=default)

def get_effective_speaker_bool(
    speaker_key: str,
    attr: str,
    *,
    speakers: Mapping[str, Mapping[str, str]],
    types: Mapping[str, Mapping[str, str]],
    meta: Mapping[str, Mapping[str, str]] | None = None,
    default: bool = False,
) -> bool:
    """
    Resolve a speaker/meta boolean attribute with standard precedence:

    1) [speakers.<KEY>].<attr> or [meta.<KEY>].<attr>
    2) [speakerTypes.<Type>].<attr> or [metaTypes.<Type>].<attr>
    3) default
    """
    speaker_info = _speaker_info_for_key(speaker_key, speakers, meta)
    type_info = _type_info_for_speaker_info(speaker_info, types)
    return pick_bool(speaker_info.get(attr), type_info.get(attr), default=default)