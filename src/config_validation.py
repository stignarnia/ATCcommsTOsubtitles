def is_timestamp_name(name: str) -> bool:
    return (name or "").strip().lower() == "timestamp"

def ensure_no_timing_keys(info: dict, subject: str) -> None:
    if "format" in info or "cps" in info:
        raise ValueError(f"{subject} may not define 'format' or 'cps' (only 'Timestamp' may)")

def ensure_no_visual_keys(info: dict, subject: str) -> None:
    if "position" in info or "color" in info or "background" in info:
        raise ValueError(f"{subject} must not define 'position', 'color' or 'background'")
