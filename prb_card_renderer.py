import re
import struct
import tempfile
import textwrap
import zlib
from pathlib import Path


WIDTH = 1080
HEIGHT = 1350
MARGIN = 64
PRB_TEXT_LEFT = 128
PRB_TEXT_MAX_CHARS = 37
LINE_HEIGHT = 26
BODY_SCALE = 3
PRB_BODY_SCALE = 4
PRB_LINE_HEIGHT = 38
TITLE_SCALE = 5
SMALL_SCALE = 2
MAX_BODY_LINES = 28

BG_TOP = (2, 12, 22)
BG_BOTTOM = (5, 42, 55)
CARD = (10, 30, 42)
CARD_EDGE = (37, 212, 232)
TEXT = (218, 236, 242)
MUTED = (156, 180, 190)
CYAN = (56, 224, 241)
GOLD = (219, 181, 76)
GREEN = (83, 219, 125)
RED = (231, 85, 82)
ALERT_SIGNAL_SCOPE = "Daily signal - snapshot in time, not a trend call"
GHOST_WATERMARK_OPACITY = 0.05
GHOST_WATERMARK_PATHS = (
    Path("assets") / "poinkle_ghost_watermark.png",
    Path("assets") / "poinkle_pig_silhouette.png",
    Path("assets") / "poinkle_silhouette_logo.png",
)
MIKE_WATERMARK_PATH = Path("assets") / "inner_circle_logo.png"
MIKE_WATERMARK_OPACITY = 0.10
MIKE_TABLE_SCALE = BODY_SCALE
MIKE_TABLE_ROW_GAP = 74
MIKE_TABLE_X_OFFSET = 56


