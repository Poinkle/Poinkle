EXPLANATION_REGISTRY = {
    "rsi": {
        "beginner": (
            "A strength meter for recent price moves, scored 0 to 100. It compares "
            "how big the recent gains have been versus the recent losses. Above 70 "
            "means buyers have been in control (overbought — the price may be "
            "stretched and could slow down). Below 30 means sellers have been in "
            "control (oversold — the price may be beaten down and could bounce). "
            "Critical truth: RSI measures strength — it does NOT predict what happens "
            "next. In a strong trend it can stay high or low for a long time — so it's "
            "one clue, not a crystal ball."
        ),
        "experienced": (
            "RSI (14) — momentum oscillator, 0-100. >70 overbought, <30 oversold. "
            "Watch for divergences and cross-backs, not just absolute levels."
        ),
    },
    "ema": {
        "beginner": (
            "A line that tracks the average price over a recent period, but pays more "
            "attention to recent prices — so it reacts faster than a plain average. "
            "Poinkle uses the EMA 21 (shorter-term) and EMA 55 (medium-term). When "
            "price is above them the trend's leaning up; below, it's leaning down. "
            "Honest: it helps make the trend easier to see — it doesn't predict the "
            "future."
        ),
        "experienced": (
            "EMA — exponentially weighted moving average (recent prices weighted "
            "heavier). 21/55 cross used as a momentum/trend signal. Above = bullish "
            "lean, below = bearish lean."
        ),
    },
    "volume_spike": {
        "beginner": (
            "How many people are buying and selling in a given period — the activity "
            "behind a price move. Think a few people whispering vs. a packed stadium "
            "cheering. Higher volume means more people and money are behind the move, "
            "so it tends to matter more. A move with strong volume is usually more "
            "believable than the same move with weak volume."
        ),
        "experienced": (
            "Volume spike — current volume well above its average (e.g. >=2x). "
            "Confirms conviction behind a move; low-volume moves are less reliable."
        ),
    },
    "support": {
        "beginner": (
            "A price level where the asset tends to stop falling and bounce back up — "
            "like a floor. It holds because enough people decide it's a good price to "
            "buy. Honest limit: it's not a magic wall. Strong enough selling can push "
            "right through it."
        ),
        "experienced": (
            "Support — price level where demand has previously absorbed selling. "
            "Watch for holds vs breaks and retests."
        ),
    },
    "resistance": {
        "beginner": (
            "A price level where the asset tends to stop rising and get pushed back "
            "down — like a ceiling. Many people decide it's a good price to sell. "
            "Honest limit: not guaranteed. Enough buying pressure can break through "
            "it."
        ),
        "experienced": (
            "Resistance — price level where supply has previously capped advances. "
            "Break-and-hold above flips it to support."
        ),
    },
    "breakout": {
        "beginner": (
            "When price moves above a resistance level and stays there — often with "
            "more people buying. Like finally breaking through the ceiling. It can "
            "signal a stronger move up. Caution: sometimes it looks like a breakout, "
            "then quickly falls back below the level. A breakout that stays above "
            "means more than one that quickly falls back — patience compounds."
        ),
        "experienced": (
            "Breakout — price closes beyond a defined level. Quality depends on "
            "volume, follow-through, and confirmation (hold) rather than the initial "
            "poke."
        ),
    },
    "breakdown": {
        "beginner": (
            "When price falls below a support level and stays below it — like the "
            "floor giving way. It can signal a stronger move down. Caution: same as "
            "breakouts — wait to see if it stays below the level before trusting it."
        ),
        "experienced": (
            "Breakdown — price closes below a support level. Confirm with "
            "follow-through/volume; watch for failed breakdowns (reclaim)."
        ),
    },
    "confluence": {
        "beginner": (
            "When several things line up and point the same way — like a few friends "
            "all agreeing on the best route. Example: price sitting at support, plus "
            "the EMA pointing the same direction, plus RSI pointing the same way. "
            "More agreement gives you a better chance of being right — though still "
            "never a guarantee. Confluence is what turns separate observations into a "
            "clearer picture."
        ),
        "experienced": (
            "Confluence — multiple independent signals aligning (e.g. RSI + volume + "
            "EMA + level). Higher confluence = higher-conviction setup."
        ),
    },
    "trend": {
        "beginner": (
            "The overall direction the price is moving — like the flow of a river. It "
            "can go up (generally climbing), down (generally falling), or sideways "
            "(drifting with no clear direction). It doesn't tell you what WILL happen "
            "next — it just shows what the market is doing right now. Most decisions "
            "start here: is the river flowing up, down, or nowhere?"
        ),
        "experienced": (
            "Trend — prevailing directional bias (via structure and EMAs). Trade with "
            "it unless there's a clear, confirmed reversal."
        ),
    },
}


EXPLANATION_ALIASES = {
    "relative strength": "rsi",
    "relative strength index": "rsi",
    "rsi": "rsi",
    "ema": "ema",
    "exponential moving average": "ema",
    "moving average": "ema",
    "volume": "volume_spike",
    "volume spike": "volume_spike",
    "volume_spike": "volume_spike",
    "support": "support",
    "floor": "support",
    "resistance": "resistance",
    "ceiling": "resistance",
    "breakout": "breakout",
    "break out": "breakout",
    "breakdown": "breakdown",
    "break down": "breakdown",
    "confluence": "confluence",
    "confirmation": "confluence",
    "trend": "trend",
    "market trend": "trend",
}


CONCEPT_DISPLAY_NAMES = {
    "rsi": "RSI",
    "ema": "EMA",
    "volume_spike": "Volume Spike",
    "support": "Support",
    "resistance": "Resistance",
    "breakout": "Breakout",
    "breakdown": "Breakdown",
    "confluence": "Confluence",
    "trend": "Trend",
}


def available_concepts():
    return tuple(EXPLANATION_REGISTRY.keys())


def normalize_concept_key(concept):
    clean = " ".join(str(concept or "").strip().lower().replace("-", " ").split())
    return EXPLANATION_ALIASES.get(clean)


def explain_concept(concept_key, skill_level=None):
    resolved_key = normalize_concept_key(concept_key)
    if not resolved_key:
        return None

    entry = EXPLANATION_REGISTRY.get(resolved_key)
    if not entry:
        return None

    level = skill_level if skill_level in entry else "experienced"
    return entry.get(level) or entry.get("experienced") or entry.get("beginner")


def concept_display_name(concept_key):
    resolved_key = normalize_concept_key(concept_key) or concept_key
    return CONCEPT_DISPLAY_NAMES.get(resolved_key, str(resolved_key).replace("_", " ").title())
