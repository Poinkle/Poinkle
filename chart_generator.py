import json
import os
import tempfile
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle


# === Poinkle Snapshot Generator ===
# Level 1 architecture:
# Clean teaching snapshot first, market data pipeline underneath.
# Scanner logic stays outside this file.

BACKGROUND = "#06141d"
CHART_BG = "#07141d"
PANEL = "#112332"
PANEL_ALT = "#0f172a"
GRID = "#263243"
TEXT = "#e5edf7"
MUTED = "#91a1b5"
GREEN = "#39f06f"
RED = "#ff5555"
BLUE = "#38bdf8"
YELLOW = "#facc15"
ORANGE = "#fb923c"
PURPLE = "#a855f7"
WHITE = "#f8fafc"

SNAPSHOT_WIDTH = 1600
SNAPSHOT_HEIGHT = 900
TRADINGVIEW_ENABLED = os.getenv("POINKLE_TRADINGVIEW_CAPTURE", "1") != "0"


# -----------------------------
# Basic helpers
# -----------------------------

def format_price(price):
    if price is None:
        return "N/A"
    if abs(price) >= 1000:
        return f"{price:,.0f}"
    if abs(price) >= 10:
        return f"{price:,.2f}"
    if abs(price) >= 1:
        return f"{price:,.3f}"
    return f"{price:.5f}"


def latest_value(values):
    if not values:
        return None
    return values[-1]


def nearest_levels(levels, current_price, side, limit=3):
    levels = list(levels or [])
    if not levels:
        return []
    if side == "support":
        candidates = [level for level in levels if level <= current_price]
        candidates = sorted(candidates, key=lambda level: current_price - level)
    else:
        candidates = [level for level in levels if level >= current_price]
        candidates = sorted(candidates, key=lambda level: level - current_price)

    if len(candidates) < limit:
        extras = [level for level in levels if level not in candidates]
        extras = sorted(extras, key=lambda level: abs(level - current_price))
        candidates.extend(extras)

    return candidates[:limit]


TARGET_CANDLE_HEIGHT_RATIO = 0.72


def candle_price_bounds(candles, current_price=None):
    prices = [c["high"] for c in candles]
    prices += [c["low"] for c in candles]
    if not prices and current_price is not None:
        prices.append(current_price)

    low = min(prices)
    high = max(prices)
    span = max(high - low, abs(current_price or high or 1) * 0.025, 0.000001)
    return low, high, span


def chart_near_levels(levels, current_price, candles, limit=3):
    candle_low, candle_high, candle_span = candle_price_bounds(candles, current_price)
    target_span = candle_span / TARGET_CANDLE_HEIGHT_RATIO
    nearby_pad = (target_span - candle_span) / 2
    near_low = max(candle_low - nearby_pad, 0)
    near_high = candle_high + nearby_pad

    near = [
        level
        for level in list(levels or [])
        if near_low <= level <= near_high
    ]
    near = sorted(near, key=lambda level: abs(level - current_price))
    return near[:limit]


def visible_teaching_level(levels, current_price, candles, side):
    near = chart_near_levels(levels, current_price, candles, 1)
    if near:
        return near

    if side == "support":
        return [min(candle["low"] for candle in candles)]
    return [max(candle["high"] for candle in candles)]


def select_liquidity_marker(candles, current_price, y_min, y_max):
    if len(candles) < 12:
        return None

    _, _, candle_span = candle_price_bounds(candles, current_price)
    sweep_candidates = []
    lookback = 8
    start = max(lookback, len(candles) - 36)

    for i in range(start, len(candles)):
        candle = candles[i]
        previous = candles[i - lookback : i]
        previous_high = max(item["high"] for item in previous)
        previous_low = min(item["low"] for item in previous)
        body_high = max(candle["open"], candle["close"])
        body_low = min(candle["open"], candle["close"])
        candle_range = max(candle["high"] - candle["low"], 0.000001)
        upper_wick = candle["high"] - body_high
        lower_wick = body_low - candle["low"]
        recency = i / max(len(candles) - 1, 1)

        if candle["high"] > previous_high and candle["close"] < previous_high:
            sweep_size = candle["high"] - previous_high
            wick_ratio = upper_wick / candle_range
            if sweep_size >= candle_span * 0.012 and wick_ratio >= 0.32 and y_min <= candle["high"] <= y_max:
                sweep_candidates.append((2.0 + wick_ratio * 3 + recency, i, candle["high"], "sell_side"))

        if candle["low"] < previous_low and candle["close"] > previous_low:
            sweep_size = previous_low - candle["low"]
            wick_ratio = lower_wick / candle_range
            if sweep_size >= candle_span * 0.012 and wick_ratio >= 0.32 and y_min <= candle["low"] <= y_max:
                sweep_candidates.append((2.0 + wick_ratio * 3 + recency, i, candle["low"], "buy_side"))

    if not sweep_candidates:
        return None

    _, index, price, side = max(sweep_candidates, key=lambda item: item[0])
    return {"index": index, "price": price, "side": side}


def add_liquidity_line_candidate(candidates, level, score, index, source):
    if level is None:
        return
    candidates.append(
        {
            "level": level,
            "score": score,
            "index": index,
            "source": source,
        }
    )


def select_liquidity_lines(candles, current_price, y_min, y_max, limit=4):
    if len(candles) < 18:
        return []

    _, _, candle_span = candle_price_bounds(candles, current_price)
    tolerance = max(candle_span * 0.028, abs(current_price) * 0.0012, 0.000001)
    min_spacing = max(candle_span * 0.095, abs(current_price) * 0.0025, 0.000001)
    max_distance = max(candle_span * 0.62, abs(current_price) * 0.035, 0.000001)
    candidates = []
    lookback = 2
    last_index = len(candles) - 1

    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback : i + lookback + 1]
        recency = i / max(last_index, 1)
        if candles[i]["high"] >= max(candle["high"] for candle in window):
            add_liquidity_line_candidate(candidates, candles[i]["high"], 2.4 + recency, i, "swing_high")
        if candles[i]["low"] <= min(candle["low"] for candle in window):
            add_liquidity_line_candidate(candidates, candles[i]["low"], 2.4 + recency, i, "swing_low")

    for side, field in (("equal_high", "high"), ("equal_low", "low")):
        points = sorted((candle[field], i) for i, candle in enumerate(candles))
        clusters = []
        for level, index in points:
            if not clusters or abs(level - clusters[-1]["center"]) > tolerance:
                clusters.append({"levels": [level], "indexes": [index], "center": level})
                continue
            cluster = clusters[-1]
            cluster["levels"].append(level)
            cluster["indexes"].append(index)
            cluster["center"] = sum(cluster["levels"]) / len(cluster["levels"])

        for cluster in clusters:
            touches = len(cluster["levels"])
            if touches < 2:
                continue
            recency = max(cluster["indexes"]) / max(last_index, 1)
            score = 3.2 + min(touches, 4) * 0.75 + recency
            add_liquidity_line_candidate(candidates, cluster["center"], score, max(cluster["indexes"]), side)

    sweep = select_liquidity_marker(candles, current_price, y_min, y_max)
    if sweep:
        add_liquidity_line_candidate(candidates, sweep["price"], 4.6, sweep["index"], "sweep")

    visible = []
    for candidate in candidates:
        level = candidate["level"]
        distance = abs(level - current_price)
        if not (y_min <= level <= y_max) or distance > max_distance:
            continue
        candidate = candidate.copy()
        candidate["score"] += max(0, 2.2 - (distance / max_distance) * 2.2)
        visible.append(candidate)
    visible.sort(key=lambda candidate: candidate["score"], reverse=True)

    selected = []
    for candidate in visible:
        level = candidate["level"]
        if any(abs(level - existing["level"]) < min_spacing for existing in selected):
            continue
        start = 1
        end = len(candles) - 2
        selected.append({**candidate, "start": start, "end": end})
        if len(selected) >= limit:
            break

    if len(selected) < 2:
        return []

    if len(selected) > 2 and selected[2]["score"] < 4.4:
        selected = selected[:2]

    return sorted(selected, key=lambda item: item["level"])


