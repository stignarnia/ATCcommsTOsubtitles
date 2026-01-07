from datetime import timedelta

from ass_format import format_time, split_ass_color

# Layout constants
FONT_SIZE = 56
MARGIN_L = 20
MARGIN_R = 20
MARGIN_V = 20
BG_LINE_H = int(FONT_SIZE * 1.10)
BG_PAD_Y = 15
BG_PAD_X = 20
WIDTH_SCALE = 1
BG_CORNER_R = 18

def _char_width_units(ch: str) -> float:
    if ch in " .,:;!|'`":
        return 0.24
    if ch in "ilI1[]()":
        return 0.30
    if ch in "MW@#%":
        return 0.85
    if ch.isupper() or ch.isdigit():
        return 0.62
    return 0.46

def get_max_units_per_line(play_res_x: int, wrap_width_ratio: float) -> float:
    usable_px = max(1, play_res_x - MARGIN_L - MARGIN_R)
    target_wrap_px = max(1, int(usable_px * wrap_width_ratio))
    return target_wrap_px / max(1, FONT_SIZE)

def wrap_ass_text(text: str, max_units_per_line: float) -> tuple[str, int, float]:
    # Normalize newlines to ASS breaks
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")

    out_lines: list[str] = []
    max_units_seen = 0.0

    for seg in raw.split("\\N"):
        words = seg.split()
        if not words:
            out_lines.append("")
            continue

        current_words: list[str] = []
        current_units = 0.0

        for w in words:
            w_units = sum(_char_width_units(ch) for ch in w)
            space_units = _char_width_units(" ")

            if not current_words:
                current_words = [w]
                current_units = w_units
                continue

            if current_units + space_units + w_units <= max_units_per_line:
                current_words.append(w)
                current_units += space_units + w_units
            else:
                out_lines.append(" ".join(current_words))
                max_units_seen = max(max_units_seen, current_units)
                current_words = [w]
                current_units = w_units

        out_lines.append(" ".join(current_words))
        max_units_seen = max(max_units_seen, current_units)

    line_count = max(1, len(out_lines))
    return "\\N".join(out_lines), line_count, max_units_seen

def get_box_height_px(line_count: int) -> int:
    return (max(1, int(line_count)) * BG_LINE_H) + (2 * BG_PAD_Y)

def get_text_core_width_px(max_units: float) -> int:
    return max(1, int(max(0.0, float(max_units)) * FONT_SIZE * WIDTH_SCALE))

def get_bg_y_top(alignment: int, height: int, play_res_y: int) -> int:
    # 7,8,9=top; 4,5,6=middle; 1,2,3=bottom
    if alignment in (7, 8, 9):
        return MARGIN_V - BG_PAD_Y
    if alignment in (4, 5, 6):
        return (play_res_y // 2) - (height // 2)
    return play_res_y - MARGIN_V + BG_PAD_Y - height

def get_bg_box_x(alignment: int, text_w: int, play_res_x: int) -> tuple[int, int]:
    # 1,4,7=left; 2,5,8=center; 3,6,9=right
    if alignment in (1, 4, 7):
        text_left = MARGIN_L
    elif alignment in (2, 5, 8):
        text_left = (play_res_x // 2) - (text_w // 2)
    else:
        text_left = play_res_x - MARGIN_R - text_w

    text_right = text_left + text_w

    box_left = text_left - BG_PAD_X
    box_right = text_right + BG_PAD_X

    # Clamp box within video frame
    if box_right > play_res_x:
        shift = box_right - play_res_x
        box_left -= shift
        box_right = play_res_x

    if box_left < 0:
        shift = -box_left
        box_left = 0
        box_right = min(play_res_x, box_right + shift)

    box_width = max(1, int(box_right - box_left))
    box_left = max(0, min(int(box_left), play_res_x - box_width))
    return int(box_left), box_width

def _rounded_rect_path(width: int, height: int, r: int) -> str:
    r = max(0, min(int(r), int(width // 2), int(height // 2)))
    if r <= 0:
        return f"m 0 0 l {width} 0 l {width} {height} l 0 {height} l 0 0"

    k = int(round(r * 0.5522847498))

    return (
        f"m {r} 0 "
        f"l {width - r} 0 "
        f"b {width - r + k} 0 {width} {r - k} {width} {r} "
        f"l {width} {height - r} "
        f"b {width} {height - r + k} {width - r + k} {height} {width - r} {height} "
        f"l {r} {height} "
        f"b {r - k} {height} 0 {height - r + k} 0 {height - r} "
        f"l 0 {r} "
        f"b 0 {r - k} {r - k} 0 {r} 0"
    )

def create_bg_event(
    *,
    sr: dict[str, object],
    line_count: int,
    max_line_units: float,
    start: timedelta,
    end: timedelta,
    play_res_x: int,
    play_res_y: int,
) -> tuple[timedelta, int, str] | None:
    if not sr.get("has_bg"):
        return None

    threshold = int(sr.get("background_lines_threshold", 1))
    if line_count < threshold:
        return None

    bg_alpha, bg_bbggrr = split_ass_color(str(sr.get("bg_ass", "&H00000000")))
    alignment = int(sr.get("alignment", 1))

    height = get_box_height_px(line_count)
    y_top = get_bg_y_top(alignment, height, play_res_y)

    text_w = get_text_core_width_px(max_line_units)
    x_left, width = get_bg_box_x(alignment, text_w, play_res_x)

    path = _rounded_rect_path(width, height, BG_CORNER_R)

    bg_text = (
        f"{{\\p1\\pos({x_left},{y_top})\\an7\\bord0\\shad0\\1c&H{bg_bbggrr}&\\1a&H{bg_alpha}&}}"
        f"{path}"
        f"{{\\p0}}"
    )

    bg_line = f"Dialogue: 0,{format_time(start)},{format_time(end)},Default,,0,0,0,,{bg_text}"
    return (start, -1, bg_line)
