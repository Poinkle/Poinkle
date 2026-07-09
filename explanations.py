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
    "confirmation": {
        "beginner": (
            "When price doesn't just touch a level but actually finishes the time "
            "period beyond it — showing the move is more likely to be real, not just a "
            "quick poke. Think of a breakout: price might jump above resistance for a "
            "second, then fall right back. Waiting for confirmation means waiting for "
            "the full period to finish above the level before trusting it. Poinkle "
            "only uses confirmed breaks for this reason — patience compounds. The "
            "tradeoff: you get in at a slightly worse price, but with a better chance "
            "the move is real."
        ),
        "experienced": (
            "Confirmation — a candle CLOSE beyond a level (not an intraday wick). "
            "Filters fakeouts by requiring the period to finish past the level. "
            "Trades off entry price for higher reliability; optional retest adds "
            "further validation."
        ),
    },
    "candle": {
        "beginner": (
            "Each candle on the chart is one chunk of time — on Poinkle's daily "
            "charts, one candle = one day. It shows four things: where price started, "
            "where it finished, and the highest and lowest it reached during that "
            "time. The thick middle part (called the body) shows the start-to-finish "
            "range. The thin lines above and below it (called wicks) show the highest "
            "and lowest points reached. Green usually means price finished higher "
            "than it started; red means it finished lower. A candle is just a simple "
            "picture of what happened in that time period."
        ),
        "experienced": (
            "Candlestick — OHLC for one period. Body = open-to-close range; "
            "wicks/shadows = the high and low extremes. Color shows close vs open "
            "(green up, red down). Body size and wick length convey conviction and "
            "rejection."
        ),
    },
    "range": {
        "beginner": (
            "The zone between a recent high and a recent low — the \"box\" price has "
            "been bouncing around in. When price is stuck between a floor (support) "
            "and a ceiling (resistance) with no clear direction, it's moving sideways "
            "in that box. Poinkle shows you where price sits in its box — near the "
            "top, middle, or bottom. This helps you see if there's room to move, or "
            "if price is bumping against an edge."
        ),
        "experienced": (
            "Range — price bounded between horizontal support and resistance, no "
            "directional trend. Range position (top/mid/bottom) frames risk/reward; "
            "edges are where breaks or rejections tend to occur."
        ),
    },
    "key_level": {
        "beginner": (
            "A price that matters — a spot where the market has reacted before, so "
            "it's worth paying attention if price returns there. Support and "
            "resistance are both key levels (a floor and a ceiling). Poinkle marks "
            "these so you know the prices worth watching. Honest limit: key levels "
            "are zones of interest, not magic lines. Price can and does break through "
            "them — they show you where the important battles happen, not what the "
            "outcome will be."
        ),
        "experienced": (
            "Key level — a price with a history of reaction (support/resistance, "
            "prior swing high/low, range edge). Zones, not exact lines. Watch for "
            "holds, breaks, and retests rather than assuming a bounce."
        ),
    },
    "liquidity": {
        "beginner": (
            "How easily an asset can be bought or sold without moving the price much. "
            "High liquidity means lots of buyers and sellers, so trades happen "
            "smoothly. Low liquidity means fewer buyers and sellers, so price can "
            "jump around more on smaller trades. Think a busy marketplace (easy to "
            "buy and sell at fair prices) versus a quiet one (harder to buy or sell "
            "without changing the price). Coins with lower liquidity tend to have "
            "bigger, faster price swings."
        ),
        "experienced": (
            "Liquidity — depth of available buy/sell orders. High liquidity = tight "
            "spreads, low slippage, smoother fills. Low liquidity = wider spreads, "
            "more slippage, sharper moves on smaller size."
        ),
    },
    "market_structure": {
        "beginner": (
            "The overall shape of how price rises and falls over time. When each high "
            "is higher than the last and each dip is higher too (higher highs, higher "
            "lows), the structure is trending up. The reverse (lower highs, lower "
            "lows) is trending down. When it's neither, price is moving sideways. "
            "It's the big picture underneath the day-to-day price changes. Honest "
            "limit: structure describes what's happened, not what must happen next — "
            "it can shift."
        ),
        "experienced": (
            "Market structure — the sequence of swing highs/lows. Higher highs + "
            "higher lows = uptrend; lower highs + lower lows = downtrend; otherwise "
            "ranging. Structure breaks (a failed HH/HL sequence) flag potential "
            "regime change."
        ),
    },
    "accumulation": {
        "beginner": (
            "When buyers are quietly stepping in over time — often while price moves "
            "sideways or dips — slowly building their investment instead of buying all "
            "at once. Think of it as slowly filling a basket while prices are low, "
            "rather than grabbing everything in one rush. It's the heart of "
            "\"patience compounds\": small, steady buys at good levels. Honest limit: "
            "accumulation is a strategy, not a guarantee — the price can still fall "
            "further, which is why you never buy all at once."
        ),
        "experienced": (
            "Accumulation — building a position gradually over time/levels rather "
            "than a single entry. Often occurs during sideways/basing action. Scaling "
            "in manages timing risk; size discipline matters since price can extend "
            "lower."
        ),
    },
    "retest": {
        "beginner": (
            "After price breaks through a level, it often comes back to test that "
            "level again before continuing — like checking if the door you just "
            "walked through still holds. If a price that used to act as a ceiling now "
            "acts as a floor (price breaks above, dips back, and holds), that's a "
            "healthy retest and a stronger sign the breakout is holding. Honest "
            "limit: not every retest holds — sometimes price falls back through, "
            "which tells you the break may have been weak."
        ),
        "experienced": (
            "Retest — price returns to a broken level to test it as new "
            "support/resistance (role reversal). A holding retest strengthens the "
            "break and offers a cleaner entry with defined risk; a failed retest "
            "signals a weak/false break."
        ),
    },
    "follow_through": {
        "beginner": (
            "What happens after a move or a break — does price keep going in that "
            "direction, or fade out? Strong follow-through (continued movement, often "
            "with steady volume) suggests the move had more buying behind it. Weak "
            "follow-through suggests it may have been a false start. Honest limit: "
            "it's something you see after the move has already started — you're "
            "reading whether a move stuck, not predicting that it will."
        ),
        "experienced": (
            "Follow-through — continuation after an initial move/break, ideally with "
            "sustained volume. Strong follow-through validates the move; weak/absent "
            "follow-through warns of a failed or exhausted push."
        ),
    },
    "trade_plan": {
        "beginner": (
            "Your decided-in-advance answer to three questions before you ever buy: "
            "where you'll buy (your entry), where you'll sell if things go well (your "
            "target), and where you'll get out if they don't (your stop). Having a "
            "plan before you act keeps emotion out of the decision. Honest limit: a "
            "plan doesn't make you right — it makes you disciplined. The point isn't "
            "to win every time; it's to never be caught without a decision."
        ),
        "experienced": (
            "Trade plan — predefined entry, target(s), and stop (invalidation), with "
            "position size set by the risk between entry and stop. Removes "
            "in-the-moment emotion; enforces consistent risk/reward and discipline."
        ),
    },
    "market_score": {
        "beginner": (
            "A single 0-100 rating of how strong a coin's overall setup looks "
            "right now, shown as a score out of 10. Higher means more of the "
            "signals are lining up favorably — a quick way to compare coins at a "
            "glance. Honest limit: it describes the moment, not the future. A high "
            "score is a starting point for a closer look, never a reason to buy on "
            "its own."
        ),
        "experienced": (
            "Market Score — 0-100 overall technical confidence from market "
            "structure inputs, displayed as X.X/10. A ranking aid, not a trigger."
        ),
    },
    "setup_quality": {
        "beginner": (
            "A simple letter grade — A+ down to F — for how clean a trade setup "
            "looks. It's just the Break Strength Score written as a letter instead "
            "of a number: an A means the signs are strong, an F means steer clear. "
            "Honest limit: a high grade means a better-looking setup — nothing "
            "more. The cleanest-looking setups still lose sometimes."
        ),
        "experienced": (
            "Setup Quality — the A+-F letter grade mapped directly from the "
            "(adjusted) Break Strength Score. Not a separate model."
        ),
    },
    "break_strength_score": {
        "beginner": (
            "A 0-100 score for how convincing a breakout or breakdown really is. "
            "It looks at things like volume, momentum, and how firmly price closed "
            "past the level. Higher means more signs the move is real instead of a "
            "quick fake-out. Honest limit: a high score tilts the odds in your "
            "favor — it can't remove the risk. Convincing breaks fail all the time."
        ),
        "experienced": (
            "Break Strength Score — 0-100 from volume, RSI/EMA alignment, close "
            "strength beyond level, retest quality, and room to target; capped "
            "down for poor location or weak momentum."
        ),
    },
    "patience_grade": {
        "beginner": (
            "A letter grade — A to F — for how well a coin fits patiently "
            "building up a position right now, a little at a time, instead of "
            "buying all at once. It weighs things like how close price is to "
            "support, the overall trend, and volume. An A means conditions favor "
            "waiting and adding slowly; an F means sit on your hands. Honest "
            "limit: it grades the conditions, not what happens next — and even an "
            "A is never a reason to go all in. Only ever swing a portion."
        ),
        "experienced": (
            "Patience Grade — A-F accumulation-fit grade (support proximity, trend "
            "bias, RSI zone, volume, market structure). Distinct from the "
            "patience_score proximity metric."
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
    "volumespike": "volume_spike",
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
    "trend": "trend",
    "market trend": "trend",
    "confirmation": "confirmation",
    "confirmed": "confirmation",
    "confirm": "confirmation",
    "confirmed break": "confirmation",
    "candle": "candle",
    "candlestick": "candle",
    "candles": "candle",
    "body": "candle",
    "wick": "candle",
    "wicks": "candle",
    "range": "range",
    "range bound": "range",
    "trading range": "range",
    "box": "range",
    "key_level": "key_level",
    "key level": "key_level",
    "keylevel": "key_level",
    "key levels": "key_level",
    "level": "key_level",
    "levels": "key_level",
    "zone": "key_level",
    "zones": "key_level",
    "liquidity": "liquidity",
    "liquid": "liquidity",
    "illiquid": "liquidity",
    "market_structure": "market_structure",
    "market structure": "market_structure",
    "marketstructure": "market_structure",
    "structure": "market_structure",
    "higher highs": "market_structure",
    "lower lows": "market_structure",
    "accumulation": "accumulation",
    "accumulate": "accumulation",
    "accumulating": "accumulation",
    "accumulation zone": "accumulation",
    "retest": "retest",
    "re-test": "retest",
    "retesting": "retest",
    "retested": "retest",
    "follow_through": "follow_through",
    "follow through": "follow_through",
    "followthrough": "follow_through",
    "follow-through": "follow_through",
    "trade_plan": "trade_plan",
    "trade plan": "trade_plan",
    "tradeplan": "trade_plan",
    "plan": "trade_plan",
    "entry": "trade_plan",
    "target": "trade_plan",
    "stop": "trade_plan",
    "stop loss": "trade_plan",
    "exit": "trade_plan",
    "market score": "market_score",
    "marketscore": "market_score",
    "setup quality": "setup_quality",
    "setupquality": "setup_quality",
    "quality": "setup_quality",
    "break strength": "break_strength_score",
    "break strength score": "break_strength_score",
    "breakstrength": "break_strength_score",
    "break score": "break_strength_score",
    "patience grade": "patience_grade",
    "patiencegrade": "patience_grade",
    "patience": "patience_grade",
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
    "confirmation": "Confirmation",
    "candle": "Candle",
    "range": "Range",
    "key_level": "Key Level",
    "liquidity": "Liquidity",
    "market_structure": "Market Structure",
    "accumulation": "Accumulation",
    "retest": "Retest",
    "follow_through": "Follow-Through",
    "trade_plan": "Trade Plan",
    "market_score": "Market Score",
    "setup_quality": "Setup Quality",
    "break_strength_score": "Break Strength Score",
    "patience_grade": "Patience Grade",
}


def available_concepts():
    return tuple(EXPLANATION_REGISTRY.keys())


def normalize_concept_key(concept):
    clean = " ".join(str(concept or "").strip().lower().replace("-", " ").split())
    normalized_aliases = {
        " ".join(str(alias).strip().lower().replace("-", " ").split()): key
        for alias, key in EXPLANATION_ALIASES.items()
    }
    if clean in normalized_aliases:
        return normalized_aliases[clean]

    registry_key = clean.replace(" ", "_")
    if registry_key in EXPLANATION_REGISTRY:
        return registry_key

    return None


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
