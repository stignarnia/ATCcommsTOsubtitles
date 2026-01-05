from datetime import timedelta

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

def estimate_spoken_length(
    text: str,
    acronyms: dict[str, str] | None = None,
    waypoints: set[str] | None = None,
    visited_acronyms: set[str] | None = None,
) -> int:
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
                total += estimate_spoken_length(
                    acronyms[prefix],
                    acronyms=acronyms,
                    waypoints=waypoints,
                    visited_acronyms=visited,
                )
                if suffix:
                    total += 1  # word boundary
                    total += estimate_spoken_length(
                        suffix,
                        acronyms=acronyms,
                        waypoints=waypoints,
                        visited_acronyms=visited,
                    )
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
            if (
                ch == "."
                and idx > 0
                and idx < len(token) - 1
                and token[idx - 1].isdigit()
                and token[idx + 1].isdigit()
            ):
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
    text: str,
    cps: float = 15.0,
    acronyms: dict[str, str] | None = None,
    waypoints: set[str] | None = None,
) -> timedelta:
    """
    Estimate speaking duration using characters-per-second.
    No minimum.
    """
    spoken_len = estimate_spoken_length(text, acronyms=acronyms, waypoints=waypoints)
    seconds = spoken_len / max(0.001, cps)
    return timedelta(milliseconds=int(seconds * 1000))