def axis_bounds(current_price, candles, supports, resistances):
    candle_low, candle_high, candle_span = candle_price_bounds(candles, current_price)
    target_span = candle_span / TARGET_CANDLE_HEIGHT_RATIO
    pad = (target_span - candle_span) / 2

    low = candle_low - pad
    high = candle_high + pad

    for level in list(supports or []) + list(resistances or []):
        low = min(low, level)
        high = max(high, level)

    return max(low, 0), high


def calc_rsi(closes, period=14):
    if len(closes) <= period:
        return None

    gains = []
    losses = []
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        gain = max(change, 0)
        loss = abs(min(change, 0))
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_ema_series(values, period):
    if not values:
        return []
    multiplier = 2 / (period + 1)
    series = [values[0]]
    for value in values[1:]:
        series.append((value - series[-1]) * multiplier + series[-1])
    return series


def usable_ema_series(values, closes, period):
    values = list(values or [])
    sample = values[-min(len(values), 12):]
    if len(sample) >= 2 and len({round(value, 8) for value in sample}) > 1:
        return values
    return calc_ema_series(closes, period)


def draw_ema_label(ax, x_values, values, label, color, x_offset=0.8):
    if not values:
        return
    ax.text(
        x_values[-1] + x_offset,
        values[-1],
        label,
        color=color,
        fontsize=6.2,
        fontweight="bold",
        ha="left",
        va="center",
        alpha=0.88,
        zorder=11,
        path_effects=[pe.withStroke(linewidth=2.0, foreground="#03101a", alpha=0.72)],
    )


def trend_lesson(closes):
    if len(closes) < 12 or closes[0] == 0:
        return "Changing", "Let structure form", YELLOW

    change = (closes[-1] - closes[0]) / closes[0]
    highs = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])
    lows = sum(1 for i in range(1, len(closes)) if closes[i] < closes[i - 1])
    range_pct = (max(closes) - min(closes)) / closes[-1] if closes[-1] else 0

    if abs(change) < 0.018 and range_pct < 0.065:
        return "Ranging", "Trade the map", YELLOW
    if change > 0 and highs >= lows:
        return "Uptrend", "Higher highs + higher lows", GREEN
    if change < 0 and lows >= highs:
        return "Downtrend", "Lower highs + lower lows", RED
    return "Changing", "Wait for confirmation", BLUE


def level_focus_text(current_price, supports, resistances):
    levels = [(abs(level - current_price), "support", level) for level in supports]
    levels += [(abs(level - current_price), "resistance", level) for level in resistances]
    if not levels:
        return "No nearby level", MUTED
    _, side, level = min(levels, key=lambda item: item[0])
    if side == "support":
        return f"Support near {format_price(level)}", GREEN
    return f"Resistance near {format_price(level)}", RED


def patience_score(current_price, supports, resistances):
    levels = list(supports or []) + list(resistances or [])
    if not levels or not current_price:
        return "N/A"
    nearest = min(abs(level - current_price) / current_price for level in levels)
    score = max(0, min(100, int(nearest * 900)))
    return f"{score}/100"


def time_label(candle):
    value = candle.get("time") or candle.get("timestamp") or candle.get("datetime") or ""
    if isinstance(value, datetime):
        return value.strftime("%b %d")
    text = str(value)
    if "T" in text:
        return text.split("T")[0][-5:]
    if " " in text:
        return text.split(" ")[0][-5:]
    return text[-5:] if len(text) > 5 else text


def tradingview_symbol(symbol):
    base, _, quote = symbol.replace("-", "/").partition("/")
    base = base.upper()
    quote = (quote or "USD").upper()
    if quote == "USDT":
        return f"BINANCE:{base}USDT"
    return f"COINBASE:{base}USD"


# -----------------------------
# Optional TradingView capture
# -----------------------------

def tradingview_widget_html(symbol):
    widget_options = {
        "autosize": True,
        "symbol": tradingview_symbol(symbol),
        "interval": "15",
        "timezone": "Etc/UTC",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "backgroundColor": CHART_BG,
        "gridColor": GRID,
        "hide_top_toolbar": False,
        "hide_side_toolbar": False,
        "allow_symbol_change": False,
        "save_image": False,
        "calendar": False,
        "support_host": "https://www.tradingview.com",
        "studies": ["STD;EMA", "STD;RSI"],
    }
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    html, body, #chart {{ width: 100%; height: 100%; margin: 0; overflow: hidden; background: {CHART_BG}; }}
  </style>
</head>
<body>
  <div id="chart" class="tradingview-widget-container">
    <div class="tradingview-widget-container__widget"></div>
    <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
    {json.dumps(widget_options)}
    </script>
  </div>
