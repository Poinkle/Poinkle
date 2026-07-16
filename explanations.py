EXPLANATION_REGISTRY = {
    "rsi": {
        "beginner": (
            "RSI is a reading, not a signal. It shows whether recent candles have "
            "been stretched toward buyers or sellers. Above 70 means price is "
            "extended; for a patient buyer, that is a caution reading, not a buy "
            "signal. Below 30 means price is stretched lower and worth looking at "
            "in context. RSI cannot fire an alert in Poinkle — structure fires, "
            "indicators confirm. Honest limit: RSI can stay high or low for a long "
            "time, so it never tells you what price will do next."
        ),
        "experienced": (
            "RSI (14) — momentum reading, 0-100. >70 is extended, <30 is oversold. "
            "It cannot fire an alert; it only adds context after structure is in "
            "play. Honest limit: extremes can persist during strong trends."
        ),
    },
    "ema": {
        "beginner": (
            "A line that tracks the average price over a recent period, but pays more "
            "attention to recent prices — so it reacts faster than a plain average. "
            "Poinkle uses EMAs to read trend context after price has reached a zone. "
            "EMA cannot fire an alert. It can only confirm or question what price "
            "already showed. Honest limit: a moving average smooths the past; it "
            "doesn't predict the next candle."
        ),
        "experienced": (
            "EMA — exponentially weighted moving average with recent prices weighted "
            "heavier. Poinkle uses it as trend context, not as the reason an alert "
            "sends. Honest limit: EMAs lag price and can whipsaw in chop."
        ),
    },
    "volume_spike": {
        "beginner": (
            "How many people are buying and selling in a given period — the activity "
            "behind a price move. Volume is neutral by nature: it shows participation, "
            "not direction. A spike on an up candle and a spike on a down candle mean "
            "different things because price gives the direction. Volume cannot fire "
            "an alert in Poinkle; it confirms what price is already doing. Honest "
            "limit: one loud candle can be a single large order, not lasting interest."
        ),
        "experienced": (
            "Volume spike — current volume well above its average, used as "
            "participation context only. Direction comes from price, not volume "
            "itself. Honest limit: volume confirms activity, not outcome."
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
            "Watch for holds vs breaks and retests. Honest limit: support is a zone "
            "of prior reaction, not a guaranteed floor."
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
            "Break-and-hold above can flip it to support. Honest limit: resistance "
            "is a zone, not a ceiling price must obey."
        ),
    },
    "double_top": {
        "beginner": (
            "<b>WHAT IT IS</b>\n"
            "A double top is where price fails at the same resistance level twice. "
            "It rises to a zone, gets turned back, returns to that same zone, and "
            "gets turned back again. Two failed attempts at one ceiling. The low "
            "between the two peaks is the NECKLINE.\n\n"
            "<b>WHAT CONFIRMS IT</b>\n"
            "Seeing two tops is not the pattern completing. The pattern completes "
            "only when price closes below the neckline — and by Poinkle's rule that "
            "means TWO closes, not one. One close below is an attempt. The second "
            "close that holds is confirmation. Until the neckline breaks with "
            "confirmation, it is two rejections being watched, not a completed "
            "pattern.\n\n"
            "<b>HONEST LIMIT</b>\n"
            "No pattern is guaranteed. Two tops can form and price can push through "
            "on a later attempt. A neckline can break and then reclaim. A double "
            "top describes what price has already done — twice turned back at one "
            "level — not what comes next. It is a shape worth watching, never a call."
        ),
        "experienced": (
            "<b>WHAT IT IS</b>\n"
            "A double top is where price fails at the same resistance level twice. "
            "It rises to a zone, gets turned back, returns to that same zone, and "
            "gets turned back again. Two failed attempts at one ceiling. The low "
            "between the two peaks is the NECKLINE.\n\n"
            "<b>WHAT CONFIRMS IT</b>\n"
            "Seeing two tops is not the pattern completing. The pattern completes "
            "only when price closes below the neckline — and by Poinkle's rule that "
            "means TWO closes, not one. One close below is an attempt. The second "
            "close that holds is confirmation. Until the neckline breaks with "
            "confirmation, it is two rejections being watched, not a completed "
            "pattern.\n\n"
            "<b>HONEST LIMIT</b>\n"
            "No pattern is guaranteed. Two tops can form and price can push through "
            "on a later attempt. A neckline can break and then reclaim. A double "
            "top describes what price has already done — twice turned back at one "
            "level — not what comes next. It is a shape worth watching, never a call."
        ),
    },
    "double_bottom": {
        "beginner": (
            "<b>WHAT IT IS</b>\n"
            "A double bottom is where price holds at the same support level twice. "
            "It falls to a zone, gets turned back up, returns to that same zone, "
            "and holds again. Two successful defenses of one floor. The high "
            "between the two lows is the NECKLINE.\n\n"
            "<b>WHAT CONFIRMS IT</b>\n"
            "Seeing two bottoms is not the pattern completing. The pattern "
            "completes only when price closes above the neckline — and by "
            "Poinkle's rule that means TWO closes, not one. One close above is an "
            "attempt. The second close that holds is confirmation. Until the "
            "neckline breaks with confirmation, it is two holds being watched, "
            "not a completed pattern.\n\n"
            "<b>HONEST LIMIT</b>\n"
            "No pattern is guaranteed. Two bottoms can form and price can break "
            "down through the floor on a later attempt. A neckline can break and "
            "then fail back below. A double bottom describes what price has "
            "already done — twice held at one level — not what comes next. It is "
            "a shape worth watching, never a call."
        ),
        "experienced": (
            "<b>WHAT IT IS</b>\n"
            "A double bottom is where price holds at the same support level twice. "
            "It falls to a zone, gets turned back up, returns to that same zone, "
            "and holds again. Two successful defenses of one floor. The high "
            "between the two lows is the NECKLINE.\n\n"
            "<b>WHAT CONFIRMS IT</b>\n"
            "Seeing two bottoms is not the pattern completing. The pattern "
            "completes only when price closes above the neckline — and by "
            "Poinkle's rule that means TWO closes, not one. One close above is an "
            "attempt. The second close that holds is confirmation. Until the "
            "neckline breaks with confirmation, it is two holds being watched, "
            "not a completed pattern.\n\n"
            "<b>HONEST LIMIT</b>\n"
            "No pattern is guaranteed. Two bottoms can form and price can break "
            "down through the floor on a later attempt. A neckline can break and "
            "then fail back below. A double bottom describes what price has "
            "already done — twice held at one level — not what comes next. It is "
            "a shape worth watching, never a call."
        ),
    },
    "neckline": {
        "beginner": (
            "<b>WHAT IT IS</b>\n"
            "The neckline is the level that decides whether a double top or double "
            "bottom completes. On a double top it is the low between the two peaks. "
            "On a double bottom it is the high between the two lows. It is the line "
            "price must close through for the pattern to count.\n\n"
            "<b>WHAT CONFIRMS IT</b>\n"
            "A neckline is not broken the moment price touches it. By Poinkle's "
            "rule, breaking it means TWO closes through it, not one. One close "
            "through is an attempt. The second close that holds is confirmation. "
            "Until then the neckline is a level being watched, not a level that "
            "has broken.\n\n"
            "<b>HONEST LIMIT</b>\n"
            "No level is guaranteed. A neckline can be closed through and then "
            "reclaimed, turning a break into a failed attempt. The neckline "
            "describes the line that matters for a pattern — it does not promise "
            "the pattern completes or that price keeps going after it breaks. It "
            "is a level worth watching, never a call."
        ),
        "experienced": (
            "<b>WHAT IT IS</b>\n"
            "The neckline is the level that decides whether a double top or double "
            "bottom completes. On a double top it is the low between the two peaks. "
            "On a double bottom it is the high between the two lows. It is the line "
            "price must close through for the pattern to count.\n\n"
            "<b>WHAT CONFIRMS IT</b>\n"
            "A neckline is not broken the moment price touches it. By Poinkle's "
            "rule, breaking it means TWO closes through it, not one. One close "
            "through is an attempt. The second close that holds is confirmation. "
            "Until then the neckline is a level being watched, not a level that "
            "has broken.\n\n"
            "<b>HONEST LIMIT</b>\n"
            "No level is guaranteed. A neckline can be closed through and then "
            "reclaimed, turning a break into a failed attempt. The neckline "
            "describes the line that matters for a pattern — it does not promise "
            "the pattern completes or that price keeps going after it breaks. It "
            "is a level worth watching, never a call."
        ),
    },
    "breakout": {
        "beginner": (
            "When price moves above a resistance level and stays there — often with "
            "more people buying. Like finally breaking through the ceiling. It can "
            "tell you price entered a new zone. Caution: sometimes it looks like a "
            "breakout, then quickly falls back below the zone. Honest limit: Poinkle "
            "waits for confirmation because one close can still fake out."
        ),
        "experienced": (
            "Breakout — price closes beyond a defined level. Quality depends on "
            "confirmation, volume, and follow-through rather than the initial poke. "
            "Honest limit: a confirmed breakout can still be reclaimed."
        ),
    },
    "breakdown": {
        "beginner": (
            "When price falls below a support level and stays below it — like the "
            "floor giving way. It tells you price entered a lower zone. Caution: same "
            "as breakouts — wait to see if it stays below the zone before trusting "
            "it. Honest limit: a breakdown can still be reclaimed."
        ),
        "experienced": (
            "Breakdown — price closes below a support level. Confirm with "
            "follow-through/volume; watch for failed breakdowns (reclaim). Honest "
            "limit: one close below a zone is an attempt, not confirmation."
        ),
    },
    "confluence": {
        "beginner": (
            "Confluence means structure fired first, then the readings agreed with "
            "it. In Poinkle, that means a confirmed zone break — two daily closes "
            "beyond a zone — plus context like 6h structure, EMA trend, or volume "
            "participation lining up. Indicators do not lead. Price is truth. "
            "Honest limit: agreement means there is more to inspect, not that the "
            "move will continue."
        ),
        "experienced": (
            "Confluence — confirmed structure plus confirming context. Post-inversion, "
            "2+ indicators agreeing is not enough to send an alert. Honest limit: "
            "confluence is noise control, not probability."
        ),
    },
    "dominance": {
        "beginner": (
            "<b>WHAT IT IS</b>\n"
            "Dominance = one coin's market cap divided by the total crypto market "
            "cap, as a percent. BTC.D is Bitcoin's share. USDT.D is Tether's share.\n\n"
            "<b>THE PART MOST PEOPLE MISS</b>\n"
            "It is a RATIO — one number built from two moving parts. It can rise "
            "two ways: Bitcoin's share grew, or everything else shrank around it. "
            "BTC.D rising can "
            "mean Bitcoin gained — or it can mean everything else fell harder. Same "
            "number. Different picture. The number alone cannot tell you which. The "
            "charts can.\n\n"
            "<b>WHAT USDT.D IS ACTUALLY SHOWING</b>\n"
            "Tether is a stablecoin — it does not move with the market. Its share of "
            "the pie grows when money sits in it instead of in coins. Rising USDT.D "
            "= more capital parked, not deployed. Falling USDT.D = capital leaving "
            "the sidelines. It is a measure of WHERE MONEY IS SITTING, not a forecast.\n\n"
            "<b>HONEST LIMITS</b>\n"
            "- Dominance describes the market's shape right now. It does not predict "
            "the next move.\n"
            "- A single day's reading is noise. Structure on any chart needs "
            "confirmation before it means anything — one close is an attempt, two "
            "is confirmation. The same discipline applies here.\n"
            "- Poinkle currently shows you the CURRENT number only, not its trend. "
            "Reading dominance properly means reading its chart over time — go look "
            "at it yourself."
        ),
        "experienced": (
            "<b>WHAT IT IS</b>\n"
            "Dominance = one coin's market cap divided by the total crypto market "
            "cap, as a percent. BTC.D is Bitcoin's share. USDT.D is Tether's share.\n\n"
            "<b>THE PART MOST PEOPLE MISS</b>\n"
            "It is a RATIO — one number built from two moving parts. It can rise "
            "two ways: Bitcoin's share grew, or everything else shrank around it. "
            "BTC.D rising can "
            "mean Bitcoin gained — or it can mean everything else fell harder. Same "
            "number. Different picture. The number alone cannot tell you which. The "
            "charts can.\n\n"
            "<b>WHAT USDT.D IS ACTUALLY SHOWING</b>\n"
            "Tether is a stablecoin — it does not move with the market. Its share of "
            "the pie grows when money sits in it instead of in coins. Rising USDT.D "
            "= more capital parked, not deployed. Falling USDT.D = capital leaving "
            "the sidelines. It is a measure of WHERE MONEY IS SITTING, not a forecast.\n\n"
            "<b>HONEST LIMITS</b>\n"
            "- Dominance describes the market's shape right now. It does not predict "
            "the next move.\n"
            "- A single day's reading is noise. Structure on any chart needs "
            "confirmation before it means anything — one close is an attempt, two "
            "is confirmation. The same discipline applies here.\n"
            "- Poinkle currently shows you the CURRENT number only, not its trend. "
            "Reading dominance properly means reading its chart over time — go look "
            "at it yourself."
        ),
    },
    "trend": {
        "beginner": (
            "The overall direction the price is moving — like the flow of a river. It "
            "can go up (generally climbing), down (generally falling), or sideways "
            "(drifting with no clear direction). It doesn't tell you what WILL happen "
            "next — it just shows what the market is doing right now. Most decisions "
            "start here: is the river flowing up, down, or nowhere? Honest limit: "
            "trend is a read of the current path, not a promise it continues."
        ),
        "experienced": (
            "Trend — prevailing directional bias (via structure and EMAs). Trade with "
            "it unless there's a clear, confirmed reversal. Honest limit: trend is "
            "descriptive; it can change."
        ),
    },
    "confirmation": {
        "beginner": (
            "<b>Real breakout or fakeout?</b>\n\n"
            "A price break is not an event. A price break that HOLDS is an event.\n\n"
            "One daily close beyond a zone is an ATTEMPT. Two consecutive daily "
            "closes beyond it is CONFIRMATION.\n\n"
            "A fakeout is a break that never got its second close. Price pokes "
            "through, everyone reacts, and it closes back inside. That's not a "
            "signal failing — that's a signal that never happened.\n\n"
            "This is why Poinkle waits. It would rather be late than wrong.\n\n"
            "Honest limit: even a confirmed break can fail. Two closes raises the "
            "odds it was real. It does not make it certain."
        ),
        "experienced": (
            "<b>Real breakout or fakeout?</b>\n\n"
            "A price break is not an event. A price break that HOLDS is an event.\n\n"
            "One daily close beyond a zone is an ATTEMPT. Two consecutive daily "
            "closes beyond it is CONFIRMATION.\n\n"
            "A fakeout is a break that never got its second close. Price pokes "
            "through, everyone reacts, and it closes back inside. That's not a "
            "signal failing — that's a signal that never happened.\n\n"
            "This is why Poinkle waits. It would rather be late than wrong.\n\n"
            "Honest limit: even a confirmed break can fail. Two closes raises the "
            "odds it was real. It does not make it certain."
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
            "picture of what happened in that time period. Honest limit: one candle "
            "never tells the whole story."
        ),
        "experienced": (
            "Candlestick — OHLC for one period. Body = open-to-close range; "
            "wicks/shadows = the high and low extremes. Color shows close vs open "
            "(green up, red down). Honest limit: one candle is context, not a verdict."
        ),
    },
    "range": {
        "beginner": (
            "The zone between a recent high and a recent low — the \"box\" price has "
            "been bouncing around in. When price is stuck between a floor (support) "
            "and a ceiling (resistance) with no clear direction, it's moving sideways "
            "in that box. Poinkle shows you where price sits in its box — near the "
            "top, middle, or bottom. This helps you see if there's room to move, or "
            "if price is bumping against an edge. Honest limit: a range is current "
            "context; price can leave it."
        ),
        "experienced": (
            "Range — price bounded between horizontal support and resistance, no "
            "directional trend. Range position (top/mid/bottom) frames risk/reward; "
            "edges are where breaks or rejections tend to occur. Honest limit: ranges "
            "shift as new candles print."
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
            "holds, breaks, and retests rather than assuming a bounce. Honest limit: "
            "wicks fake out."
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
            "bigger, faster price swings. Honest limit: liquidity changes by venue "
            "and by time of day, so it is never a permanent label."
        ),
        "experienced": (
            "Liquidity — depth of available buy/sell orders. High liquidity = tight "
            "spreads, low slippage, smoother fills. Low liquidity = wider spreads, "
            "more slippage, sharper moves on smaller size. Honest limit: liquidity "
            "is observed context, not a quality score."
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
            "regime change. Honest limit: structure is confirmed after price prints."
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
            "lower. Honest limit: accumulation is a plan, not proof price is done "
            "falling."
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
            "read; a failed retest shows the break did not hold. Honest limit: a "
            "retest is information, not permission."
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
            "sustained volume. Weak/absent follow-through flags a failed or exhausted "
            "push. Honest limit: follow-through is read after the move starts."
        ),
    },
    "setup_quality": {
        "beginner": (
            "A setup grade describes the structure the bot is seeing, not the coin "
            "and not a trade. It helps explain why a confirmed zone break was worth "
            "mentioning or why a weaker break stayed quiet. Honest limit: a grade is "
            "a label for the setup, never a reason to act."
        ),
        "experienced": (
            "Setup Quality — internal structure grade derived from break quality "
            "checks. It grades the setup, not direction or outcome. Honest limit: it "
            "is context, not conviction."
        ),
    },
    "break_strength_score": {
        "beginner": (
            "An internal quality check the bot uses before it mentions a break. It "
            "looks at mechanical details like close strength, volume, and location. "
            "It is not shown on cards and it is not something to trade. Honest limit: "
            "it is a filter for the bot, not a promise about price."
        ),
        "experienced": (
            "Break Strength Score — internal gating input for break quality. It can "
            "suppress weak structure before a user sees it. Honest limit: mechanical "
            "filters reduce noise; they do not forecast follow-through."
        ),
    },
    "patience_grade": {
        "beginner": (
            "A calm label for how much to look, not how much to act. In the current "
            "alert model, the structure has to come first: a confirmed zone break. "
            "Then Poinkle checks whether context agrees, such as 6h structure, EMA "
            "trend, and volume participation. Honest limit: a higher label means "
            "less noise, not a better trade."
        ),
        "experienced": (
            "Patience Grade — user-facing noise-control read: confirmed structure "
            "plus agreement from context inputs. Honest limit: it describes how much "
            "is worth inspecting, not probability or action strength."
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
    "double top": "double_top",
    "doubletop": "double_top",
    "double-top": "double_top",
    "dt": "double_top",
    "m top": "double_top",
    "m-top": "double_top",
    "double bottom": "double_bottom",
    "doublebottom": "double_bottom",
    "double-bottom": "double_bottom",
    "db": "double_bottom",
    "w bottom": "double_bottom",
    "w-bottom": "double_bottom",
    "neckline": "neckline",
    "neck line": "neckline",
    "neck-line": "neckline",
    "breakout": "breakout",
    "break out": "breakout",
    "breakdown": "breakdown",
    "break down": "breakdown",
    "confluence": "confluence",
    "dominance": "dominance",
    "btc.d": "dominance",
    "btcd": "dominance",
    "btc dominance": "dominance",
    "bitcoin dominance": "dominance",
    "usdt.d": "dominance",
    "usdtd": "dominance",
    "usdt dominance": "dominance",
    "tether dominance": "dominance",
    "market dominance": "dominance",
    "alt season": "dominance",
    "altseason": "dominance",
    "trend": "trend",
    "market trend": "trend",
    "confirmation": "confirmation",
    "confirmed": "confirmation",
    "confirm": "confirmation",
    "confirmed break": "confirmation",
    "fakeout": "confirmation",
    "fake breakout": "confirmation",
    "real breakout": "confirmation",
    "false breakout": "confirmation",
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
    "double_top": "Double Top",
    "double_bottom": "Double Bottom",
    "neckline": "Neckline",
    "breakout": "Breakout",
    "breakdown": "Breakdown",
    "confluence": "Confluence",
    "dominance": "Dominance",
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
