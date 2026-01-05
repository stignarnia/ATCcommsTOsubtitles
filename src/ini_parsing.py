import configparser

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

def load_acronyms(config: configparser.ConfigParser) -> dict[str, str]:
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

def load_waypoints(path: str | None = None, lines: list[str] | None = None) -> dict[str, set[str]]:
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
