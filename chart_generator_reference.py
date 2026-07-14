import math
import os
import tempfile
import textwrap
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle

GHOST_WATERMARK_OPACITY = 0.05
GHOST_WATERMARK_PATHS = (
    os.path.join("assets", "poinkle_ghost_watermark.png"),
    os.path.join("assets", "poinkle_pig_silhouette.png"),
    os.path.join("assets", "poinkle_silhouette_logo.png"),
)
POINKLE_LOGO_WATERMARK_PATHS = (
    os.path.join("assets", "poinkle_logo_full.png"),
    os.path.join("assets", "poinkle_prb_logo.png"),
)


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


def ema_series(values, period):
    if not values:
        return []
    multiplier = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append((value - out[-1]) * multiplier + out[-1])
    return out


def usable_ema(values, closes, period):
    values = list(values or [])
    sample = values[-min(len(values), 12):]
    if len(sample) >= 2 and len({round(value, 8) for value in sample}) > 1:
        return values
    return ema_series(closes, period)


def nearest_levels(levels, current_price, side, limit=3):
    levels = list(levels or [])
    if side == "support":
        candidates = sorted([level for level in levels if level <= current_price], key=lambda level: current_price - level)
    else:
        candidates = sorted([level for level in levels if level >= current_price], key=lambda level: level - current_price)
    if len(candidates) < limit:
        extras = sorted([level for level in levels if level not in candidates], key=lambda level: abs(level - current_price))
        candidates.extend(extras)
    return candidates[:limit]


def in_view_level(levels, low, high, fallback):
    visible = [level for level in levels if low <= level <= high]
    if visible:
        return visible[0]
    return fallback


def liquidity_levels_from_structure(candles, y_min, y_max, current_price):
    if len(candles) < 20:
        return []
    span = max(max(c["high"] for c in candles) - min(c["low"] for c in candles), 1)
    tolerance = max(span * 0.018, abs(current_price) * 0.0008)
    min_spacing = max(span * 0.09, abs(current_price) * 0.002)
    candidates = []
    lookback = 2
    swings = {"high": [], "low": []}
    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback : i + lookback + 1]
        if candles[i]["high"] >= max(c["high"] for c in window):
            swings["high"].append((candles[i]["high"], i))
        if candles[i]["low"] <= min(c["low"] for c in window):
            swings["low"].append((candles[i]["low"], i))

    for field, points in swings.items():
        points = sorted(points)
        cluster = []
        for level, idx in points:
            if not cluster or abs(level - np.mean([p[0] for p in cluster])) <= tolerance:
                cluster.append((level, idx))
            else:
                _add_confirmed_liquidity_candidate(candidates, cluster, field, len(candles), y_min, y_max)
                cluster = [(level, idx)]
        _add_confirmed_liquidity_candidate(candidates, cluster, field, len(candles), y_min, y_max)

    candidates = [
        (level, score + max(0, 1.6 - abs(level - current_price) / max(span, 1) * 2.0), idx)
        for level, score, idx in candidates
        if y_min <= level <= y_max
    ]
    candidates.sort(key=lambda item: item[1], reverse=True)
    selected = []
    for level, score, idx in candidates:
        if any(abs(level - existing) < min_spacing for existing in selected):
            continue
        selected.append(level)
        if len(selected) >= 4:
            break
    return sorted(selected) if len(selected) >= 2 else []


def _add_confirmed_liquidity_candidate(candidates, cluster, field, candle_count, y_min, y_max):
    if len(cluster) < 2:
        return
    indexes = sorted(idx for _, idx in cluster)
    if indexes[-1] - indexes[0] < 6:
        return
    level = float(np.mean([price for price, _ in cluster]))
    if not y_min <= level <= y_max:
        return
    recency = indexes[-1] / max(candle_count - 1, 1)
    side_weight = 0.15 if field == "high" else 0.0
    score = 3.0 + min(len(cluster), 4) * 0.55 + recency * 0.55 + side_weight
    candidates.append((level, score, indexes[-1]))


