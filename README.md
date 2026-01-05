# ATC Comms → ASS Subtitles

Small command-line tool to compile an INI-style transcript of air traffic communications into ASS subtitle files suitable for video overlay.

Highlights
- Keeps `[comms]` entries in order and supports repeated keys (multiple messages per speaker).
- Estimates spoken durations using configurable characters-per-second, NATO alphabet expansion, acronym expansions and waypoint exceptions.
- Generates `ASS` styles per speaker and additional elements on screen; supports simple color names and hex colors.
- Deterministic wrapping: the compiler inserts explicit `\N` line breaks and emits `{\q2}` (no renderer auto-wrap) so line counts are known and consistent across players.
- Speaker IDs mentioned inside message text are substituted with that speaker’s display name before timing + rendering (see `src/visual_substitution.py`).
- Includes an `init` command to scaffold a working example `INI`.

Prerequisites
- `uv` (recommended)

Quick start
- Initialize the example INI:
```bash
uv run src/main.py init --name comms.ini
```
- Compile an INI to ASS:
```bash
uv run src/main.py compile -i comms.ini -o comms.ass
```

Commands
- `compile` (default): read an `INI` and write an `ASS` file.
- `init`: write a starter `INI` template (does not overwrite existing files unless removed).

`INI` structure
- `[metaTypes.<Name>]`
  - Define reusable "type" settings for meta entries (for example `Timestamp` or `Comment`).
  - Common keys:
    - `format` = timestamp format used to parse `T=` values. Supported tokens: `ss`, `mm:ss`, `hh:mm:ss`. Fractional milliseconds are allowed by appending `.ms` to the value (e.g. `00:12.345`).
      - Important: ASS/SSA event times are **centiseconds** (`H:MM:SS.cc`), not milliseconds. The compiler accepts millisecond precision on input, but will quantize output to centiseconds to avoid VLC/libass interpreting `.mmm` as centiseconds and creating long overlaps.
    - `cps` = characters-per-second (`float`) used to estimate spoken duration when fitting messages between `T` markers.
    - `position` = visual position used when generating styles (examples: `bottom-right`, `top-left`, `middle-center`). Speaker and meta styles inherit this if not overridden.
    - `color` = color for generated ASS styles (named color or hex `#RRGGBB` / `#RRGGBBAA`; alpha is ignored for text, preserved for background boxes).
    - `background` = background behind subtitles. Accepts `none` or a color (named color / `#RRGGBB` / `#RRGGBBAA`). When set to a color, subtitles render with an opaque-box background.
  - Usage:
    - Mandatory `Timestamp` meta type:
      ```ini
      [metaTypes.Timestamp]
      format = mm:ss
      cps = 15
      ```
    - Other meta types (e.g. `Comment`):
      ```ini
      [metaTypes.Comment]
      position = top-left
      color = gray
      background = none
      ```

- `[speakerTypes.<Name>]`
  - Default visual properties for speakers of the given type (`position`, `color`, `background`).
  - `show_name` (`true`/`false`, default: `false`):
    - If enabled, speaker lines of this type are rendered as `<speaker display name>: <text>`.
    - Example (with `show_name = true` on the `Pilot` type):
      - Input `[comms]`: `JET = Lisboa Arrival good evening, JET, FL250, inbound to LAZET, Information K`
      - Output subtitle: `N178QS: Lisboa Arrival good evening, N178QS, FL250, inbound to LAZET, Information K`

- `[meta.<Key>]`
  - Can be used in two ways:
    ```ini
    [meta.T]
    type = Timestamp
    ```
    To rename the `Timestamp` token to a shorter key like `T` that is easier to type later. You can also have different `Timestamp` objects and override `format` and `cps` in order to have blocks with different timing rules.
    ```ini
    [meta.C]
    type = Comment
    ```
    Assuming a `Comment` meta type is declared earlier, can be used to give a shorthand key and to override `position`, `color` and `background`. All meta types that aren't `Timestamp` fall into this category.

- `[speakers.<KEY>]`
  - Speaker definitions keyed by stable identifier (used as `ASS` style name). Fields: `name`, `type`, `color` (hex or named color), `background` (`none` or a color), `show_name` (`true`/`false`, default: `false`).

- `[acronyms.<KEY>]`
  - `extension = ...` used to expand acronyms (e.g. FL -> "Flight Level").

- `[waypoints.<GROUP>]`
  - Freeform tokens, one per line or comma separated. Declared tokens are spoken literally (no NATO expansion). Groups are cosmetic only, for example it can be used to distinguish between `RNAV` and `VOR` waypoints.

- `[comms]`
  - The actual transcript.
  - Use `T = <timestamp>` to mark timeline anchors. Following non-`T` lines are treated as messages or meta elements in that block.
  - First `[comms]` entry must be `T=...`.
  - Values may be wrapped in single or double quotes to allow internal apostrophes/quotes. These will be stripped in the final subtitles.

Timing rules (summary)
- Within a `T` block, available time (until next `T`) is allocated across messages.
- If no following `T` exists, estimated durations (or a small fallback) are used.
- Estimation rules:
  - Acronym expansions are applied first.
  - ALL-UPPERCASE tokens (`A-Z0-9`) are expanded to NATO letter names unless listed in waypoints.
  - Digits are counted as spoken words (e.g. "2" → "two").
  - `cps` (characters-per-second) from the timestamp meta type controls conversion to duration.

Wrapping rules (summary)
- The compiler wraps text itself (rather than relying on the subtitle renderer):
  - It inserts explicit ASS line breaks (`\N`).
  - It prepends `{\q2}` to each event so the renderer does not re-wrap lines.
- Wrapping is intentionally aggressive: it targets roughly half the usable screen width to produce taller, more readable blocks and predictable background box sizing.

Color handling
- Supports:
  - `#RRGGBB`
  - `#RRGGBBAA` (alpha ignored for text, preserved for background boxes)
  - Named colors via the `webcolors` package
- Converted into ASS color format (`&H00BBGGRR`).

Notes
- When placing apostrophes in values, wrap the value in double quotes to avoid parsing issues (e.g. "don't").