FONT = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10011", "10001", "10001", "01110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    " ": ["000", "000", "000", "000", "000", "000", "000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ".": ["000", "000", "000", "000", "000", "011", "011"],
    ":": ["000", "011", "011", "000", "011", "011", "000"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    "(": ["001", "010", "100", "100", "100", "010", "001"],
    ")": ["100", "010", "001", "001", "001", "010", "100"],
    "?": ["01110", "10001", "00001", "00010", "00100", "00000", "00100"],
    "!": ["010", "010", "010", "010", "010", "000", "010"],
    "%": ["11001", "11010", "00010", "00100", "01000", "01011", "10011"],
    "'": ["010", "010", "100", "000", "000", "000", "000"],
    ",": ["000", "000", "000", "000", "011", "011", "010"],
}


def sanitize_text(value):
    replacements = {
        "🐷": "",
        "✅": "",
        "📈": "",
        "🐂": "",
        "🐻": "",
        "❓": "",
        "🔍": "",
        "⚠️": "",
        "📊": "",
        "📌": "",
        "🎓": "",
        "🟢": "",
        "🔴": "",
        "🟡": "",
        "⚪": "",
        "—": "-",
        "→": "->",
        "’": "'",
        "“": '"',
        "”": '"',
        "•": "-",
        "━━━━━━━━━━━━━━━━━━": "",
    }
    text = str(value)
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("ascii", "ignore").decode("ascii").strip()


def text_width(text, scale):
    total = 0
    for char in text.upper():
        pattern = FONT.get(char, FONT[" "])
        total += (len(pattern[0]) + 1) * scale
    return total


def set_pixel(pixels, width, height, x, y, color):
    if 0 <= x < width and 0 <= y < height:
        pixels[y][x] = color


def fill_rect(pixels, width, height, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(height, y1)):
        row = pixels[y]
        for x in range(max(0, x0), min(width, x1)):
            row[x] = color


def draw_text(pixels, width, height, x, y, text, color=TEXT, scale=BODY_SCALE):
    cursor = x
    for char in text.upper():
        pattern = FONT.get(char, FONT[" "])
        for row_idx, row in enumerate(pattern):
            for col_idx, bit in enumerate(row):
                if bit != "1":
                    continue
                fill_rect(
                    pixels,
                    width,
                    height,
                    cursor + col_idx * scale,
                    y + row_idx * scale,
                    cursor + (col_idx + 1) * scale,
                    y + (row_idx + 1) * scale,
                    color,
                )
        cursor += (len(pattern[0]) + 1) * scale


def draw_centered_text(pixels, width, height, y, text, color=TEXT, scale=BODY_SCALE):
    x = max(MARGIN, (width - text_width(text, scale)) // 2)
    draw_text(pixels, width, height, x, y, text, color=color, scale=scale)


def draw_horizontal_line(pixels, width, height, y, color=CYAN):
    fill_rect(pixels, width, height, MARGIN, y, width - MARGIN, y + 3, color)


def make_canvas(width=WIDTH, height=HEIGHT):
    pixels = []
    for y in range(height):
        mix = y / max(height - 1, 1)
        color = tuple(int(BG_TOP[i] * (1 - mix) + BG_BOTTOM[i] * mix) for i in range(3))
        pixels.append([color for _ in range(width)])
    fill_rect(pixels, width, height, 32, 32, width - 32, height - 32, CARD)
    fill_rect(pixels, width, height, 32, 32, width - 32, 36, CARD_EDGE)
    fill_rect(pixels, width, height, 32, height - 36, width - 32, height - 32, CARD_EDGE)
    fill_rect(pixels, width, height, 32, 32, 36, height - 32, CARD_EDGE)
    fill_rect(pixels, width, height, width - 36, 32, width - 32, height - 32, CARD_EDGE)
    draw_ghost_watermark(pixels, width=width, height=height)
    return pixels


def write_png(path, pixels):
    height = len(pixels)
    width = len(pixels[0])
    raw_rows = []
    for row in pixels:
        raw_rows.append(b"\x00" + b"".join(bytes(pixel) for pixel in row))
    raw = b"".join(raw_rows)

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    Path(path).write_bytes(png)


def paeth_predictor(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read_png(path):
    data = Path(path).read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Not a PNG")

    offset = 8
    width = height = color_type = None
    idat = []
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += length + 12
        if kind == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", chunk_data)
            if bit_depth != 8 or compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("Unsupported PNG format")
            if color_type not in (2, 6):
                raise ValueError("Unsupported PNG color type")
        elif kind == b"IDAT":
            idat.append(chunk_data)
        elif kind == b"IEND":
            break

    channels = 4 if color_type == 6 else 3
    stride = width * channels
    raw = zlib.decompress(b"".join(idat))
    rows = []
    prev = [0] * stride
    pos = 0
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        row = list(raw[pos : pos + stride])
        pos += stride
        for i, value in enumerate(row):
            left = row[i - channels] if i >= channels else 0
            up = prev[i]
            upper_left = prev[i - channels] if i >= channels else 0
            if filter_type == 1:
                row[i] = (value + left) & 0xFF
            elif filter_type == 2:
                row[i] = (value + up) & 0xFF
            elif filter_type == 3:
                row[i] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[i] = (value + paeth_predictor(left, up, upper_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError("Unsupported PNG filter")
        prev = row
        pixels = []
        for x in range(width):
            start = x * channels
            if channels == 4:
                pixels.append(tuple(row[start : start + 4]))
            else:
                pixels.append(tuple(row[start : start + 3]) + (255,))
        rows.append(pixels)
    return width, height, rows


def draw_png_image(pixels, logo_path, center_x, top_y, max_width, max_height):
    logo_width, logo_height, logo_pixels = read_png(logo_path)
    scale = min(max_width / logo_width, max_height / logo_height, 1.0)
    draw_width = max(1, int(logo_width * scale))
    draw_height = max(1, int(logo_height * scale))
    left = center_x - draw_width // 2
    for y in range(draw_height):
        source_y = min(logo_height - 1, int(y / scale))
        for x in range(draw_width):
            source_x = min(logo_width - 1, int(x / scale))
            r, g, b, a = logo_pixels[source_y][source_x]
            target_x = left + x
            target_y = top_y + y
            if not (0 <= target_x < WIDTH and 0 <= target_y < HEIGHT):
                continue
            if a >= 255:
                pixels[target_y][target_x] = (r, g, b)
            elif a > 0:
                base = pixels[target_y][target_x]
                alpha = a / 255
                pixels[target_y][target_x] = tuple(int(base[i] * (1 - alpha) + (r, g, b)[i] * alpha) for i in range(3))
    return left, top_y, draw_width, draw_height


def ghost_watermark_path():
    for path in GHOST_WATERMARK_PATHS:
        if Path(path).exists():
            return Path(path)
    return None


def draw_ghost_watermark(
    pixels,
    watermark_path=None,
    opacity=GHOST_WATERMARK_OPACITY,
    width=WIDTH,
    height=HEIGHT,
):
    path = Path(watermark_path) if watermark_path else ghost_watermark_path()
    if not path:
        return False
    try:
        logo_width, logo_height, logo_pixels = read_png(path)
    except Exception:
        return False

    max_width = int(width * 0.72)
    max_height = int(height * 0.62)
    scale = min(max_width / logo_width, max_height / logo_height)
    draw_width = max(1, int(logo_width * scale))
    draw_height = max(1, int(logo_height * scale))
    left = (width - draw_width) // 2
    top = (height - draw_height) // 2

    for y in range(draw_height):
        source_y = min(logo_height - 1, int(y / scale))
        target_y = top + y
        if not 0 <= target_y < height:
            continue
        for x in range(draw_width):
            source_x = min(logo_width - 1, int(x / scale))
            r, g, b, a = logo_pixels[source_y][source_x]
            if a <= 0:
                continue
            target_x = left + x
            if not 0 <= target_x < width:
                continue
            alpha = (a / 255) * opacity
            base = pixels[target_y][target_x]
            pixels[target_y][target_x] = tuple(
                int(base[i] * (1 - alpha) + (r, g, b)[i] * alpha)
                for i in range(3)
            )
    return True


def wrapped_prb_lines(prb_text):
    lines = []
    for raw_line in prb_text.splitlines():
        clean = sanitize_text(raw_line)
        if not clean:
            lines.append("")
            continue
        prefix = "- " if clean.startswith("- ") else ""
        content = clean[2:] if prefix else clean
        wrapped = textwrap.wrap(content, width=36) or [""]
        for idx, line in enumerate(wrapped):
            lines.append(f"{prefix if idx == 0 else '  ' if prefix else ''}{line}")
    while lines and not lines[0]:
        lines.pop(0)
    return lines


def paginate(lines, max_lines=MAX_BODY_LINES):
    pages = []
    current = []
    for line in lines:
        if len(current) >= max_lines and line:
            pages.append(current)
            current = []
        current.append(line)
    if current:
        pages.append(current)
    return pages or [[]]


def paginate_prb_lines(lines, has_first_page_chart=False):
    if not has_first_page_chart:
        return paginate(lines)

    first_page_lines = 11
    pages = []
    current = []
    max_lines = first_page_lines
    for line in lines:
        if len(current) >= max_lines and line:
            pages.append(current)
            current = []
            max_lines = MAX_BODY_LINES
        current.append(line)
    if current:
        pages.append(current)
    return pages or [[]]


def extract_prb_id(prb_text):
    match = re.search(r"PRB-\d{4}", prb_text)
    return match.group(0) if match else "PRB-0000"


def extract_title(prb_text):
    for line in prb_text.splitlines():
        if line.startswith("Title:"):
            return sanitize_text(line.replace("Title:", "", 1)).upper()[:42]
    return "RESEARCH BRIEF"


def draw_logo_placeholder(pixels):
    cx, cy = WIDTH // 2, 92
    fill_rect(pixels, WIDTH, HEIGHT, cx - 44, cy - 28, cx + 44, cy + 28, (17, 72, 83))
    fill_rect(pixels, WIDTH, HEIGHT, cx - 36, cy - 20, cx + 36, cy + 20, CYAN)
    draw_centered_text(pixels, WIDTH, HEIGHT, cy - 10, "P", color=(2, 12, 22), scale=4)


def draw_logo(pixels, logo_path=None):
    if logo_path and Path(logo_path).exists():
        try:
            draw_png_image(pixels, logo_path, WIDTH // 2, 52, 150, 92)
            return
        except Exception:
            pass
    draw_logo_placeholder(pixels)


def draw_chart_embed(pixels, chart_path):
    if not chart_path or not Path(chart_path).exists():
        return 330

    try:
        left, top, draw_width, draw_height = draw_png_image(
            pixels,
            chart_path,
            WIDTH // 2,
            318,
            WIDTH - (MARGIN * 2),
            560,
        )
    except Exception:
        return 330

    pad = 8
    edge = (30, 126, 142)
    fill_rect(pixels, WIDTH, HEIGHT, left - pad, top - pad, left + draw_width + pad, top - pad + 4, edge)
    fill_rect(pixels, WIDTH, HEIGHT, left - pad, top + draw_height + pad - 4, left + draw_width + pad, top + draw_height + pad, edge)
    fill_rect(pixels, WIDTH, HEIGHT, left - pad, top - pad, left - pad + 4, top + draw_height + pad, edge)
    fill_rect(pixels, WIDTH, HEIGHT, left + draw_width + pad - 4, top - pad, left + draw_width + pad, top + draw_height + pad, edge)
    return top + draw_height + 44


def draw_card(page_lines, page_number, page_count, prb_id, title, output_path, logo_path=None, chart_path=None):
    pixels = make_canvas()
    draw_logo(pixels, logo_path=logo_path)
    draw_centered_text(pixels, WIDTH, HEIGHT, 145, "POINKLE RESEARCH BRIEF", color=CYAN, scale=TITLE_SCALE)
    draw_centered_text(pixels, WIDTH, HEIGHT, 202, f"{prb_id} CARD {page_number}/{page_count}", color=GOLD, scale=BODY_SCALE)
    draw_centered_text(pixels, WIDTH, HEIGHT, 244, title, color=TEXT, scale=BODY_SCALE)
    draw_horizontal_line(pixels, WIDTH, HEIGHT, 292, color=CYAN)

    y = draw_chart_embed(pixels, chart_path) if page_number == 1 else 330
    for line in page_lines:
        if y > HEIGHT - 130:
            break
        clean = sanitize_text(line)
        if not clean:
            y += PRB_LINE_HEIGHT
            continue
        color = TEXT
        scale = PRB_BODY_SCALE
        if clean.isupper() and len(clean) < 48:
            color = CYAN
            y += 10
        elif clean.startswith("-"):
            color = (204, 222, 228)
        draw_text(pixels, WIDTH, HEIGHT, PRB_TEXT_LEFT, y, clean[:PRB_TEXT_MAX_CHARS], color=color, scale=scale)
        y += PRB_LINE_HEIGHT

    draw_horizontal_line(pixels, WIDTH, HEIGHT, HEIGHT - 92, color=(30, 126, 142))
    draw_centered_text(pixels, WIDTH, HEIGHT, HEIGHT - 62, "PATIENCE COMPOUNDS", color=MUTED, scale=SMALL_SCALE)
    write_png(output_path, pixels)


def alert_accent_color(alert_data):
    color = str(alert_data.get("color") or alert_data.get("direction") or "").lower()
    if color in {"green", "bullish", "up"}:
        return GREEN
    if color in {"red", "bearish", "down"}:
        return RED
    if color in {"gold", "yellow", "neutral"}:
        return GOLD
    return CYAN


def draw_alert_stat_box(pixels, x, y, w, h, label, value, accent):
    fill_rect(pixels, WIDTH, HEIGHT, x, y, x + w, y + h, (13, 42, 54))
    fill_rect(pixels, WIDTH, HEIGHT, x, y, x + w, y + 4, accent)
    fill_rect(pixels, WIDTH, HEIGHT, x, y, x + 4, y + h, (20, 92, 108))
    fill_rect(pixels, WIDTH, HEIGHT, x + w - 4, y, x + w, y + h, (20, 92, 108))
    fill_rect(pixels, WIDTH, HEIGHT, x, y + h - 4, x + w, y + h, (20, 92, 108))
    draw_text(pixels, WIDTH, HEIGHT, x + 24, y + 24, sanitize_text(label)[:18], color=MUTED, scale=SMALL_SCALE)
    draw_text(pixels, WIDTH, HEIGHT, x + 24, y + 62, sanitize_text(value)[:20], color=TEXT, scale=BODY_SCALE)


def render_alert_card(alert_data, logo_path=None, output_dir=None):
    """
    Renders a single branded alert card as a PNG, matching the PRB
    card visual style. alert_data should contain: symbol, label
    (e.g. "Bullish Volume Spike"), emoji/indicator color, price, key
    stat lines (2-4 max, not a full data dump), and a short takeaway
    line. Returns the file path to the rendered PNG.
    """
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="poinkle_alert_cards_"))
    output_dir.mkdir(parents=True, exist_ok=True)

    symbol = sanitize_text(alert_data.get("symbol", "SYMBOL")).upper()[:18]
    label = sanitize_text(alert_data.get("label", "MARKET ALERT")).upper()[:32]
    takeaway = sanitize_text(alert_data.get("takeaway", "WATCH FOR CONFIRMATION."))[:62]
    timeframe = sanitize_text(alert_data.get("timeframe", "Daily"))[:16]
    timestamp = sanitize_text(alert_data.get("timestamp", ""))[:36]
    stats = list(alert_data.get("stats") or [])[:4]
    official_link = sanitize_text(alert_data.get("official_link", ""))[:54]
    accent = alert_accent_color(alert_data)

    pixels = make_canvas()
    draw_logo(pixels, logo_path=logo_path)
    draw_centered_text(pixels, WIDTH, HEIGHT, 145, "POINKLE ALERT", color=CYAN, scale=TITLE_SCALE)
    draw_centered_text(pixels, WIDTH, HEIGHT, 202, symbol, color=GOLD, scale=TITLE_SCALE)
    draw_centered_text(pixels, WIDTH, HEIGHT, 262, label, color=TEXT, scale=BODY_SCALE)
    draw_horizontal_line(pixels, WIDTH, HEIGHT, 316, color=accent)
    if timestamp:
        draw_centered_text(pixels, WIDTH, HEIGHT, 348, f"{timeframe}  {timestamp}", color=MUTED, scale=SMALL_SCALE)
    else:
        draw_centered_text(pixels, WIDTH, HEIGHT, 348, timeframe, color=MUTED, scale=SMALL_SCALE)
    scope = sanitize_text(alert_data.get("signal_scope", ALERT_SIGNAL_SCOPE))[:54]
    draw_centered_text(pixels, WIDTH, HEIGHT, 386, scope, color=MUTED, scale=SMALL_SCALE)

    box_w = (WIDTH - (MARGIN * 2) - 28) // 2
    box_h = 138
    start_y = 448
    for index, stat in enumerate(stats):
        if isinstance(stat, dict):
            stat_label = stat.get("label", "")
            stat_value = stat.get("value", "")
        else:
            stat_label, stat_value = stat
        col = index % 2
        row = index // 2
        x = MARGIN + col * (box_w + 28)
        y = start_y + row * (box_h + 34)
        draw_alert_stat_box(pixels, x, y, box_w, box_h, stat_label, stat_value, accent)

    takeaway_top = 790
    draw_horizontal_line(pixels, WIDTH, HEIGHT, takeaway_top - 34, color=(30, 126, 142))
    draw_centered_text(pixels, WIDTH, HEIGHT, takeaway_top, "WHAT TO WATCH", color=CYAN, scale=BODY_SCALE)
    wrapped_takeaway = textwrap.wrap(takeaway, width=44)[:3]
    y = takeaway_top + 58
    for line in wrapped_takeaway:
        draw_centered_text(pixels, WIDTH, HEIGHT, y, line, color=TEXT, scale=BODY_SCALE)
        y += 42

    if official_link:
        draw_centered_text(pixels, WIDTH, HEIGHT, HEIGHT - 134, f"LEARN MORE: {official_link}", color=MUTED, scale=SMALL_SCALE)
    draw_horizontal_line(pixels, WIDTH, HEIGHT, HEIGHT - 92, color=(30, 126, 142))
    draw_centered_text(pixels, WIDTH, HEIGHT, HEIGHT - 62, "PATIENCE COMPOUNDS", color=MUTED, scale=SMALL_SCALE)

    filename = f"alert_{symbol.lower().replace('/', '_')}_{label.lower().replace(' ', '_')}.png"
    output_path = output_dir / filename
    write_png(output_path, pixels)
    return str(output_path)


def draw_wrapped_text_block(pixels, lines, x, y, width=52, color=TEXT, scale=BODY_SCALE, line_gap=9):
    for raw_line in lines:
        clean = sanitize_text(raw_line)
        wrapped = textwrap.wrap(clean, width=width) if clean else [""]
        for line in wrapped:
            if line:
                draw_text(pixels, WIDTH, HEIGHT, x, y, line[:62], color=color, scale=scale)
            y += LINE_HEIGHT + line_gap
    return y


def render_welcome_card(symbols, logo_path=None, output_dir=None):
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="poinkle_welcome_cards_"))
    output_dir.mkdir(parents=True, exist_ok=True)

    symbols = [sanitize_text(symbol).replace("/USD", "").upper() for symbol in symbols]
    primary = symbols[0] if symbols else "BTC"
    secondary = symbols[1] if len(symbols) > 1 else primary
    research = symbols[2] if len(symbols) > 2 else primary

    pixels = make_canvas()
    draw_logo(pixels, logo_path=logo_path)
    draw_centered_text(pixels, WIDTH, HEIGHT, 145, "POINKLE START", color=CYAN, scale=TITLE_SCALE)
    draw_centered_text(pixels, WIDTH, HEIGHT, 204, "WELCOME TO POINKLE ALPHA", color=GOLD, scale=BODY_SCALE)
    draw_horizontal_line(pixels, WIDTH, HEIGHT, 254, color=CYAN)

    y = 292
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "MISSION", color=CYAN, scale=BODY_SCALE)
    y += 48
    mission_lines = [
        "Poinkle helps teach you what to look at next.",
        "Use it to read trend, levels, liquidity, confirmation, and decision quality.",
    ]
    y = draw_wrapped_text_block(pixels, mission_lines, MARGIN + 24, y, width=50, color=TEXT, scale=SMALL_SCALE, line_gap=9)

    y += 22
    draw_horizontal_line(pixels, WIDTH, HEIGHT, y, color=(30, 126, 142))
    y += 34
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "START WITH", color=CYAN, scale=BODY_SCALE)
    y += 48
    command_lines = [
        f"/snapshot {primary} - full visual chart + breakdown",
        f"/snap {secondary} - quick version of the same",
        f"/research {research} - deeper multi-card research brief",
        f"/levels {primary} - legacy text version",
        "/help - full command list anytime",
    ]
    y = draw_wrapped_text_block(pixels, command_lines, MARGIN + 24, y, width=51, color=TEXT, scale=SMALL_SCALE, line_gap=7)

    y += 22
    draw_horizontal_line(pixels, WIDTH, HEIGHT, y, color=(30, 126, 142))
    y += 34
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "LAYER 1 TEACHES", color=CYAN, scale=BODY_SCALE)
    y += 48
    layer_lines = [
        "Trend",
        "Key Levels",
        "Liquidity",
        "Confirmation",
        "Decision",
    ]
    y = draw_wrapped_text_block(pixels, layer_lines, MARGIN + 24, y, width=50, color=TEXT, scale=SMALL_SCALE, line_gap=7)

    y += 20
    draw_horizontal_line(pixels, WIDTH, HEIGHT, y, color=(30, 126, 142))
    y += 34
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "SUPPORTED COINS", color=CYAN, scale=BODY_SCALE)
    y += 48
    coin_lines = textwrap.wrap(" ".join(symbols), width=48)[:4]
    y = draw_wrapped_text_block(pixels, coin_lines, MARGIN + 24, y, width=48, color=GOLD, scale=SMALL_SCALE, line_gap=10)
    if len(textwrap.wrap(" ".join(symbols), width=48)) > 4:
        draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "MORE IN /HELP", color=MUTED, scale=SMALL_SCALE)
        y += 34

    y += 20
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "EDUCATIONAL MARKET STRUCTURE ONLY.", color=MUTED, scale=SMALL_SCALE)
    y += 34
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "NOT FINANCIAL ADVICE.", color=MUTED, scale=SMALL_SCALE)

    draw_horizontal_line(pixels, WIDTH, HEIGHT, HEIGHT - 92, color=(30, 126, 142))
    draw_centered_text(pixels, WIDTH, HEIGHT, HEIGHT - 62, "PATIENCE COMPOUNDS", color=MUTED, scale=SMALL_SCALE)

    output_path = output_dir / "poinkle_welcome.png"
    write_png(output_path, pixels)
    return str(output_path)


