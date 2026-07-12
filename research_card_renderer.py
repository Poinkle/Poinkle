import tempfile
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import image as mpimg
from matplotlib.patches import FancyBboxPatch


WIDTH = 1080
HEIGHT = 1350
DPI = 100

BACKGROUND_TOP = "#06141d"
BACKGROUND_BOTTOM = "#082a37"
PANEL = "#0f2230"
PANEL_EDGE = "#1f9fb1"
TEXT = "#e5edf7"
MUTED = "#91a1b5"
CYAN = "#38dff2"
GOLD = "#facc15"
WHITE = "#f8fafc"

CARD_LEFT = 0.08
CARD_RIGHT = 0.92
TITLE_Y = 0.845
TITLE_RULE_Y = 0.805
HEADLINE_Y = 0.745
BLOCK_GAP = 0.026
HEADLINE_LINE_GAP = 0.058
BODY_FONT_SIZE = 19
BODY_WRAP_WIDTH = 60
NOTE_WRAP_WIDTH = 62
BODY_LINE_GAP = 0.036
NOTE_LINE_GAP = 0.032
DETAIL_BOX_Y = 0.15
DETAIL_BOX_HEIGHT = 0.18
DETAIL_BOX_TOP = DETAIL_BOX_Y + DETAIL_BOX_HEIGHT
DETAIL_SAFE_TOP = DETAIL_BOX_TOP + 0.005
DETAIL_LINE_GAP = 0.029
FOOTER_RULE_Y = 0.095


def wrap_lines(text, width):
    clean = " ".join(str(text or "").split())
    if not clean:
        return []
    return textwrap.wrap(clean, width=width)


def draw_background(ax):
    top = np.array([int(BACKGROUND_TOP[i : i + 2], 16) for i in (1, 3, 5)]) / 255
    bottom = np.array([int(BACKGROUND_BOTTOM[i : i + 2], 16) for i in (1, 3, 5)]) / 255
    gradient = np.linspace(0, 1, HEIGHT)[:, None]
    colors = top * (1 - gradient) + bottom * gradient
    image = np.repeat(colors[:, None, :], WIDTH, axis=1)
    ax.imshow(image, extent=[0, 1, 0, 1], origin="lower", aspect="auto")
    frame = FancyBboxPatch(
        (0.035, 0.035),
        0.93,
        0.93,
        boxstyle="round,pad=0.006,rounding_size=0.018",
        linewidth=1.8,
        edgecolor="#185f70",
        facecolor=PANEL,
        alpha=0.78,
    )
    ax.add_patch(frame)


def draw_logo(ax, logo_path):
    ax.text(
        0.09,
        0.92,
        "Poinkle",
        color=CYAN,
        fontsize=18,
        fontweight="bold",
        ha="left",
        va="center",
    )
    if not logo_path or not Path(logo_path).exists():
        return
    try:
        logo = mpimg.imread(logo_path)
        ax.imshow(logo, extent=[0.055, 0.085, 0.902, 0.94], aspect="auto", zorder=3)
    except Exception:
        return


def draw_wrapped_text(
    ax,
    lines,
    x,
    y,
    width,
    fontsize,
    color,
    weight="normal",
    line_gap=0.033,
    min_y=None,
):
    truncated = False
    for item in lines or []:
        wrapped = wrap_lines(item, width)
        if not wrapped:
            y -= line_gap
            continue
        for line in wrapped:
            if min_y is not None and y - line_gap < min_y:
                truncated = True
                break
            ax.text(
                x,
                y,
                line,
                color=color,
                fontsize=fontsize,
                fontweight=weight,
                ha="left",
                va="top",
                linespacing=1.15,
            )
            y -= line_gap
        if truncated:
            break
    return y, truncated


def draw_detail_box(ax, details):
    if not details:
        return
    box = FancyBboxPatch(
        (CARD_LEFT, DETAIL_BOX_Y),
        0.84,
        DETAIL_BOX_HEIGHT,
        boxstyle="round,pad=0.018,rounding_size=0.02",
        linewidth=1.0,
        edgecolor="#1f6474",
        facecolor="#071924",
        alpha=0.92,
    )
    ax.add_patch(box)
    y = DETAIL_BOX_Y + DETAIL_BOX_HEIGHT - 0.045
    for detail in details[:5]:
        ax.text(
            0.105,
            y,
            str(detail),
            color=MUTED,
            fontsize=16,
            ha="left",
            va="top",
        )
        y -= DETAIL_LINE_GAP


def render_research_card(card, page_number, page_count, output_path, logo_path=None):
    fig = plt.figure(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    draw_background(ax)
    draw_logo(ax, logo_path)

    ax.text(
        CARD_RIGHT,
        0.92,
        f"{page_number}/{page_count}",
        color=MUTED,
        fontsize=15,
        ha="right",
        va="center",
    )
    ax.text(
        CARD_LEFT,
        TITLE_Y,
        card.get("title", "Research"),
        color=GOLD,
        fontsize=19,
        fontweight="bold",
        ha="left",
        va="top",
    )
    ax.plot([CARD_LEFT, CARD_RIGHT], [TITLE_RULE_Y, TITLE_RULE_Y], color=CYAN, linewidth=1.2, alpha=0.7)

    headline = card.get("headline", "")
    y, _ = draw_wrapped_text(
        ax,
        [headline],
        CARD_LEFT,
        HEADLINE_Y,
        width=28,
        fontsize=34,
        color=WHITE,
        weight="bold",
        line_gap=HEADLINE_LINE_GAP,
        min_y=DETAIL_SAFE_TOP,
    )

    y -= BLOCK_GAP
    y, body_truncated = draw_wrapped_text(
        ax,
        card.get("body", []),
        CARD_LEFT,
        y,
        width=BODY_WRAP_WIDTH,
        fontsize=BODY_FONT_SIZE,
        color=TEXT,
        line_gap=BODY_LINE_GAP,
        min_y=DETAIL_SAFE_TOP,
    )

    notes = card.get("notes", [])
    notes_truncated = False
    if notes and y - BLOCK_GAP > DETAIL_SAFE_TOP:
        y -= BLOCK_GAP
        y, notes_truncated = draw_wrapped_text(
            ax,
            notes,
            CARD_LEFT,
            y,
            width=NOTE_WRAP_WIDTH,
            fontsize=17,
            color=MUTED,
            line_gap=NOTE_LINE_GAP,
            min_y=DETAIL_SAFE_TOP,
        )
    if body_truncated or notes_truncated:
        ax.text(
            CARD_LEFT,
            DETAIL_SAFE_TOP + 0.012,
            "Extra context trimmed to keep the card readable.",
            color=MUTED,
            fontsize=15,
            ha="left",
            va="bottom",
        )

    draw_detail_box(ax, card.get("details", []))
    ax.plot([CARD_LEFT, CARD_RIGHT], [FOOTER_RULE_Y, FOOTER_RULE_Y], color="#1f6474", linewidth=1.0, alpha=0.8)
    ax.text(
        0.5,
        0.065,
        "Patience compounds",
        color=MUTED,
        fontsize=14,
        ha="center",
        va="center",
    )

    fig.savefig(output_path, dpi=DPI, facecolor=BACKGROUND_TOP)
    plt.close(fig)


def render_research_cards(cards, logo_path=None, output_dir=None):
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="poinkle_research_cards_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    cards = list(cards or [])
    paths = []
    for index, card in enumerate(cards, start=1):
        path = output_dir / f"research_card_{index}_of_{len(cards)}.png"
        render_research_card(card, index, len(cards), path, logo_path=logo_path)
        paths.append(str(path))
    return paths