def add_pig_logo(ax):
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    cyan = "#25d8e8"
    dark = "#073142"
    ax.add_patch(Circle((0.50, 0.50), 0.44, facecolor=cyan, edgecolor="none", alpha=0.14))
    ax.add_patch(Circle((0.50, 0.50), 0.31, facecolor=cyan, edgecolor="none", alpha=0.96))
    ax.add_patch(Circle((0.25, 0.77), 0.15, facecolor=cyan, edgecolor="none", alpha=0.96))
    ax.add_patch(Circle((0.75, 0.77), 0.15, facecolor=cyan, edgecolor="none", alpha=0.96))
    ax.add_patch(Circle((0.39, 0.56), 0.035, facecolor=dark, edgecolor="none", alpha=0.95))
    ax.add_patch(Circle((0.61, 0.56), 0.035, facecolor=dark, edgecolor="none", alpha=0.95))
    ax.add_patch(Circle((0.50, 0.39), 0.13, facecolor="#0aaec6", edgecolor="none", alpha=0.88))
    ax.add_patch(Circle((0.455, 0.39), 0.020, facecolor=dark, edgecolor="none", alpha=0.86))
    ax.add_patch(Circle((0.545, 0.39), 0.020, facecolor=dark, edgecolor="none", alpha=0.86))


def glow_text(ax, x, y, value, size, color="#39def2", ha="left", va="center", weight="bold", glow="#087287", lw=4.0, alpha=0.55, family=None):
    txt = ax.text(x, y, value, transform=ax.transAxes, fontsize=size, color=color, ha=ha, va=va, fontweight=weight, zorder=10, fontfamily=family)
    txt.set_path_effects([pe.withStroke(linewidth=lw, foreground=glow, alpha=alpha)])
    return txt


def ghost_watermark_path():
    for path in GHOST_WATERMARK_PATHS:
        if os.path.exists(path):
            return path
    return None


def add_ghost_watermark(ax, watermark_path=None, opacity=GHOST_WATERMARK_OPACITY):
    path = watermark_path or ghost_watermark_path()
    if not path:
        return False
    try:
        image = plt.imread(path)
    except Exception:
        return False
    ax.imshow(
        image,
        extent=[0.18, 0.82, 0.08, 0.92],
        transform=ax.transAxes,
        origin="upper",
        aspect="auto",
        alpha=opacity,
        zorder=0.35,
    )
    return True


def logo_watermark_path():
    for path in POINKLE_LOGO_WATERMARK_PATHS:
        if os.path.exists(path):
            return path
    return None


def add_logo_watermark(ax, watermark_path=None, opacity=0.06):
    path = watermark_path or logo_watermark_path()
    if not path:
        return False
    try:
        image = plt.imread(path)
    except Exception:
        return False
    image_height, image_width = image.shape[:2]
    image_aspect = image_width / max(image_height, 1)
    watermark_height = 0.46
    watermark_width = min(0.62, watermark_height * image_aspect)
    watermark_height = watermark_width / max(image_aspect, 0.0001)
    x_center, y_center = 0.50, 0.50
    x0, x1 = x_center - watermark_width / 2, x_center + watermark_width / 2
    y0, y1 = y_center - watermark_height / 2, y_center + watermark_height / 2
    ax.imshow(
        image,
        extent=[x0, x1, y0, y1],
        transform=ax.transAxes,
        origin="upper",
        aspect="equal",
        alpha=opacity,
        zorder=0.35,
    )
    return True


def wrap_card_body(body):
    lines = []
    for raw_line in str(body).splitlines():
        clean = raw_line.strip()
        if not clean:
            continue
        lines.extend(textwrap.wrap(clean, width=21) or [""])
    return lines[:4]


def draw_wrapped_card_body(ax, body):
    lines = wrap_card_body(body)
    if not lines:
        return
    line_count = len(lines)
    fontsize = 8.7 if line_count >= 4 or any(len(line) > 18 for line in lines) else 9.8
    top_y = 0.435 if line_count >= 4 else 0.390 if line_count == 3 else 0.335
    y = top_y
    for line in lines:
        ax.text(
            0.205,
            y,
            line,
            color="#d4dfe5",
            fontsize=fontsize,
            ha="left",
            va="center",
            zorder=4,
        )
        y -= 0.145


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