</body>
</html>"""


def capture_tradingview_chart(symbol):
    if not TRADINGVIEW_ENABLED:
        return None
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    html_file = tempfile.NamedTemporaryFile(
        suffix=".html",
        prefix=f"{symbol.replace('/', '_')}_tradingview_",
        mode="w",
        encoding="utf-8",
        delete=False,
    )
    try:
        html_file.write(tradingview_widget_html(symbol))
        html_file.close()
        image_file = tempfile.NamedTemporaryFile(
            suffix=".png",
            prefix=f"{symbol.replace('/', '_')}_tradingview_",
            delete=False,
        )
        image_path = image_file.name
        image_file.close()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1240, "height": 610}, device_scale_factor=1)
            page.goto(f"file://{html_file.name}", wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(6500)
            page.screenshot(path=image_path, full_page=False)
            browser.close()
        return image_path
    except Exception:
        return None
    finally:
        try:
            os.unlink(html_file.name)
        except Exception:
            pass


# -----------------------------
# Drawing primitives
# -----------------------------

def box(ax, x, y, w, h, edge=GRID, face=PANEL, alpha=0.94, lw=1.0, z=2):
    ax.add_patch(
        Rectangle((x, y), w, h, transform=ax.transAxes, facecolor=face, edgecolor=edge, linewidth=lw, alpha=alpha, zorder=z)
    )


def rounded_box(ax, x, y, w, h, edge=GRID, face=PANEL, alpha=0.82, lw=1.0, radius=0.035, z=2):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            transform=ax.transAxes,
            boxstyle=f"round,pad=0.012,rounding_size={radius}",
            facecolor=face,
            edgecolor=edge,
            linewidth=lw,
            alpha=alpha,
            zorder=z,
        )
    )


def text(ax, x, y, value, size=9, color=TEXT, weight="normal", ha="left", va="center", z=5):
    ax.text(x, y, value, transform=ax.transAxes, fontsize=size, color=color, fontweight=weight, ha=ha, va=va, zorder=z)


def style_axis(ax, right_axis=True):
    ax.set_facecolor(CHART_BG)
    ax.grid(True, color=GRID, alpha=0.26, linewidth=0.65)
    ax.tick_params(colors=MUTED, labelsize=8)
    if right_axis:
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
    for spine in ax.spines.values():
        spine.set_color(GRID)


def draw_candles(ax, candles):
    for i, candle in enumerate(candles):
        o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]
        color = GREEN if c >= o else RED
        ax.vlines(i, l, h, color=color, linewidth=2.3, alpha=1.0, zorder=4)
        body_low = min(o, c)
        body_h = abs(c - o) or max(abs(c) * 0.00025, 0.000001)
        ax.add_patch(Rectangle((i - 0.495, body_low), 0.99, body_h, facecolor=color, edgecolor=color, linewidth=0.9, alpha=1.0, zorder=5))


def draw_zone(ax, level, x0, x1, current_price, color, label):
    band = max(abs(current_price) * 0.010, 0.000001)
    ax.add_patch(
        Rectangle(
            (x0, level - band / 2),
            x1 - x0,
            band,
            facecolor=color,
            edgecolor=color,
            alpha=0.12,
            linewidth=0,
            zorder=1,
        )
    )


def draw_liquidity_band(ax, level, x0, x1, current_price):
    band = max(abs(current_price) * 0.006, 0.000001)
    ax.add_patch(
        Rectangle(
            (x0, level - band / 2),
            x1 - x0,
            band,
            facecolor=YELLOW,
            edgecolor=YELLOW,
            alpha=0.020,
            linewidth=0,
            zorder=1,
        )
    )


def draw_teaching_card(ax, n, title, body, accent):
    ax.axis("off")
    rounded_box(ax, 0.015, 0.055, 0.970, 0.880, edge=accent, face=PANEL, alpha=0.72, lw=0.85, radius=0.040)
    badge = Circle((0.105, 0.690), 0.078, transform=ax.transAxes, facecolor=accent, edgecolor="none", alpha=0.95, zorder=4)
    ax.add_patch(badge)
    text(ax, 0.105, 0.690, str(n), size=13.8, color=BACKGROUND, weight="bold", ha="center")
    text(ax, 0.210, 0.720, title, size=10.0, color=accent, weight="bold")
    text(ax, 0.210, 0.385, body, size=7.6, color=TEXT, va="center")


def draw_teaching_arrow(ax, start, end, rad=0.0):
    arrow = FancyArrowPatch(
        start,
        end,
        transform=ax.transAxes,
        arrowstyle="-|>",
        mutation_scale=14,
        connectionstyle=f"arc3,rad={rad}",
        color=BLUE,
        linewidth=1.05,
        linestyle=(0, (1.8, 2.8)),
        alpha=0.76,
        zorder=4,
    )
    ax.add_patch(arrow)


def draw_footer_card(ax, title, lines, accent):
    ax.axis("off")
    box(ax, 0.020, 0.10, 0.960, 0.80, edge=GRID, face=PANEL, alpha=0.94, lw=1.0)
    text(ax, 0.50, 0.735, title, size=9.1, color=accent, weight="bold", ha="center")
    y = 0.500
    for line in lines[:4]:
        text(ax, 0.095, y, line, size=6.75, color=TEXT)
        y -= 0.135


def draw_level_one_footer(ax, trend_title, trend_hint, current_price, supports, resistances):
    ax.axis("off")
    box(ax, 0.00, 0.08, 1.00, 0.84, edge=GRID, face=PANEL, alpha=0.76, lw=1.0)
    text(ax, 0.50, 0.735, "WHAT TO WATCH NEXT", size=13, color=BLUE, weight="bold", ha="center")

    watch_lines = [
        (
            f"Hold above {format_price(supports[0])}",
            "Trend stays healthy.",
        ) if supports else ("Let support form", "Wait for a cleaner map."),
        (
            f"Reclaim {format_price(current_price)}",
            "Buyers step back in.",
        ),
        (
            f"Break {format_price(resistances[0])}",
            "Next leg can start.",
        ) if resistances else ("Wait for resistance", "Let price show the ceiling."),
    ]
    x_positions = [0.155, 0.420, 0.685]
    colors = [GREEN, BLUE, RED]
    for index, (x_pos, item, color) in enumerate(zip(x_positions, watch_lines, colors), start=1):
        line, lesson = item
        badge = Circle((x_pos, 0.445), 0.027, transform=ax.transAxes, facecolor=color, edgecolor="none", alpha=0.90, zorder=4)
        ax.add_patch(badge)
        text(ax, x_pos, 0.445, str(index), size=8.2, color=BACKGROUND, weight="bold", ha="center")
        text(ax, x_pos + 0.040, 0.470, line, size=9.4, color=TEXT, weight="bold")
        text(ax, x_pos + 0.040, 0.270, lesson, size=7.9, color=MUTED)


# Future learning layers:
# Level 2 = Levels detail
# Level 3 = Teacher explanation
# Level 4 = Creator/community context
# Level 5 = Website learning hub


def draw_sidebar(ax, symbol, current_price, trend_title, trend_hint, trend_color, rsi_value, patience, supports, resistances, ema21, ema55):
    ax.axis("off")
    ax.set_facecolor(PANEL)
    box(ax, 0.030, 0.020, 0.940, 0.960, edge=GRID, face=PANEL, alpha=0.96)

    label_x = 0.120
    value_x = 0.865

    text(ax, 0.50, 0.955, "MARKET OVERVIEW", size=10.4, color=YELLOW, weight="bold", ha="center")
    rows = [
        ("CURRENT PRICE", format_price(current_price), BLUE),
        ("BIAS", trend_title.upper(), trend_color),
        ("TREND", "STRONG" if trend_title not in ("Changing", "Ranging") else "DEVELOPING", trend_color),
        ("PATIENCE", patience, BLUE),
    ]
    y = 0.895
    for label, value, color in rows:
        text(ax, label_x, y, label, size=7.4, color=MUTED, weight="bold")
        text(ax, value_x, y, value, size=8.1, color=color, weight="bold", ha="right")
        y -= 0.052

    y -= 0.026
    text(ax, 0.50, y, "KEY LEVELS", size=10.4, color=YELLOW, weight="bold", ha="center")
    y -= 0.040
    text(ax, label_x, y, "RESISTANCE / PROFIT REVIEW", size=8.0, color=RED, weight="bold")
    y -= 0.032
    for i, level in enumerate(resistances[:3], start=1):
        text(ax, label_x + 0.020, y, f"R{i}", size=7.4, color=MUTED, weight="bold")
        text(ax, value_x, y, format_price(level), size=7.6, color=TEXT, ha="right")
        y -= 0.028

    y -= 0.021
    text(ax, label_x, y, "LIQUIDITY ZONES", size=8.0, color=ORANGE, weight="bold")
    y -= 0.032
    if resistances:
        text(ax, label_x + 0.020, y, f"Sell side  {format_price(resistances[0])}", size=7.4, color=TEXT)
        y -= 0.026
    if supports:
        text(ax, label_x + 0.020, y, f"Buy side   {format_price(supports[0])}", size=7.4, color=TEXT)
        y -= 0.026

    y -= 0.021
    text(ax, label_x, y, "SUPPORT / ACCUMULATION", size=8.0, color=GREEN, weight="bold")
    y -= 0.032
    for i, level in enumerate(supports[:5], start=1):
        text(ax, label_x + 0.020, y, f"S{i}", size=7.4, color=MUTED, weight="bold")
        text(ax, value_x, y, format_price(level), size=7.6, color=TEXT, ha="right")
        y -= 0.026

    y -= 0.021
    text(ax, 0.50, y, "TREND SUMMARY", size=9.8, color=YELLOW, weight="bold", ha="center")
    y -= 0.030
    summary = [
        ("Direction", trend_title),
        ("Structure", trend_hint),
        ("EMA21", "N/A" if ema21 is None else format_price(ema21)),
        ("EMA55", "N/A" if ema55 is None else format_price(ema55)),
        ("RSI", "N/A" if rsi_value is None else f"{rsi_value:.1f}"),
    ]
    for label, value in summary:
        text(ax, label_x, y, label, size=6.75, color=MUTED, weight="bold")
        text(ax, value_x, y, value, size=6.75, color=TEXT, ha="right")
        y -= 0.016

    text(ax, 0.50, 0.128, "STRATEGY REMINDER", size=8.6, color=ORANGE, weight="bold", ha="center")
    for yy, line in zip([0.102, 0.083, 0.064, 0.045], ["Follow the trend.", "Trade key levels.", "Wait for confirmation.", "Protect downside."]):
        text(ax, label_x, yy, f"• {line}", size=6.35, color=TEXT)

    box(ax, 0.055, 0.006, 0.890, 0.034, edge=GRID, face=BACKGROUND, alpha=0.96)
    text(ax, label_x, 0.024, f"/levels {symbol.split('/')[0]}", size=8.0, color=BLUE, weight="bold")
    text(ax, 0.905, 0.024, "Poinkle", size=7.0, color=MUTED, ha="right")


# -----------------------------
# Main Draft 3 generator
# -----------------------------

def generate_matplotlib_levels_chart(symbol, candles, current_price, supports, resistances, ema21=None, ema55=None):
    if not candles:
        raise ValueError("No candles provided")

    recent = candles[-72:]
    closes = [c["close"] for c in recent]
    x = list(range(len(recent)))

    panel_supports = nearest_levels(supports, current_price, "support", 3)
    panel_resistances = nearest_levels(resistances, current_price, "resistance", 3)
    visible_supports = visible_teaching_level(panel_supports, current_price, recent, "support")
    visible_resistances = visible_teaching_level(panel_resistances, current_price, recent, "resistance")
    y_min, y_max = axis_bounds(current_price, recent, visible_supports, visible_resistances)

    trend_title, trend_hint, trend_color = trend_lesson(closes)
    level_text, level_color = level_focus_text(current_price, visible_supports, visible_resistances)
    patience = patience_score(current_price, visible_supports, visible_resistances)

    fig = plt.figure(figsize=(16, 9), dpi=150)
    fig.patch.set_facecolor(BACKGROUND)

    # Header
    header = fig.add_axes([0.030, 0.910, 0.940, 0.070])
    header.axis("off")
    header.text(
        0.020,
        0.612,
        "p",
        transform=header.transAxes,
        fontsize=12.5,
        color=BACKGROUND,
        fontweight="bold",
        ha="center",
        va="center",
        zorder=5,
        bbox={"boxstyle": "circle,pad=0.28", "facecolor": BLUE, "edgecolor": BLUE, "alpha": 0.90},
    )
    text(header, 0.050, 0.610, "POINKLE SNAPSHOT", size=10.5, color=TEXT, weight="normal")
    text(header, 0.500, 0.610, f"{symbol} TEACHING YOU WHAT TO LOOK AT NEXT", size=19.5, color=BLUE, weight="bold", ha="center")
    text(header, 1.000, 0.620, datetime.now().strftime("%b %-d, %Y").upper(), size=8.2, color=MUTED, weight="bold", ha="right")

    # Teaching cards
    card_y = 0.765
    card_h = 0.110
    card_w = 0.172
    card_gap = 0.012
    card_left = 0.035
    card_specs = [
        ("READ TREND", "Find higher highs\nand lows.", GREEN),
        ("KEY LEVELS", "Mark support /\nresistance.", BLUE),
        ("WATCH\nLIQUIDITY", "See sweeps\nabove/below.", BLUE),
        ("WAIT FOR\nCONFIRMATION", "Demand clean\nbreakouts.", BLUE),
        ("EXECUTE\nPLAN", "Manage risk.\nStay patient.", BLUE),
    ]
    card_axes = [
        fig.add_axes([card_left + i * (card_w + card_gap), card_y, card_w, card_h])
        for i in range(5)
    ]
    for index, (card_ax, (title, body, accent)) in enumerate(zip(card_axes, card_specs), start=1):
        draw_teaching_card(card_ax, index, title, body, accent)

    # Level 1 layout
    chart_ax = fig.add_axes([0.035, 0.205, 0.930, 0.505])
    footer_ax = fig.add_axes([0.040, 0.052, 0.920, 0.105])
    guide_ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    guide_ax.axis("off")
    guide_ax.patch.set_alpha(0)
    guide_ax.set_zorder(10)

    # Optional TradingView background. If it fails, draw local candles.
    background_path = capture_tradingview_chart(symbol)
    if background_path:
        bg = plt.imread(background_path)
        chart_ax.imshow(bg, extent=[-1, len(recent), y_min, y_max], aspect="auto", alpha=0.80, zorder=0)
        try:
            os.unlink(background_path)
        except Exception:
            pass

    style_axis(chart_ax)
    chart_ax.set_xlim(-1, len(recent))
    chart_ax.set_ylim(y_min, y_max)
    chart_ax.grid(False)
    chart_ax.set_xticks([])
    chart_ax.set_yticks([])
    chart_ax.tick_params(left=False, right=False, bottom=False, labelleft=False, labelright=False, labelbottom=False)
    for spine in chart_ax.spines.values():
        spine.set_visible(False)
    chart_ax.text(0.50, 0.43, "POINKLE", transform=chart_ax.transAxes, color=WHITE, fontsize=56, alpha=0.020, ha="center", va="center", fontweight="bold", zorder=0)
    guide_ax.text(0.50, 0.030, "Prepare. Let price tell you. Patience compounds.", color=TEXT, fontsize=9.5, alpha=0.44, ha="center", va="center", fontfamily="serif", zorder=6)

    x0, x1 = -1, len(recent)
    draw_liquidity_band(chart_ax, current_price, x0, x1, current_price)
    if visible_resistances:
        draw_zone(chart_ax, visible_resistances[0], x0, x1, current_price, RED, "MAJOR RESISTANCE")
    if visible_supports:
        draw_zone(chart_ax, visible_supports[0], x0, x1, current_price, GREEN, "MAJOR SUPPORT")

    # Always draw local candles over background so the snapshot is reliable.
    draw_candles(chart_ax, recent)

    ema21_values = usable_ema_series(ema21, [c["close"] for c in candles], 21)
    ema55_values = usable_ema_series(ema55, [c["close"] for c in candles], 55)
    if ema21_values:
        vals = ema21_values[-len(recent):]
        vals_x = x[-len(vals):]
        chart_ax.plot(vals_x, vals, color="#e5edf2", linewidth=0.85, alpha=0.66, zorder=7)
        draw_ema_label(chart_ax, vals_x, vals, "EMA 21", "#edf6fa")
    if ema55_values:
        vals = ema55_values[-len(recent):]
        vals_x = x[-len(vals):]
        chart_ax.plot(vals_x, vals, color="#d1a94a", linewidth=1.10, alpha=0.58, zorder=6)
        draw_ema_label(chart_ax, vals_x, vals, "EMA 55", "#e8c76a")

    arrow_starts = [0.120, 0.305, 0.490, 0.675, 0.860]
    arrow_ends = [(0.250, 0.520), (0.385, 0.560), (0.505, 0.630), (0.665, 0.640), (0.760, 0.570)]
    arrow_rads = [0.30, 0.12, 0.02, -0.10, -0.28]
    for start_x, end, rad in zip(arrow_starts, arrow_ends, arrow_rads):
        draw_teaching_arrow(guide_ax, (start_x, card_y - 0.005), end, rad=rad)

    draw_level_one_footer(footer_ax, trend_title, trend_hint, current_price, panel_supports, panel_resistances)

    fd, path = tempfile.mkstemp(suffix=".png", prefix=f"{symbol.replace('/', '_')}_draft3_snapshot_")
    os.close(fd)
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor(), bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return path


def generate_poinkle_snapshot_spec_chart(symbol, candles, current_price, supports, resistances, ema21=None, ema55=None):
    if not candles:
        raise ValueError("No candles provided")

    recent = candles[-64:]
    closes = [c["close"] for c in candles]
    visible_closes = [c["close"] for c in recent]
    ema21_values = usable_ema_series(ema21, closes, 21)[-len(recent):]
    ema55_values = usable_ema_series(ema55, closes, 55)[-len(recent):]
    x = list(range(len(recent)))

    candle_low = min(c["low"] for c in recent)
    candle_high = max(c["high"] for c in recent)
    candle_span = max(candle_high - candle_low, abs(current_price) * 0.02, 0.000001)
    y_min = max(candle_low - candle_span * 0.20, 0)
    y_max = candle_high + candle_span * 0.31

    nearby_supports = nearest_levels(supports, current_price, "support", 3)
    nearby_resistances = nearest_levels(resistances, current_price, "resistance", 3)
    support_level = chart_near_levels(nearby_supports, current_price, recent, 1)
    resistance_level = chart_near_levels(nearby_resistances, current_price, recent, 1)
    support_level = support_level[0] if support_level else candle_low + candle_span * 0.03
    resistance_level = resistance_level[0] if resistance_level else candle_high - candle_span * 0.03
    title_symbol = symbol.replace("/", " / ")
    base_symbol = symbol.split("/")[0]

    fig = plt.figure(figsize=(12.96, 8.56), dpi=100)
    fig.patch.set_facecolor("#020b13")

    canvas = fig.add_axes([0, 0, 1, 1])
    canvas.set_xlim(0, 1)
    canvas.set_ylim(0, 1)
    canvas.axis("off")

    # Painted atmosphere, not a dashboard panel.
    canvas.add_patch(Rectangle((0, 0), 1, 1, facecolor="#04121c", edgecolor="none", zorder=0))
    for alpha, width in [(0.085, 0.78), (0.055, 0.54), (0.035, 0.32)]:
        canvas.add_patch(
            Circle((0.82, 0.05), width, transform=canvas.transAxes, facecolor="#0a7890", edgecolor="none", alpha=alpha, zorder=0)
        )
    canvas.add_patch(Circle((0.48, 0.48), 0.58, transform=canvas.transAxes, facecolor="#0b3340", edgecolor="none", alpha=0.10, zorder=0))
    canvas.add_patch(Rectangle((0, 0), 1, 1, facecolor="#010711", edgecolor="none", alpha=0.32, zorder=1))
    canvas.add_patch(Rectangle((0, 0.93), 1, 0.07, facecolor="#010610", edgecolor="none", alpha=0.28, zorder=2))
    canvas.add_patch(Rectangle((0, 0), 1, 0.10, facecolor="#010610", edgecolor="none", alpha=0.22, zorder=2))
    canvas.add_patch(Rectangle((0, 0), 0.035, 1, facecolor="#010610", edgecolor="none", alpha=0.24, zorder=2))
    canvas.add_patch(Rectangle((0.965, 0), 0.035, 1, facecolor="#010610", edgecolor="none", alpha=0.22, zorder=2))

    # Header logo mark.
    logo_ax = fig.add_axes([0.032, 0.918, 0.050, 0.060])
    logo_ax.set_xlim(0, 1)
    logo_ax.set_ylim(0, 1)
    logo_ax.axis("off")
    logo_color = "#28d7e4"
    logo_ax.add_patch(Circle((0.50, 0.50), 0.38, facecolor=logo_color, edgecolor="none", alpha=0.12))
    logo_ax.add_patch(Circle((0.50, 0.50), 0.32, facecolor=logo_color, edgecolor="none", alpha=0.92))
    logo_ax.add_patch(Circle((0.25, 0.78), 0.15, facecolor=logo_color, edgecolor="none", alpha=0.92))
    logo_ax.add_patch(Circle((0.75, 0.78), 0.15, facecolor=logo_color, edgecolor="none", alpha=0.92))
    logo_ax.add_patch(Circle((0.40, 0.56), 0.035, facecolor="#06202b", edgecolor="none", alpha=0.90))
    logo_ax.add_patch(Circle((0.60, 0.56), 0.035, facecolor="#06202b", edgecolor="none", alpha=0.90))
    logo_ax.add_patch(Circle((0.50, 0.39), 0.135, facecolor="#0aaec6", edgecolor="none", alpha=0.85))
    logo_ax.add_patch(Circle((0.455, 0.39), 0.022, facecolor="#06202b", edgecolor="none", alpha=0.75))
    logo_ax.add_patch(Circle((0.545, 0.39), 0.022, facecolor="#06202b", edgecolor="none", alpha=0.75))

    brand_text = canvas.text(0.082, 0.945, "POINKLE SNAPSHOT", color="#d3dee6", fontsize=12, ha="left", va="center", zorder=5)
    brand_text.set_path_effects([pe.withStroke(linewidth=2.6, foreground="#0a3f4a", alpha=0.45)])
    title_text = canvas.text(
        0.215,
        0.950,
        f"{title_symbol} TEACHING YOU WHAT TO LOOK AT NEXT",
        color="#42dff4",
        fontsize=19,
        fontweight="bold",
        ha="left",
        va="center",
        zorder=5,
    )
    title_text.set_path_effects([pe.withStroke(linewidth=5.5, foreground="#0a6c7d", alpha=0.52)])
    canvas.text(0.965, 0.948, datetime.now().strftime("%b %-d, %Y").upper(), color="#9aa9b8", fontsize=10, fontweight="bold", ha="right", va="center", zorder=5)

    def spec_card(left, number, title, body):
        ax = fig.add_axes([left, 0.760, 0.174, 0.132])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.add_patch(
            FancyBboxPatch(
                (0.02, 0.02),
                0.96,
                0.96,
                boxstyle="round,pad=0.018,rounding_size=0.055",
                facecolor="#122a36",
                edgecolor="#47dcec",
                linewidth=0.55,
                alpha=0.42,
                zorder=1,
            )
        )
        ax.add_patch(
            FancyBboxPatch(
                (0.02, 0.02),
                0.96,
                0.96,
                boxstyle="round,pad=0.018,rounding_size=0.055",
                facecolor="none",
                edgecolor="#6fefff",
                linewidth=10,
                alpha=0.030,
                zorder=0,
            )
        )
        ax.add_patch(Circle((0.155, 0.680), 0.090, facecolor="#2ee7f2", edgecolor="none", alpha=0.95, zorder=3))
        ax.text(0.155, 0.680, str(number), color="#05131a", fontsize=14, fontweight="bold", ha="center", va="center", zorder=4)
        card_title = ax.text(0.275, 0.700, title, color="#38dff2", fontsize=11.1, fontweight="bold", ha="left", va="center", zorder=4, linespacing=0.92)
        card_title.set_path_effects([pe.withStroke(linewidth=2.4, foreground="#0b5d6d", alpha=0.42)])
        ax.text(0.205, 0.300, body, color="#d7e0e6", fontsize=8.7, ha="left", va="center", zorder=4)
        return ax

    card_lefts = [0.030, 0.215, 0.410, 0.595, 0.795]
    card_specs = [
        ("READ TREND", "Find higher highs and lows."),
        ("KEY LEVELS", "Mark support / resistance."),
        ("WATCH\nLIQUIDITY", "Watch price reaction."),
        ("WAIT FOR\nCONFIRMATION", "Demand clean breakouts."),
        ("EXECUTE\nPLAN", "Manage risk.  Stay patient."),
    ]
    for index, (left, (title, body)) in enumerate(zip(card_lefts, card_specs), start=1):
        spec_card(left, index, title, body)

    chart_ax = fig.add_axes([0.030, 0.260, 0.885, 0.485])
    chart_ax.set_facecolor((0, 0, 0, 0))
    chart_ax.set_xlim(-1, len(recent))
    chart_ax.set_ylim(y_min, y_max)
    chart_ax.axis("off")

    chart_ax.text(
        0.56,
        0.45,
        "POINKLE",
        transform=chart_ax.transAxes,
        color="#d7f7ff",
        fontsize=54,
        fontweight="bold",
        ha="center",
        va="center",
        alpha=0.0315,
        zorder=0,
    )

    def band(level, thickness, color, alpha, start=0, end=None):
        end = len(recent) if end is None else end
        x_left = start - 1
        width = end - start + 1
        chart_ax.add_patch(
            Rectangle((x_left, level - thickness * 0.36), width, thickness * 0.72, facecolor=color, edgecolor="none", alpha=alpha, zorder=1)
        )
        for y_offset in (-0.50, 0.36):
            chart_ax.add_patch(
                Rectangle((x_left, level + thickness * y_offset), width, thickness * 0.14, facecolor=color, edgecolor="none", alpha=alpha * 0.34, zorder=1)
            )

    band(resistance_level, candle_span * 0.126, "#c95a63", 0.18, start=max(4, len(recent) // 3), end=len(recent) - 3)
    band(support_level, candle_span * 0.138, "#2fa66c", 0.12, start=2, end=len(recent))

    def draw_liquidity_levels(levels):
        x_start = max(2, len(recent) // 12)
        x_end = min(len(recent) - 3, int(len(recent) * 0.90))
        for level in levels:
            if not y_min <= level <= y_max:
                continue
            chart_ax.hlines(
                level,
                x_start,
                x_end,
                colors="#d9b84f",
                linewidth=1.0,
                linestyles="-",
                alpha=0.32,
                zorder=5,
            )
            chart_ax.text(
                x_end + 0.8,
                level,
                "LIQ",
                color="#d9b84f",
                fontsize=5.8,
                fontweight="bold",
                ha="left",
                va="center",
                alpha=0.38,
                zorder=5,
            )

    draw_liquidity_levels([])

    # Real candles and EMA overlays.
    for i, candle in enumerate(recent):
        open_, high, low, close = candle["open"], candle["high"], candle["low"], candle["close"]
        color = "#65e95c" if close >= open_ else "#ff4f45"
        chart_ax.vlines(i, low, high, color=color, linewidth=1.15, alpha=1.0, zorder=8)
        body_low = min(open_, close)
        body_h = abs(close - open_) or candle_span * 0.004
        chart_ax.add_patch(
            Rectangle((i - 0.40, body_low), 0.80, body_h, facecolor=color, edgecolor=color, linewidth=0.30, alpha=1.0, zorder=9)
        )
    if ema21_values:
        ema21_x = x[-len(ema21_values):]
        chart_ax.plot(ema21_x, ema21_values, color="#e5edf2", linewidth=0.85, alpha=0.66, zorder=7)
        draw_ema_label(chart_ax, ema21_x, ema21_values, "EMA 21", "#edf6fa")
    if ema55_values:
        ema55_x = x[-len(ema55_values):]
        chart_ax.plot(ema55_x, ema55_values, color="#d1a94a", linewidth=1.10, alpha=0.58, zorder=6)
        draw_ema_label(chart_ax, ema55_x, ema55_values, "EMA 55", "#e8c76a")

    # Creed in the lower brand margin, outside the chart geometry.
    canvas.text(
        0.50,
        0.030,
        "Prepare. Let price tell you. Patience compounds.",
        color="#d7e7ef",
        fontsize=10.2,
        fontfamily="serif",
        alpha=0.42,
        ha="center",
        va="center",
        zorder=6,
    )

    def curved_arrow(start, end, rad):
        canvas.add_patch(
            FancyArrowPatch(
                start,
                end,
                transform=canvas.transAxes,
                arrowstyle="-|>",
                mutation_scale=19,
                connectionstyle=f"arc3,rad={rad}",
                color="#31ddeb",
                linewidth=1.25,
                linestyle=(0, (1.5, 2.7)),
                alpha=0.52,
                zorder=7,
            )
        )
        canvas.add_patch(Circle(start, 0.004, transform=canvas.transAxes, facecolor="#31ddeb", edgecolor="none", alpha=0.54, zorder=8))

    curved_arrow((0.121, 0.755), (0.245, 0.525), 0.32)
    curved_arrow((0.312, 0.755), (0.385, 0.585), 0.10)
    curved_arrow((0.498, 0.755), (0.507, 0.640), 0.02)
    curved_arrow((0.688, 0.755), (0.685, 0.640), -0.06)
    curved_arrow((0.875, 0.755), (0.720, 0.595), -0.28)

    footer = fig.add_axes([0.040, 0.100, 0.920, 0.105])
    footer.set_xlim(0, 1)
    footer.set_ylim(0, 1)
    footer.axis("off")
    footer.add_patch(
        FancyBboxPatch(
            (0, 0.02),
            1,
            0.86,
            boxstyle="round,pad=0.012,rounding_size=0.040",
            facecolor="#143243",
            edgecolor="#61e8fb",
            linewidth=0.65,
            alpha=0.38,
            zorder=1,
        )
    )
    footer.add_patch(
        FancyBboxPatch(
            (0, 0.02),
            1,
            0.86,
            boxstyle="round,pad=0.012,rounding_size=0.040",
            facecolor="none",
            edgecolor="#68e9f7",
            linewidth=8,
            alpha=0.018,
            zorder=0,
        )
    )
    footer_title = footer.text(0.50, 0.665, "WHAT TO WATCH NEXT", color="#3bdff4", fontsize=16, fontweight="bold", ha="center", va="center", zorder=3)
    footer_title.set_path_effects([pe.withStroke(linewidth=3.0, foreground="#0b6878", alpha=0.42)])

    support_text = format_price(nearby_supports[0]) if nearby_supports else format_price(support_level)
    resistance_text = format_price(nearby_resistances[0]) if nearby_resistances else format_price(resistance_level)
    watch_items = [
        f"1. Hold {support_text} support \u2192 trend stays healthy",
        f"2. Reclaim {format_price(current_price)} \u2192 buyers step back in",
        f"3. Break {resistance_text} \u2192 next leg can start",
    ]
    footer_x = [0.065, 0.385, 0.690]
    for idx, (x_pos, item) in enumerate(zip(footer_x, watch_items)):
        footer.text(x_pos, 0.315, item, color="#dbe7ef", fontsize=11.2, ha="left", va="center", zorder=3)
        if idx < 2:
            footer.plot([x_pos + 0.292, x_pos + 0.292], [0.20, 0.50], color="#2dd4f0", linewidth=1.0, alpha=0.55, zorder=3)

    canvas.text(
        0.50,
        0.062,
        "End of Snapshot  \u2022  Ready for Next Level",
        color="#a9b8c5",
        fontsize=10.5,
        alpha=0.78,
        ha="center",
        va="center",
        zorder=5,
    )

    fd, path = tempfile.mkstemp(suffix=".png", prefix=f"{symbol.replace('/', '_')}_poinkle_spec_snapshot_")
    os.close(fd)
    fig.savefig(path, dpi=100, facecolor=fig.get_facecolor(), bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return path


def generate_poinkle_reference_snapshot_chart(symbol, candles, current_price, supports, resistances, ema21=None, ema55=None):
    if not candles:
        raise ValueError("No candles provided")

    recent = candles[-96:] if len(candles) >= 96 else candles[:]
    closes = [c["close"] for c in candles]
    ema21_values = usable_ema_series(ema21, closes, 21)[-len(recent):]
    ema55_values = usable_ema_series(ema55, closes, 55)[-len(recent):]
    x = list(range(len(recent)))

    candle_low = min(c["low"] for c in recent)
    candle_high = max(c["high"] for c in recent)
    candle_span = max(candle_high - candle_low, abs(current_price) * 0.018, 0.000001)

    nearby_supports = nearest_levels(supports, current_price, "support", 3)
    nearby_resistances = nearest_levels(resistances, current_price, "resistance", 3)
    support_level = chart_near_levels(nearby_supports, current_price, recent, 1)
    resistance_level = chart_near_levels(nearby_resistances, current_price, recent, 1)
    support_level = support_level[0] if support_level else candle_low + candle_span * 0.05
    resistance_level = resistance_level[0] if resistance_level else candle_high - candle_span * 0.04

    zone_low = min(support_level, candle_low)
    zone_high = max(resistance_level, candle_high)
    y_min = max(zone_low - candle_span * 0.18, 0)
    y_max = zone_high + candle_span * 0.24

    fig = plt.figure(figsize=(12.96, 8.56), dpi=100)
    fig.patch.set_facecolor("#03101a")
    canvas = fig.add_axes([0, 0, 1, 1])
    canvas.set_xlim(0, 1)
    canvas.set_ylim(0, 1)
    canvas.axis("off")

    width, height = 1296, 856
    yy, xx = np.mgrid[0:1:complex(height), 0:1:complex(width)]
    base = np.zeros((height, width, 3))
    top = np.array([3, 15, 25]) / 255
    mid = np.array([5, 35, 49]) / 255
    glow = np.array([12, 118, 138]) / 255
    base[:] = top
    base = base * (0.92 - yy[..., None] * 0.18) + mid * (0.10 + yy[..., None] * 0.08)
    radial = np.exp(-(((xx - 0.78) ** 2) / 0.11 + ((yy - 0.90) ** 2) / 0.28))
    center_glow = np.exp(-(((xx - 0.50) ** 2) / 0.34 + ((yy - 0.54) ** 2) / 0.20))
    vignette = np.clip(((xx - 0.5) ** 2 + (yy - 0.52) ** 2) * 1.55, 0, 0.55)
    img = base + glow * radial[..., None] * 0.30 + glow * center_glow[..., None] * 0.12
    img = np.clip(img * (1 - vignette[..., None]), 0, 1)
    canvas.imshow(img, extent=[0, 1, 0, 1], origin="lower", zorder=0, aspect="auto")
    canvas.add_patch(Rectangle((0, 0), 1, 1, facecolor="#020811", edgecolor="none", alpha=0.20, zorder=1))
    canvas.add_patch(Rectangle((0, 0.94), 1, 0.06, facecolor="#010711", edgecolor="none", alpha=0.32, zorder=2))

    def glow_text(ax, x_pos, y_pos, value, size, color="#38def2", weight="bold", ha="left", va="center", glow="#0b6b7d", lw=4, alpha=0.55, family=None):
        txt = ax.text(x_pos, y_pos, value, transform=ax.transAxes, fontsize=size, color=color, fontweight=weight, ha=ha, va=va, zorder=8, fontfamily=family)
        txt.set_path_effects([pe.withStroke(linewidth=lw, foreground=glow, alpha=alpha)])
        return txt

    logo_ax = fig.add_axes([0.032, 0.914, 0.050, 0.064])
    logo_ax.set_xlim(0, 1)
    logo_ax.set_ylim(0, 1)
    logo_ax.axis("off")
    logo_ax.add_patch(Circle((0.50, 0.50), 0.42, facecolor="#21d9e8", edgecolor="none", alpha=0.12))
    logo_ax.add_patch(Circle((0.50, 0.50), 0.31, facecolor="#24d8e8", edgecolor="none", alpha=0.95))
    logo_ax.add_patch(Circle((0.25, 0.76), 0.15, facecolor="#24d8e8", edgecolor="none", alpha=0.95))
    logo_ax.add_patch(Circle((0.75, 0.76), 0.15, facecolor="#24d8e8", edgecolor="none", alpha=0.95))
    logo_ax.add_patch(Circle((0.39, 0.55), 0.035, facecolor="#073142", edgecolor="none", alpha=0.92))
    logo_ax.add_patch(Circle((0.61, 0.55), 0.035, facecolor="#073142", edgecolor="none", alpha=0.92))
    logo_ax.add_patch(Circle((0.50, 0.39), 0.13, facecolor="#0aaec6", edgecolor="none", alpha=0.86))
    logo_ax.add_patch(Circle((0.455, 0.39), 0.020, facecolor="#073142", edgecolor="none", alpha=0.86))
    logo_ax.add_patch(Circle((0.545, 0.39), 0.020, facecolor="#073142", edgecolor="none", alpha=0.86))

    canvas.text(0.083, 0.946, "POINKLE SNAPSHOT", color="#d2dee5", fontsize=12.2, ha="left", va="center", zorder=8)
    title_symbol = symbol.replace("/", " / ")
    glow_text(canvas, 0.50, 0.954, f"{title_symbol} TEACHING YOU WHAT TO LOOK AT NEXT", 24, ha="center", lw=5.0, alpha=0.60)
    canvas.text(0.966, 0.948, datetime.now().strftime("%b %-d, %Y").upper(), color="#a9b6c3", fontsize=9.8, fontweight="bold", ha="right", va="center", zorder=8)

    def card(left, number, title, body):
        ax = fig.add_axes([left, 0.760, 0.174, 0.132])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.018,rounding_size=0.050", facecolor="#173240", edgecolor="none", alpha=0.25, zorder=0))
        ax.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.018,rounding_size=0.050", facecolor="none", edgecolor="#80eaff", linewidth=9, alpha=0.025, zorder=1))
        ax.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.018,rounding_size=0.050", facecolor="#112632", edgecolor="#49dcea", linewidth=0.65, alpha=0.58, zorder=2))
        ax.add_patch(Circle((0.155, 0.68), 0.087, facecolor="#30e2ee", edgecolor="none", alpha=0.96, zorder=4))
        ax.text(0.155, 0.68, str(number), color="#05131b", fontsize=14, fontweight="bold", ha="center", va="center", zorder=5)
        title_text = ax.text(0.275, 0.70, title, color="#39def1", fontsize=11.2, fontweight="bold", ha="left", va="center", linespacing=0.92, zorder=5)
        title_text.set_path_effects([pe.withStroke(linewidth=2.5, foreground="#0a6071", alpha=0.48)])
        ax.text(0.205, 0.30, body, color="#d2dde4", fontsize=8.7, ha="left", va="center", zorder=5)

    card_specs = [
        ("READ TREND", "Find higher highs and lows."),
        ("KEY LEVELS", "Mark support / resistance."),
        ("WATCH\nLIQUIDITY", "See sweeps above/below."),
        ("WAIT FOR\nCONFIRMATION", "Demand clean breakouts."),
        ("EXECUTE\nPLAN", "Manage risk.  Stay patient."),
    ]
    for idx, (left, spec) in enumerate(zip([0.030, 0.215, 0.410, 0.595, 0.795], card_specs), start=1):
        card(left, idx, spec[0], spec[1])

    chart_ax = fig.add_axes([0.030, 0.255, 0.885, 0.500])
    chart_ax.set_facecolor((0, 0, 0, 0))
    chart_ax.set_xlim(-1, len(recent))
    chart_ax.set_ylim(y_min, y_max)
    chart_ax.axis("off")
    for grid_level in np.linspace(y_min, y_max, 6)[1:-1]:
        chart_ax.hlines(grid_level, -1, len(recent), colors="#31505a", linewidth=0.45, alpha=0.12, zorder=0)

    chart_ax.text(0.55, 0.42, "POINKLE", transform=chart_ax.transAxes, color="#e0fbff", fontsize=54, fontweight="bold", ha="center", va="center", alpha=0.030, zorder=0)

    def soft_zone(level, thickness, color, alpha, start, end):
        width = end - start
        chart_ax.add_patch(Rectangle((start, level - thickness * 0.42), width, thickness * 0.84, facecolor=color, edgecolor="none", alpha=alpha, zorder=1))
        chart_ax.add_patch(Rectangle((start, level - thickness * 0.62), width, thickness * 0.20, facecolor=color, edgecolor="none", alpha=alpha * 0.28, zorder=1))
        chart_ax.add_patch(Rectangle((start, level + thickness * 0.42), width, thickness * 0.20, facecolor=color, edgecolor="none", alpha=alpha * 0.28, zorder=1))

    soft_zone(resistance_level, candle_span * 0.12, "#ba4d5d", 0.23, max(2, len(recent) * 0.34), len(recent) * 0.94)
    soft_zone(support_level, candle_span * 0.13, "#249663", 0.20, 2, len(recent) * 0.98)
    neutral_level = (support_level + current_price) / 2
    if y_min < neutral_level < y_max:
        soft_zone(neutral_level, candle_span * 0.10, "#b5a56e", 0.075, len(recent) * 0.24, len(recent) * 0.70)

    def draw_liquidity_levels(levels):
        x_start = max(2, int(len(recent) * 0.10))
        x_end = min(len(recent) - 2, int(len(recent) * 0.90))
        for level in levels:
            if not y_min <= level <= y_max:
                continue
            chart_ax.hlines(level, x_start, x_end, colors="#d2ad45", linewidth=0.9, alpha=0.30, zorder=3)
            chart_ax.text(x_end + 1.0, level, "LIQ", color="#d2ad45", fontsize=5.6, fontweight="bold", ha="left", va="center", alpha=0.38, zorder=3)

    draw_liquidity_levels([])

    for i, candle in enumerate(recent):
        open_, high, low, close = candle["open"], candle["high"], candle["low"], candle["close"]
        color = "#70e361" if close >= open_ else "#f15346"
        chart_ax.vlines(i, low, high, color=color, linewidth=0.88, alpha=0.92, zorder=8)
        body_low = min(open_, close)
        body_h = abs(close - open_) or candle_span * 0.0035
        chart_ax.add_patch(Rectangle((i - 0.30, body_low), 0.60, body_h, facecolor=color, edgecolor=color, linewidth=0.25, alpha=0.95, zorder=9))

    if ema21_values:
        ema21_x = x[-len(ema21_values):]
        chart_ax.plot(ema21_x, ema21_values, color="#e5edf2", linewidth=0.85, alpha=0.66, zorder=7)
        draw_ema_label(chart_ax, ema21_x, ema21_values, "EMA 21", "#edf6fa")
    if ema55_values:
        ema55_x = x[-len(ema55_values):]
        chart_ax.plot(ema55_x, ema55_values, color="#d1a94a", linewidth=1.10, alpha=0.58, zorder=6)
        draw_ema_label(chart_ax, ema55_x, ema55_values, "EMA 55", "#e8c76a")

    creed = canvas.text(0.50, 0.030, "Prepare. Let price tell you. Patience compounds.", color="#d8e8ef", fontsize=10.2, fontfamily="serif", alpha=0.44, ha="center", va="center", zorder=5)
    creed.set_path_effects([pe.withStroke(linewidth=2.0, foreground="#0b1c25", alpha=0.35)])

    def curved_arrow(start, end, rad):
        canvas.add_patch(FancyArrowPatch(start, end, transform=canvas.transAxes, arrowstyle="-|>", mutation_scale=19, connectionstyle=f"arc3,rad={rad}", color="#32dbea", linewidth=1.10, linestyle=(0, (1.5, 2.6)), alpha=0.58, zorder=9))
        canvas.add_patch(Circle(start, 0.004, transform=canvas.transAxes, facecolor="#32dbea", edgecolor="none", alpha=0.62, zorder=9))

    for start, end, rad in [
        ((0.121, 0.755), (0.245, 0.525), 0.32),
        ((0.312, 0.755), (0.385, 0.585), 0.10),
        ((0.498, 0.755), (0.507, 0.640), 0.02),
        ((0.688, 0.755), (0.685, 0.640), -0.06),
        ((0.875, 0.755), (0.720, 0.595), -0.28),
    ]:
        curved_arrow(start, end, rad)

    footer = fig.add_axes([0.040, 0.100, 0.920, 0.105])
    footer.set_xlim(0, 1)
    footer.set_ylim(0, 1)
    footer.axis("off")
    footer.add_patch(FancyBboxPatch((0, 0.02), 1, 0.86, boxstyle="round,pad=0.012,rounding_size=0.040", facecolor="#143341", edgecolor="#5ae6f4", linewidth=0.6, alpha=0.36, zorder=1))
    footer.add_patch(FancyBboxPatch((0, 0.02), 1, 0.86, boxstyle="round,pad=0.012,rounding_size=0.040", facecolor="none", edgecolor="#6fefff", linewidth=8, alpha=0.020, zorder=0))
    footer_title = footer.text(0.50, 0.665, "WHAT TO WATCH NEXT", color="#3bdff4", fontsize=15.5, fontweight="bold", ha="center", va="center", zorder=3)
    footer_title.set_path_effects([pe.withStroke(linewidth=3.0, foreground="#0b6878", alpha=0.42)])

    support_text = format_price(nearby_supports[0]) if nearby_supports else format_price(support_level)
    resistance_text = format_price(nearby_resistances[0]) if nearby_resistances else format_price(resistance_level)
    watch_items = [
        f"1. Reclaim {format_price(current_price)} \u2192 buyers step back in",
        f"2. Break {resistance_text} \u2192 next leg can start",
        f"3. Lose {support_text} \u2192 watch support reaction",
    ]
    for idx, (x_pos, item) in enumerate(zip([0.065, 0.385, 0.690], watch_items)):
        footer.text(x_pos, 0.315, item, color="#dbe7ef", fontsize=10.8, ha="left", va="center", zorder=3)
        if idx < 2:
            footer.plot([x_pos + 0.292, x_pos + 0.292], [0.20, 0.50], color="#2dd4f0", linewidth=1.0, alpha=0.52, zorder=3)

    canvas.text(0.50, 0.062, "End of Snapshot  \u2022  Ready for Next Level", color="#a9b8c5", fontsize=10.5, alpha=0.74, ha="center", va="center", zorder=5)

    fd, path = tempfile.mkstemp(suffix=".png", prefix=f"{symbol.replace('/', '_')}_poinkle_reference_reset_")
    os.close(fd)
    fig.savefig(path, dpi=100, facecolor=fig.get_facecolor(), bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return path


def generate_levels_chart(
    symbol,
    candles,
    current_price,
    supports,
    resistances,
    ema21=None,
    ema55=None,
    ema200=None,
    card_specs=None,
    footer_items=None,
    title=None,
    output_prefix=None,
    signal_scope=None,
    support_label=None,
    resistance_label=None,
    chart_annotations=None,
    teaching_mode=False,
    teaching_zone=None,
):
    from chart_generator_reference import generate_reference_levels_chart

    return generate_reference_levels_chart(
        symbol,
        candles,
        current_price,
        supports,
        resistances,
        ema21=ema21,
        ema55=ema55,
        ema200=ema200,
        card_specs=card_specs,
        footer_items=footer_items,
        title=title,
        output_prefix=output_prefix,
        signal_scope=signal_scope,
        support_label=support_label,
        resistance_label=resistance_label,
        chart_annotations=chart_annotations,
        teaching_mode=teaching_mode,
        teaching_zone=teaching_zone,
    )
