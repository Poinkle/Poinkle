# 15 — Signal-Set Vetting (Swing Entry Quality)

*Poinkle — Trading Intelligence. Design doc. Written July 8, 2026.*
*Extends doc 14 (Swing Trading Pivot). Design-first; staged build follows.*

---

## Why this doc exists

The swing pivot (doc 14) moved the bot's **decision timeframe** to daily but
did not re-vet the **signal definitions** carried over from the earlier
day-trading build. On the first true live daily close (July 8, 8:00 PM ET),
the bot fired two cards that contradict the mission:

- **LDO/USD** — signal "RSI crossed above 70" + volume spike 3.48x. RSI **72**
  (overbought), EMA21 (0.2748) **below** EMA55 (0.2897) = bearish structure,
  secondary 4h/8h context **unavailable**.
- **SAFE/USD** — "Breakout Confirmation" + volume spike 2.58x. Candle body
  **0.38%** (near-doji), fired from **mid** range, EMA21 (0.0934) **below**
  EMA55 (0.1026) = bearish structure, secondary context **unavailable**.

Both fires told the group to look bullish at what is closer to a
take-profit / resistance zone than an accumulation zone. That is the exact
reactive behavior "patience compounds" exists to prevent.

Diagnostic note from the live log: the plumbing is healthy. The scan
completed every cycle, and the confirmed-break filter suppressed 132 of 134
coins. The problem is **not** that the filter is off — it is **what the
filter counts as a valid bullish swing entry**.

---

## Settled decisions carried forward (doc 14 — restated here so they live on disk)

- **D1** — Daily is the primary decision timeframe. 4h/8h are secondary
  context only, never decision drivers.
- **D2** — Card timeframe label locked to "Daily" (never "1d"/"1D").
- **D3** — Confirmed level breaks only. Suppress attempts, weak breaks,
  failed breaks, late breaks. Internal pending-setup machinery preserved but
  muzzled from Telegram.
- **D4** — Bullish / accumulation signals only. No shorting, no bearish
  alerts to the group. Product surfaces buy-side swing setups.
- **D5** — Trade-tracking muted from Telegram
  (`TRADE_TRACKING_TELEGRAM_ENABLED = False`). Monitor runs internally.
- **D6** — 24h cooldown per coin. One daily signal per coin per day.

This doc adds D7–D10 below, which **sharpen D3 and D4** — the two decisions
that were under-specified and that both bad fires fell through.

---

## New decisions

### D7 — Remove RSI > 70 as a bullish trigger

RSI above 70 is overbought — the top of a move, not an accumulation entry.
"RSI crossed above 70 → bullish card" teaches chasing, the opposite of
buy-at-support. Remove it from the bullish signal set entirely. Nothing
replaces it tonight.

*Future (not now): a proper bullish RSI signal would be RSI turning up off
oversold, e.g. crossing up through ~40–50 — captured, not built.*

### D8 — Trend gate: bearish EMA structure allowed only at support

Do **not** hard-block every bearish-EMA fire — that would kill legitimate
accumulate-on-the-dip buys, which by the support/resistance teaching
strategy happen *before* the trend turns. Instead:

- If **EMA21 < EMA55** (bearish structure) AND price is **mid or upper
  range** → **suppress**. (This is chasing a bounce inside a downtrend —
  exactly what LDO and SAFE were.)
- If **EMA21 < EMA55** AND price is **lower range** → **allowed** (buying
  the dip into support).
- If **EMA21 ≥ EMA55** → trend gate does not block.

### D9 — Breakout confirmation quality floor

A "confirmed breakout" must show conviction. Require BOTH:

- Price in **upper range** (cannot confirm a break from mid range), AND
- Candle **body ≥ 1.5%** of price (starting threshold, tunable after live
  observation).

SAFE failed both: mid range, 0.38% body.

### D10 — Suppress fires when secondary (4h/8h) context is unavailable

Both bad fires were the two thinnest coins, with insufficient history to
compute the 4h/8h context the card is built to display. If the bot cannot
compute the secondary context, it does not fire. Thin, erratic, low-history
coins are the riskiest for beginners and were the actual culprits tonight.

---

## Thresholds summary (tunable)

| Parameter | Value | Rationale |
|---|---|---|
| RSI>70 bullish trigger | REMOVED | Overbought ≠ entry (D7) |
| Trend gate | Bearish EMA + mid/upper range = suppress (D8) | Block chasing, allow dip-buys |
| Breakout range | Upper range required (D9) | Can't confirm from mid |
| Breakout body | ≥ 1.5% (D9) | Conviction floor; tune live |
| Secondary context | Required to fire (D10) | No context = no card |

---

## Scope guardrails

- This doc changes **signal qualification only**. It does not touch the
  scan loop, delivery, cooldowns (D6), card layout, or the muted trade
  monitor.
- Internal pending-setup / signal-detection machinery is preserved (D3).
  We are gating what reaches Telegram, not deleting detection logic.
- Thresholds in D9 are starting values. After the fix ships, watch for
  false-negatives (real breakouts missed) and tune, per the swing-pivot
  monitoring note.

## Out of scope (captured, not tonight)

- `Active trade monitor failed. Will retry quietly.` spamming ~12 coins per
  scan — internal error, muted from Telegram, cleanup later.
- Delivery-delay rolling stat polluted by a stale prior-day alert
  (`max 76322s`) — cosmetic.
- Lightweight-signal log date label (`2026-07-07`) vs audit snapshot date
  (`2026-07-08`) — one-glance check later.
- Bullish-RSI-off-oversold replacement signal (D7 future note).

---

## Build plan

Staged Codex task, workspace-check first, one stage, diff-reviewed before
anything else. D7–D10 are a single coherent change to the bullish
qualification path, so they ship as one reviewed stage rather than four
micro-commits.