def render_reference_card(symbols, logo_path=None, output_dir=None):
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="poinkle_reference_cards_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    symbols = [sanitize_text(symbol).replace("/USD", "").upper() for symbol in symbols]

    pixels = make_canvas()
    draw_logo(pixels, logo_path=logo_path)
    draw_centered_text(pixels, WIDTH, HEIGHT, 145, "POINKLE - QUICK REFERENCE", color=CYAN, scale=TITLE_SCALE)
    draw_horizontal_line(pixels, WIDTH, HEIGHT, 214, color=CYAN)

    y = 252
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "COMMANDS", color=CYAN, scale=BODY_SCALE)
    y += 48
    command_lines = [
        "/snapshot BTC - full visual chart + breakdown",
        "/snap ETH - quick version of the same",
        "/research SOL - deeper multi-card research brief",
        "/levels BTC - legacy text version",
        "/alerts XRP support - get DM'd when XRP nears a key zone",
        "/myalerts - see your active alerts",
        "/help - full command list anytime",
    ]
    y = draw_wrapped_text_block(pixels, command_lines, MARGIN + 24, y, width=51, color=TEXT, scale=SMALL_SCALE, line_gap=7)

    y += 22
    draw_horizontal_line(pixels, WIDTH, HEIGHT, y, color=(30, 126, 142))
    y += 34
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "SUPPORTED COINS", color=CYAN, scale=BODY_SCALE)
    y += 48
    coin_lines = textwrap.wrap(" ".join(symbols), width=48)
    y = draw_wrapped_text_block(pixels, coin_lines, MARGIN + 24, y, width=48, color=GOLD, scale=SMALL_SCALE, line_gap=10)

    y += 24
    draw_horizontal_line(pixels, WIDTH, HEIGHT, y, color=(30, 126, 142))
    y += 34
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "SCOPE NOTE", color=CYAN, scale=BODY_SCALE)
    y += 48
    scope_lines = [
        "Every alert is a short-term signal on one specific timeframe - not a call on the overall trend.",
        "Two alerts can look like they disagree and both be right.",
    ]
    y = draw_wrapped_text_block(pixels, scope_lines, MARGIN + 24, y, width=50, color=TEXT, scale=SMALL_SCALE, line_gap=9)

    y += 22
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "EDUCATIONAL MARKET STRUCTURE ONLY.", color=MUTED, scale=SMALL_SCALE)
    y += 34
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "NOT FINANCIAL ADVICE.", color=MUTED, scale=SMALL_SCALE)
    y += 34
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "POINKLE DID THE RESEARCH.", color=MUTED, scale=SMALL_SCALE)
    y += 34
    draw_text(pixels, WIDTH, HEIGHT, MARGIN + 24, y, "THE DECISION IS YOURS.", color=MUTED, scale=SMALL_SCALE)

    draw_horizontal_line(pixels, WIDTH, HEIGHT, HEIGHT - 92, color=(30, 126, 142))
    draw_centered_text(pixels, WIDTH, HEIGHT, HEIGHT - 62, "PATIENCE COMPOUNDS", color=MUTED, scale=SMALL_SCALE)

    output_path = output_dir / "poinkle_quick_reference.png"
    write_png(output_path, pixels)
    return str(output_path)