def generate_reference_levels_chart(
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
    if not candles:
        raise ValueError("No candles provided")

    candle_limit = 70 if teaching_mode else 104
    recent = candles[-candle_limit:] if len(candles) >= candle_limit else candles[:]
    x = list(range(len(recent)))
    closes = [c["close"] for c in candles]
    ema21_values = usable_ema(ema21, closes, 21)[-len(recent):]
    ema55_values = usable_ema(ema55, closes, 55)[-len(recent):]
    ema200_values = (
        usable_ema(ema200, closes, 200)[-len(recent):]
        if ema200 is not None and len(closes) >= 200
        else []
    )

    low = min(c["low"] for c in recent)
    high = max(c["high"] for c in recent)
    min_span = max(abs(current_price) * 0.018, abs(high) * 0.004, 0.00000001)
    span = max(high - low, min_span)
    y_min = max(low - span * 0.18, 0)
    y_max = high + span * 0.24

    near_supports = nearest_levels(supports, current_price, "support", 3)
    near_resistances = nearest_levels(resistances, current_price, "resistance", 3)
    support_level = in_view_level(near_supports, y_min, y_max, low + span * 0.08)
    resistance_level = in_view_level(near_resistances, y_min, y_max, high - span * 0.06)
    if teaching_mode:
        teaching_levels = near_supports[:2] + near_resistances[:2] + [current_price]
        visible_low = min([low] + teaching_levels)
        visible_high = max([high] + teaching_levels)
        span = max(visible_high - visible_low, min_span)
        y_min = max(visible_low - span * 0.045, 0)
        y_max = visible_high + span * 0.060
    liq_levels = liquidity_levels_from_structure(recent, y_min, y_max, current_price)

    fig = plt.figure(figsize=(12.96, 8.56), dpi=100)
    fig.patch.set_facecolor("#03101a")
    canvas = fig.add_axes([0, 0, 1, 1])
    canvas.set_xlim(0, 1)
    canvas.set_ylim(0, 1)
    canvas.axis("off")

    h, w = 856, 1296
    yy, xx = np.mgrid[0:1:complex(h), 0:1:complex(w)]
    navy = np.array([2, 12, 22]) / 255
    teal = np.array([5, 48, 65]) / 255
    cyan = np.array([9, 129, 150]) / 255
    bg = navy + teal * (0.24 + yy[..., None] * 0.24)
    right_glow = np.exp(-(((xx - 0.88) ** 2) / 0.12 + ((yy - 0.08) ** 2) / 0.20))
    center_glow = np.exp(-(((xx - 0.50) ** 2) / 0.46 + ((yy - 0.50) ** 2) / 0.28))
    chart_glow = np.exp(-(((xx - 0.52) ** 2) / 0.34 + ((yy - 0.52) ** 2) / 0.10))
    lower_wash = np.exp(-(((xx - 0.58) ** 2) / 0.55 + ((yy - 0.18) ** 2) / 0.12))
    vignette = np.clip(((xx - 0.50) ** 2 + (yy - 0.52) ** 2) * 1.48, 0, 0.54)
    bg = np.clip(bg + cyan * right_glow[..., None] * 0.50 + cyan * center_glow[..., None] * 0.13 + cyan * chart_glow[..., None] * 0.08 + cyan * lower_wash[..., None] * 0.08, 0, 1)
    bg = np.clip(bg * (1 - vignette[..., None]), 0, 1)
    canvas.imshow(bg, extent=[0, 1, 0, 1], origin="lower", aspect="auto", zorder=0)
    canvas.add_patch(Rectangle((0, 0), 1, 1, facecolor="#010711", edgecolor="none", alpha=0.13, zorder=1))

    if not teaching_mode:
        logo_ax = fig.add_axes([0.031, 0.916, 0.046, 0.064])
        add_pig_logo(logo_ax)
        canvas.text(0.082, 0.947, "POINKLE SNAPSHOT", color="#d2dde4", fontsize=12.0, ha="left", va="center", zorder=10)
    title = title or f"{symbol.replace('/', ' / ')} TEACHING YOU WHAT TO LOOK AT NEXT"
    glow_text(canvas, 0.515, 0.950, title, 18.8, ha="center", lw=4.6, alpha=0.58)
    if signal_scope and not teaching_mode:
        canvas.text(0.515, 0.912, signal_scope, color="#9fb3bf", fontsize=8.6, fontweight="bold", ha="center", va="center", alpha=0.82, zorder=10)
    if not teaching_mode:
        canvas.text(0.966, 0.948, datetime.now().strftime("%b %-d, %Y").upper(), color="#aab7c1", fontsize=9.6, fontweight="bold", ha="right", va="center", zorder=10)

    card_y, card_h, card_w = 0.758, 0.130, 0.176
    card_lefts = [0.030, 0.215, 0.410, 0.595, 0.795]
    card_specs = card_specs or [
        ("READ TREND", "Find higher highs and lows."),
        ("KEY LEVELS", "Mark support / resistance."),
        ("WATCH\nLIQUIDITY", "See sweeps above/below."),
        ("WAIT FOR\nCONFIRMATION", "Demand clean breakouts."),
        ("EXECUTE\nPLAN", "Manage risk.  Stay patient."),
    ]
    if not teaching_mode:
        for idx, (left, (card_title, body)) in enumerate(zip(card_lefts, card_specs), start=1):
            ax = fig.add_axes([left, card_y, card_w, card_h])
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            ax.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.018,rounding_size=0.050", facecolor="#1b3b4a", edgecolor="#5ee9f8", linewidth=13, alpha=0.040, zorder=0))
            ax.add_patch(FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.018,rounding_size=0.050", facecolor="#132b38", edgecolor="#49dcea", linewidth=0.70, alpha=0.72, zorder=1))
            ax.add_patch(Circle((0.155, 0.690), 0.086, facecolor="#31e2ee", edgecolor="none", alpha=0.96, zorder=3))
            ax.text(0.155, 0.690, str(idx), color="#06141b", fontsize=16, fontweight="bold", ha="center", va="center", zorder=4)
            t = ax.text(0.275, 0.710, card_title, color="#3ce1f3", fontsize=13.0, fontweight="bold", ha="left", va="center", linespacing=0.90, zorder=4)
            t.set_path_effects([pe.withStroke(linewidth=2.6, foreground="#0a6574", alpha=0.46)])
            draw_wrapped_card_body(ax, body)

    chart_ax = fig.add_axes([0.025, 0.095, 0.895, 0.805] if teaching_mode else [0.030, 0.330, 0.890, 0.420])
    x_right = len(recent) * 1.16 if teaching_mode else len(recent) * 1.12
    future_label_x = len(recent) + max(0.8, len(recent) * 0.015)
    chart_ax.set_facecolor((0, 0, 0, 0))
    chart_ax.set_xlim(-1, x_right)
    chart_ax.set_ylim(y_min, y_max)
    if teaching_mode:
        chart_ax.spines["left"].set_visible(False)
        chart_ax.spines["top"].set_visible(False)
        chart_ax.spines["bottom"].set_visible(False)
        chart_ax.spines["right"].set_color("#5f7c86")
        chart_ax.spines["right"].set_alpha(0.34)
        chart_ax.yaxis.tick_right()
        chart_ax.tick_params(axis="x", which="both", bottom=False, labelbottom=False)
        chart_ax.tick_params(axis="y", colors="#d6e6ec", labelsize=15.0, length=0, pad=10)
    else:
        chart_ax.axis("off")
    for grid_y in np.linspace(y_min, y_max, 7)[1:-1]:
        chart_ax.hlines(grid_y, -1, len(recent), colors="#41616a", linewidth=0.45, alpha=0.10, zorder=0)
    watermark_drawn = add_logo_watermark(chart_ax, opacity=0.06) if teaching_mode else add_ghost_watermark(chart_ax)
    if not watermark_drawn:
        watermark_size = 96 if teaching_mode else 58
        watermark_alpha = 0.055 if teaching_mode else 0.035
        chart_ax.text(0.52, 0.50, "POINKLE", transform=chart_ax.transAxes, color="#dffbff", fontsize=watermark_size, fontweight="bold", ha="center", va="center", alpha=watermark_alpha, zorder=0)

    level_ticks = []

    def level_bar(level, thickness, color, alpha, start, end, label=None, *, taught=False):
        if not y_min <= level <= y_max:
            return
        lower = level - thickness * 0.42
        upper = level + thickness * 0.42
        level_ticks.append(level)
        chart_ax.add_patch(Rectangle((start, lower), end - start, thickness * 0.84, facecolor=color, edgecolor=color, linewidth=0, alpha=alpha, zorder=1))
        if label:
            label_x = start + max(1.0, len(recent) * 0.018) if taught else future_label_x
            chart_ax.text(
                label_x,
                level,
                str(label),
                color=color,
                fontsize=12.0,
                fontweight="bold",
                ha="left",
                va="center",
                alpha=0.98,
                zorder=12,
                path_effects=[pe.withStroke(linewidth=2.8, foreground="#03101a", alpha=0.86)],
            )

    if teaching_mode:
        support_thickness = span * 0.125
        resistance_thickness = span * 0.115
        support_context = [level for level in near_supports[:2] if y_min <= level <= y_max]
        resistance_context = [level for level in near_resistances[:2] if y_min <= level <= y_max]
        if support_level not in support_context and y_min <= support_level <= y_max:
            support_context = (support_context + [support_level])[:2]
        if resistance_level not in resistance_context and y_min <= resistance_level <= y_max:
            resistance_context = (resistance_context + [resistance_level])[:2]
        taught_is_resistance = teaching_zone == "resistance"
        taught_level = resistance_level if taught_is_resistance else support_level
        taught_label = resistance_label if taught_is_resistance else support_label

        for index, level in enumerate(resistance_context):
            if taught_is_resistance and math.isclose(level, taught_level, rel_tol=0, abs_tol=max(span * 0.002, 1e-9)):
                continue
            level_bar(level, resistance_thickness * 0.72, "#ff4d5a", 0.28, len(recent) * 0.34, x_right)
        for index, level in enumerate(support_context):
            if not taught_is_resistance and math.isclose(level, taught_level, rel_tol=0, abs_tol=max(span * 0.002, 1e-9)):
                continue
            level_bar(level, support_thickness * 0.72, "#34d978", 0.24, 2, x_right)
        if teaching_zone == "resistance":
            label = str(resistance_label or "Nearest resistance").upper()
            level_bar(resistance_level, resistance_thickness, "#ff5260", 0.34, len(recent) * 0.34, x_right, label, taught=True)
        else:
            label = str(support_label or "Nearest support").upper()
            level_bar(support_level, support_thickness, "#36e27b", 0.34, 2, x_right, label, taught=True)
        teaching_ticks = sorted({round(value, 8): value for value in level_ticks + [current_price]}.values())
        chart_ax.set_yticks(teaching_ticks)
        chart_ax.set_yticklabels([format_price(value) for value in teaching_ticks])
        chart_ax.hlines(current_price, max(len(recent) * 0.08, 0), x_right, colors="#dcebf0", linewidth=1.1, linestyles=(0, (2.0, 3.2)), alpha=0.62, zorder=11)
        chart_ax.text(
            x_right,
            current_price,
            format_price(current_price),
            color="#06141b",
            fontsize=12.5,
            fontweight="bold",
            ha="right",
            va="center",
            bbox={"boxstyle": "round,pad=0.22,rounding_size=0.08", "facecolor": "#dcebf0", "edgecolor": "#5ee6f4", "linewidth": 0.8, "alpha": 0.96},
            zorder=15,
        )
    else:
        def zone(level, thickness, color, alpha, start, end, label=None):
            if not y_min <= level <= y_max:
                return
            lower = level - thickness * 0.42
            upper = level + thickness * 0.42
            chart_ax.add_patch(Rectangle((start, lower), end - start, thickness * 0.84, facecolor=color, edgecolor="none", alpha=alpha, zorder=1))
            chart_ax.add_patch(Rectangle((start, level - thickness * 0.64), end - start, thickness * 0.22, facecolor=color, edgecolor="none", alpha=alpha * 0.28, zorder=1))
            chart_ax.add_patch(Rectangle((start, upper), end - start, thickness * 0.22, facecolor=color, edgecolor="none", alpha=alpha * 0.28, zorder=1))
            if label:
                chart_ax.text(
                    end + 0.9,
                    level,
                    str(label),
                    color=color,
                    fontsize=7.0,
                    fontweight="bold",
                    ha="left",
                    va="center",
                    alpha=0.92,
                    zorder=12,
                    path_effects=[pe.withStroke(linewidth=2.2, foreground="#03101a", alpha=0.80)],
                )

        zone(resistance_level, span * 0.115, "#c7505c", 0.24, len(recent) * 0.34, len(recent) * 0.94, resistance_label)
        mid_zone = current_price if y_min <= current_price <= y_max else (support_level + resistance_level) / 2
        zone(mid_zone, span * 0.090, "#b8ab6b", 0.080, len(recent) * 0.24, len(recent) * 0.70)
        zone(support_level, span * 0.125, "#2c9c64", 0.22, 2, len(recent) * 0.98, support_label)

    if not teaching_mode:
        liq_start, liq_end = int(len(recent) * 0.10), int(len(recent) * 0.90)
        for level in liq_levels[:4]:
            if not y_min <= level <= y_max:
                continue
            chart_ax.hlines(level, liq_start, liq_end, colors="#cba94a", linewidth=0.9, alpha=0.26, zorder=3)
            chart_ax.text(liq_end + 1.0, level, "LIQ", color="#cba94a", fontsize=5.8, fontweight="bold", ha="left", va="center", alpha=0.36, zorder=3)

    for i, candle in enumerate(recent):
        open_, high_, low_, close = candle["open"], candle["high"], candle["low"], candle["close"]
        color = "#73df62" if close >= open_ else "#ef5046"
        wick_width = 1.15 if teaching_mode else 0.82
        body_width = 0.76 if teaching_mode else 0.54
        chart_ax.vlines(i, low_, high_, color=color, linewidth=wick_width, alpha=0.88, zorder=8)
        body_low = min(open_, close)
        body_h = abs(close - open_) or span * 0.003
        chart_ax.add_patch(Rectangle((i - body_width / 2, body_low), body_width, body_h, facecolor=color, edgecolor=color, linewidth=0.22, alpha=0.93, zorder=9))

    time_to_index = {candle.get("time"): index for index, candle in enumerate(recent)}
    for annotation in chart_annotations or []:
        candle_index = time_to_index.get(annotation.get("time"))
        if candle_index is None:
            continue
        candle = recent[candle_index]
        label = str(annotation.get("label") or "").strip()
        if not label:
            continue
        y_value = float(annotation.get("price") or candle.get("close") or current_price)
        chart_ax.scatter(
            [candle_index],
            [y_value],
            s=46,
            facecolor="#38dff2",
            edgecolor="#03101a",
            linewidth=1.1,
            alpha=0.96,
            zorder=13,
        )
        y_offset = span * 0.20 if y_value < (y_min + y_max) / 2 else -span * 0.20
        chart_ax.annotate(
            label,
            xy=(candle_index, y_value),
            xytext=(min(candle_index + 5, len(recent) * 0.96), y_value + y_offset),
            color="#dffbff",
            fontsize=12.0 if teaching_mode else 7.2,
            fontweight="bold",
            ha="left",
            va="center",
            arrowprops={
                "arrowstyle": "->",
                "color": "#38dff2",
                "lw": 1.0,
                "alpha": 0.82,
            },
            path_effects=[pe.withStroke(linewidth=3.1 if teaching_mode else 2.4, foreground="#03101a", alpha=0.86 if teaching_mode else 0.82)],
            zorder=14,
        )

    if ema200_values and not teaching_mode:
        ema200_x = x[-len(ema200_values):]
        chart_ax.plot(ema200_x, ema200_values, color="#60a5fa", linewidth=1.80, alpha=0.72, zorder=5)
        draw_ema_label(chart_ax, ema200_x, ema200_values, "EMA 200", "#93c5fd")
    if ema55_values and not teaching_mode:
        ema55_x = x[-len(ema55_values):]
        chart_ax.plot(ema55_x, ema55_values, color="#d1a94a", linewidth=1.10, alpha=0.58, zorder=6)
        draw_ema_label(chart_ax, ema55_x, ema55_values, "EMA 55", "#e8c76a")
    if ema21_values and not teaching_mode:
        ema21_x = x[-len(ema21_values):]
        chart_ax.plot(ema21_x, ema21_values, color="#e5edf2", linewidth=0.85, alpha=0.66, zorder=7)
        draw_ema_label(chart_ax, ema21_x, ema21_values, "EMA 21", "#edf6fa")

    if not teaching_mode:
        volume_ax = fig.add_axes([0.030, 0.250, 0.890, 0.075], sharex=chart_ax)
        volume_ax.set_facecolor((0, 0, 0, 0))
        volume_ax.set_xlim(-1, len(recent) * 1.12)
        volumes = [float(c.get("volume", 0) or 0) for c in recent]
        max_volume = max(volumes) if volumes else 0
        volume_ax.set_ylim(0, max_volume * 1.18 if max_volume > 0 else 1)
        volume_ax.axis("off")
        volume_ax.axhline(0, color="#41616a", linewidth=0.7, alpha=0.18, zorder=0)
        for i, candle in enumerate(recent):
            candle_volume = float(candle.get("volume", 0) or 0)
            color = "#73df62" if candle["close"] >= candle["open"] else "#ef5046"
            alpha = 0.60 if candle_volume >= max_volume * 0.70 and max_volume > 0 else 0.34
            volume_ax.bar(i, candle_volume, width=0.62, color=color, edgecolor="none", alpha=alpha, zorder=3)
        volume_ax.text(0.010, 0.820, "VOLUME", transform=volume_ax.transAxes, color="#9fb3bf", fontsize=7.5, fontweight="bold", ha="left", va="center", alpha=0.80, zorder=4)

    creed = canvas.text(0.50, 0.030, "Prepare. Let price tell you. Patience compounds.", color="#dcebf0", fontsize=10.5, fontfamily="serif", alpha=0.46, ha="center", va="center", zorder=5)
    creed.set_path_effects([pe.withStroke(linewidth=2.0, foreground="#07141b", alpha=0.36)])

    def curved_arrow(start, end, rad):
        canvas.add_patch(FancyArrowPatch(start, end, transform=canvas.transAxes, arrowstyle="-|>", mutation_scale=20, connectionstyle=f"arc3,rad={rad}", color="#35ddea", linewidth=1.12, linestyle=(0, (1.5, 2.6)), alpha=0.58, zorder=10))
        canvas.add_patch(Circle(start, 0.004, transform=canvas.transAxes, facecolor="#35ddea", edgecolor="none", alpha=0.64, zorder=10))

    if not teaching_mode:
        arrows = [
            ((0.121, 0.755), (0.245, 0.520), 0.32),
            ((0.312, 0.755), (0.385, 0.585), 0.10),
            ((0.498, 0.755), (0.507, 0.635), 0.02),
            ((0.688, 0.755), (0.685, 0.635), -0.06),
            ((0.875, 0.755), (0.720, 0.590), -0.28),
        ]
        for start, end, rad in arrows:
            curved_arrow(start, end, rad)

        footer = fig.add_axes([0.040, 0.100, 0.920, 0.105])
        footer.set_xlim(0, 1)
        footer.set_ylim(0, 1)
        footer.axis("off")
        footer.add_patch(FancyBboxPatch((0, 0.02), 1, 0.86, boxstyle="round,pad=0.012,rounding_size=0.040", facecolor="#143443", edgecolor="#5ee6f4", linewidth=0.65, alpha=0.42, zorder=1))
        footer.add_patch(FancyBboxPatch((0, 0.02), 1, 0.86, boxstyle="round,pad=0.012,rounding_size=0.040", facecolor="none", edgecolor="#77efff", linewidth=10, alpha=0.026, zorder=0))
        ft = footer.text(0.50, 0.665, "WHAT TO WATCH NEXT", color="#3bdff4", fontsize=18, fontweight="bold", ha="center", va="center", zorder=3)
        ft.set_path_effects([pe.withStroke(linewidth=3.0, foreground="#0b6878", alpha=0.44)])
        support_text = format_price(near_supports[0]) if near_supports else format_price(support_level)
        resistance_text = format_price(near_resistances[0]) if near_resistances else format_price(resistance_level)
        items = footer_items or [
            f"1. Reclaim {format_price(current_price)} \u2192 buyers step back in",
            f"2. Break {resistance_text} \u2192 next leg can start",
            f"3. Lose {support_text} \u2192 watch support reaction",
        ]
        column_widths = [25, 24, 23]
        for idx, (x_pos, item) in enumerate(zip([0.065, 0.385, 0.690], items)):
            wrapped = textwrap.wrap(str(item), width=column_widths[idx])[:3]
            if not wrapped:
                wrapped = [str(item)]
            y = 0.405 if len(wrapped) >= 3 else 0.355
            for line in wrapped:
                footer.text(x_pos, y, line, color="#dce7ef", fontsize=10.0, ha="left", va="center", zorder=3)
                y -= 0.145
            if idx < 2:
                footer.plot([x_pos + 0.292, x_pos + 0.292], [0.20, 0.50], color="#2dd4f0", linewidth=1.0, alpha=0.52, zorder=3)

        canvas.text(0.50, 0.062, "End of Snapshot  \u2022  Ready for Next Level", color="#a9b8c5", fontsize=10.7, alpha=0.75, ha="center", va="center", zorder=5)

    prefix = output_prefix or f"{symbol.replace('/', '_')}_poinkle_reference_"
    fd, path = tempfile.mkstemp(suffix=".png", prefix=prefix)
    os.close(fd)
    fig.savefig(path, dpi=100, facecolor=fig.get_facecolor(), bbox_inches=None, pad_inches=0)
    plt.close(fig)
    return path
