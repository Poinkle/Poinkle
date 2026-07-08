EXPLANATION_REGISTRY = {
    "rsi": {
        "beginner": (
            "RSI is like a speedometer for how fast a coin's price has been moving. "
            "It runs from 0 to 100. Above 70 means it might be moving too fast up "
            "(overbought — could be due for a rest). Below 30 means it's been beaten "
            "down hard (oversold — could be due for a bounce). It doesn't tell you "
            "what WILL happen — just whether things are stretched."
        ),
        "experienced": (
            "RSI (14) — momentum oscillator, 0-100. >70 overbought, <30 oversold. "
            "Watch for divergences and cross-backs, not just absolute levels."
        ),
    },
    "ema": {
        "beginner": (
            "An EMA is just an average price over time, but one that pays more "
            "attention to recent days. Think of it as the trend's 'center of gravity.' "
            "When price is above it, the trend's leaning up. When a shorter EMA "
            "(like the 21) crosses above a longer one (the 55), it's often an early "
            "sign momentum is turning upward."
        ),
        "experienced": (
            "EMA — exponentially weighted moving average (recent prices weighted "
            "heavier). 21/55 cross used as a momentum/trend signal. Above = bullish "
            "lean, below = bearish lean."
        ),
    },
    "volume_spike": {
        "beginner": (
            "Volume is how many people are buying and selling. A volume spike means "
            "way more activity than usual — like a quiet street suddenly getting "
            "crowded. It tells you something got people's attention. Big moves backed "
            "by big volume tend to mean more than quiet ones."
        ),
        "experienced": (
            "Volume spike — current volume well above its average (e.g. >=2x). "
            "Confirms conviction behind a move; low-volume moves are less reliable."
        ),
    },
    "support": {
        "beginner": (
            "Support is a price floor — a level where buyers have stepped in before, "
            "so the price tends to bounce up off it. Watching support tells you where "
            "buyers might defend again."
        ),
        "experienced": (
            "Support — price level where demand has previously absorbed selling. "
            "Watch for holds vs breaks and retests."
        ),
    },
    "resistance": {
        "beginner": (
            "Resistance is the ceiling — a level where sellers show up and the price "
            "struggles to break above. Watching resistance tells you where the price "
            "has to fight through to keep climbing."
        ),
        "experienced": (
            "Resistance — price level where supply has previously capped advances. "
            "Break-and-hold above flips it to support."
        ),
    },
    "breakout": {
        "beginner": (
            "A breakout is when the price finally pushes through the ceiling "
            "(resistance) — like breaking out of a box it's been stuck in. It can "
            "signal a new move starting. But patience compounds — a breakout that "
            "HOLDS matters more than one that just pokes through for a second."
        ),
        "experienced": (
            "Breakout — price closes beyond a defined level. Quality depends on "
            "volume, follow-through, and confirmation (hold) rather than the initial "
            "poke."
        ),
    },
    "breakdown": {
        "beginner": (
            "A breakdown is the opposite of a breakout — when the price falls through "
            "the floor (support) instead of bouncing off it. It can signal weakness. "
            "Same rule applies: a breakdown that holds below the level matters more "
            "than a quick dip."
        ),
        "experienced": (
            "Breakdown — price closes below a support level. Confirm with "
            "follow-through/volume; watch for failed breakdowns (reclaim)."
        ),
    },
    "confluence": {
        "beginner": (
            "Confluence just means 'more than one thing agreeing at the same time.' "
            "When several signals line up together — say the trend, the volume, and "
            "the RSI all pointing the same way — it's usually a stronger sign than "
            "any single one alone. More agreement, more conviction."
        ),
        "experienced": (
            "Confluence — multiple independent signals aligning (e.g. RSI + volume + "
            "EMA + level). Higher confluence = higher-conviction setup."
        ),
    },
    "trend": {
        "beginner": (
            "The trend is just the overall direction the price has been heading — up, "
            "down, or sideways. 'The trend is your friend' is an old saying because "
            "going WITH the direction is usually safer than fighting it. Poinkle looks "
            "at trend first, before anything else."
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
