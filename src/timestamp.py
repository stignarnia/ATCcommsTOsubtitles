from datetime import timedelta

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