def render_mike_list_card(rows, logo_path=None, output_dir=None):
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="poinkle_mike_cards_"))
    output_dir.mkdir(parents=True, exist_ok=True)

    pixels = make_canvas()
    draw_ghost_watermark(pixels, watermark_path=MIKE_WATERMARK_PATH, opacity=MIKE_WATERMARK_OPACITY)
    draw_logo(pixels, logo_path=logo_path)
    draw_centered_text(pixels, WIDTH, HEIGHT, 145, "THE INNER CIRCLE", color=CYAN, scale=TITLE_SCALE)
    draw_centered_text(pixels, WIDTH, HEIGHT, 204, "MIKE KNOWS", color=GOLD, scale=BODY_SCALE)
    draw_centered_text(pixels, WIDTH, HEIGHT, 252, "MIKE'S CURATED LIST", color=TEXT, scale=SMALL_SCALE)
    draw_horizontal_line(pixels, WIDTH, HEIGHT, 302, color=CYAN)

    y = 348
    coin_x = 76 + MIKE_TABLE_X_OFFSET
    price_x = 250 + MIKE_TABLE_X_OFFSET
    trend_x = 560 + MIKE_TABLE_X_OFFSET
    rsi_x = 800 + MIKE_TABLE_X_OFFSET
    draw_text(pixels, WIDTH, HEIGHT, coin_x, y, "COIN", color=CYAN, scale=MIKE_TABLE_SCALE)
    draw_text(pixels, WIDTH, HEIGHT, price_x, y, "PRICE", color=CYAN, scale=MIKE_TABLE_SCALE)
    draw_text(pixels, WIDTH, HEIGHT, trend_x, y, "TREND", color=CYAN, scale=MIKE_TABLE_SCALE)
    draw_text(pixels, WIDTH, HEIGHT, rsi_x, y, "RSI", color=CYAN, scale=MIKE_TABLE_SCALE)
    y += 46
    draw_horizontal_line(pixels, WIDTH, HEIGHT, y, color=(30, 126, 142))
    y += 32

    for row in rows[:10]:
        available = row.get("available", True)
        row_color = TEXT if available else MUTED
        trend = sanitize_text(row.get("trend", "n/a")).upper()
        if trend == "BULLISH":
            trend_color = GREEN
        elif trend == "BEARISH":
            trend_color = RED
        else:
            trend_color = MUTED if not available else GOLD

        symbol = sanitize_text(row.get("symbol", "SYMBOL")).upper()[:8]
        price = sanitize_text(row.get("price", "n/a"))[:18] if available else "unavailable"
        rsi_value = sanitize_text(row.get("rsi", "n/a"))[:8]

        draw_text(pixels, WIDTH, HEIGHT, coin_x, y, symbol, color=GOLD if available else MUTED, scale=MIKE_TABLE_SCALE)
        draw_text(pixels, WIDTH, HEIGHT, price_x, y, price, color=row_color, scale=MIKE_TABLE_SCALE)
        draw_text(pixels, WIDTH, HEIGHT, trend_x, y, trend[:10], color=trend_color, scale=MIKE_TABLE_SCALE)
        draw_text(pixels, WIDTH, HEIGHT, rsi_x, y, rsi_value, color=row_color, scale=MIKE_TABLE_SCALE)
        y += MIKE_TABLE_ROW_GAP

    draw_horizontal_line(pixels, WIDTH, HEIGHT, HEIGHT - 164, color=(30, 126, 142))
    draw_centered_text(pixels, WIDTH, HEIGHT, HEIGHT - 128, "PRICE  TREND  RSI", color=MUTED, scale=SMALL_SCALE)
    draw_centered_text(pixels, WIDTH, HEIGHT, HEIGHT - 96, "EDUCATIONAL MARKET STRUCTURE ONLY.", color=MUTED, scale=SMALL_SCALE)
    draw_centered_text(pixels, WIDTH, HEIGHT, HEIGHT - 62, "PATIENCE COMPOUNDS", color=MUTED, scale=SMALL_SCALE)

    output_path = output_dir / "inner_circle_mike_list.png"
    write_png(output_path, pixels)
    return str(output_path)


def render_prb_cards(prb_text, logo_path=None, output_dir=None, chart_path=None):
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="poinkle_prb_cards_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    prb_id = extract_prb_id(prb_text)
    title = extract_title(prb_text)
    lines = wrapped_prb_lines(prb_text)
    pages = paginate_prb_lines(lines, has_first_page_chart=bool(chart_path))
    paths = []
    for idx, page_lines in enumerate(pages, start=1):
        path = output_dir / f"{prb_id.lower()}_card_{idx}_of_{len(pages)}.png"
        draw_card(
            page_lines,
            idx,
            len(pages),
            prb_id,
            title,
            path,
            logo_path=logo_path,
            chart_path=chart_path if idx == 1 else None,
        )
        paths.append(str(path))
    return paths
