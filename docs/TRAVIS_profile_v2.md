# TRAVIS — Poinkle Founder Profile

*Carry-forward context for new threads. Last updated: July 9, 2026.*
*Travis: edit anything that's off, trim anything too personal, add what's missing.*

---

## Who I am / the mission

I'm Travis, founder and product owner of **Poinkle** — "Connect Humanity
Through Knowledge." Poinkle is a communication operating system and human
knowledge platform. The first public product is **Poinkle Trading
Intelligence**: a Telegram-based crypto alert and education bot (@Poinkle_Bot)
built around a **"patience compounds"** philosophy — spot/swing accumulation,
no shorting, no leverage, no day-trading framing.

Crypto is "just the toe." Trading Intelligence is the first classroom of a
much larger system modeled on the human body, eventually spanning multiple
domains and communities. The deeper driver: knowledge dies with people who
hold it, and I want to help preserve and connect it. I started building with
zero coding background in late June 2026, learning trading fundamentals and
development side by side.

---

## How I work (read this — it matters)

- **I generate, my AI tools organize.** Ideas arrive fast and out of order,
  often mid-task. If I don't capture an idea the moment it lands, it's gone.
  So when I drop a random idea in the middle of other work, catch it, tag it,
  park it, and steer us back — don't treat it as a derail. Some of those
  trains are carrying the good stuff.
- **I follow my own focus and energy rhythm**, including odd hours. When I'm
  locked in, I push hard; the work itself helps me rest better afterward.
  Don't push me to stop or to keep going — follow my lead on pace.
- **Voice-to-text extensively** — interpret transcription errors charitably.
- **Two-screen setup.** Military background; military terminology is natural
  and preferred. SITREP-style status updates work well.
- **Design-doc-first, always.** No code changes without a written plan.
  Staged builds with diff review before committing.
- **Copy-paste discipline:** label every block — `📋 → PASTE INTO CODEX:`,
  `⌨️ → RUN IN TERMINAL:`, `📋 → PASTE INTO GROK:`. Every command in its own
  clean block. Put a copy block on ANYTHING I need to type. Don't refer me
  back to an earlier message to find a command — re-post or ask.
- **Which window gets what:** Grok = image prompts. Codex = code tasks.
  Terminal = magick/git/python commands. (I sometimes paste into the wrong
  one — a gentle catch helps.)
- **I ask a lot of questions to learn.** Explain the "why," not just the
  "what" — it's how it eventually sticks. I want to actually understand this,
  not just run commands blindly.
- **Do it right the first time.** I don't like shortcuts or having to go back
  and redo things. Given the choice, I'll spend more effort now for a clean
  foundation over a fast patch.

---

## AI collaboration structure

- **Travis = Commander.** Final decision authority on everything.
- **Claude = Chief Strategist / Architect.** Drafts, synthesizes, verifies,
  reviews. Gives a clear recommendation *with* options, then I decide yes/no.
  Does NOT independently decide next tasks or start implementation — waits for
  assignment.
- **Codex = engineering executor.** Every Codex task opens with a workspace
  check: *"FIRST: reply with your current workspace root; if it is not
  /Users/travisjoshinabery/Desktop/TIC BOT, STOP and do nothing."* Codex has
  drifted to stale folders before; this catches it. Recon → diff review →
  commit.
- **Grok = visual/card generation.** Note: Grok outputs JPGs (convert to PNG),
  and historically reinvented the pig logo — now solved (see below).
- **GPT = secondary adviser / council member.**
- **Council synthesis pattern:** when I bring input from multiple advisers, I
  paste it all at once → Claude analyzes, catches conflicts, returns ONE
  merged recommendation. I decide.

---

## Project state (CURRENT — as of July 9, 2026)

**Bot runs locally** at `/Users/travisjoshinabery/Desktop/TIC BOT` on my Mac.
`/livealerts` is **ON** and the bot is live to the group.

**Signal-set vetting (D7–D10) — DONE, live (commit 07c5646).** The swing pivot
had moved timeframes to daily but left old day-trading signal definitions in
place, so the bot was firing bad alerts (overbought RSI, bearish EMA
structure, thin-body breakouts, missing 4h/8h context). Fixed:
- D7: removed RSI>70 as a bullish trigger
- D8: trend gate — bearish EMA allowed only at support (lower range)
- D9: breakout requires upper-range + body ≥ 1.5%
- D10: suppress when secondary 4h/8h context unavailable
Expect **quieter alerts** — that's the design working, not the bot sleeping.
Documented in `15_Signal_Set_Vetting_Design.md` (now saved to disk).

**Teaching cards — 19 complete, all live in `/explain`.**
- Layout: full-bleed chart + text overlaid in corners + a branded **footer bar**
  (crisp pig + bold "POINKLE" + "LEARN. WATCH. GROW."), color-matched per card.
- First 9 (rsi, support, resist, breakout, breakdown, con/confluence, trend,
  ema, volume) kept with their existing big logo.
- 10 new (confirmation, candle, range, keylevel, liquidity, structure,
  accumulation, retest, followthrough, tradeplan) built with the footer,
  wired into `CONCEPT_TEACHING_CARD_FILES`, live.
- `/explain` and `/learn` now send **card only, no text paragraph**.
- Aliases cover one-word, spaced, capitalized, hyphenated forms.

**Logo workflow — SOLVED.** Grok kept reinventing the pig and outputs JPGs.
New process: Grok generates the chart with an empty corner (no logo) → footer
(with the real crisp logo) is composited on afterward via **ImageMagick**
(`magick`), which is now installed. A crisp `poinkle_logo_full.png` and the
per-card footer command exist. Do NOT ask Grok to place the logo anymore.

**Patience Grade rename — DONE (commit 06799c8).** The vault docs called it
"Patience Grade" but the code called it `accumulation_grade` — naming drift.
Renamed internal identifiers `accumulation_grade`→`patience_grade`,
`accumulation_label`→`patience_label`, `grade_accumulation()`→`grade_patience()`,
`score_accumulation_setup()`→`score_patience_setup()`. User-facing strings
("Excellent accumulation" etc.) left UNCHANGED on purpose — that wording is a
separate copy decision. The genuine "accumulation" concept (zones, glossary
card, `patience_score` proximity metric) was left untouched.

**Poinkle-specific term definitions (mapped from code July 9):**
- **Snapshot** = the presentation card packaging price, S/R, trend, RSI,
  Market Score, teaching notes. "A snapshot in time, not a trend call."
- **Market Score** = 0–100 overall technical confidence
  (`calculate_overall_confidence`), shown as X.X / 10.
- **Break Strength Score** = 0–100 raw score (volume, RSI/EMA alignment, close
  strength, retest quality, room to target; capped for poor location/momentum).
- **Setup Quality** = Break Strength Score expressed as an A–F letter grade.
- **Patience Grade** = the A–F accumulation-fit grade (formerly
  `accumulation_grade`); proximity to support, trend, RSI, volume, structure.
- **patience_score** = SEPARATE chart metric (distance to nearest level, "42/100").

---

## On the horizon / bench (not urgent)

- **User-facing grade label wording** — deliberately left as "Excellent
  accumulation" etc.; decide the perfect user-facing copy as its own pass.
- **5 Poinkle-term glossary entries** — write clean Dad-Test definitions for
  Snapshot / Market Score / Setup Quality / Break Strength Score / Patience
  Grade (definitions now known; entries not yet written).
- **Interactive button foundation** (THE big one) — tappable coin menu,
  coin auto-complete, layered /research card, per-user preferences (timeframe
  choice, severity filtering, privatize-alert). Build ONCE, all fall out of it.
  Validated by real friction: Telegram's slash-menu sends immediately, which
  is clunky for commands needing a coin argument.
- **Alert severity labels** — ~3 signals = "yellow," 4–5+ = "red."
- **Community daily-report posts** — `daily_report.sh` exists (build report:
  commits + line stats). Post end-of-day summaries to the group; building in
  public with two-way engagement is my edge vs broadcast-only communities.
- **Bitcoin mining stocks vertical** (future) — MARA, RIOT, CLSK as
  educational mini-classrooms; bridges crypto to equities.
- **AI voice cloning** (ElevenLabs) for bulk video content; real voice for
  personal moments. Lightly disclose AI-voice use (on-brand transparency).
- **Vault/reference docs drifted** — 04 (Telegram Commands), 07 (Architecture),
  09 (Roadmap), 10 (Future Ideas) predate recent work; refresh when relevant.

---

## Key principles (non-negotiable)

- **Honest-limit lines** on every card and glossary entry — Poinkle's signature
  voice. Every explanation ends with an honest limitation.
- **Dad Test** — read explanations aloud; if a non-trader trips on any word,
  simplify.
- **Teaching framing** — "buy at support when price dips into it," NOT "buy
  when bearish." Always include that support/resistance CAN break, plus "never
  all-in, only swing a portion" as the risk anchor.
- **Bot restart protocol (always in order):** (1) `pkill -f
  crypto_alert_scanner.py` (2) verify empty: `ps aux | grep
  crypto_alert_scanner | grep -v grep` (3) `python3 crypto_alert_scanner.py`.
  Skipping the verify causes stacked processes / duplicate alerts.
- **Files have homes:** card images → `assets/`; vault/design docs → vault;
  tools (command deck) → wherever I open them. Download files to disk, don't
  just preview in Google Docs. Don't dump everything into one folder.

---

## Tools & resources

- **Telegram:** @Poinkle_Bot, Poinkle Alpha group (~13 members), my own DM as
  a safe test path.
- **Exchanges:** Coinbase (primary), KuCoin (secondary, for coins not on
  Coinbase).
- **Codex** (engineering), **Grok** (card visuals), **GPT** (adviser/council).
- **ImageMagick** (`magick`) — installed; used for logo compositing & format
  conversion. **Homebrew** installed.
- **CapCut** (video), **ElevenLabs** (planned voice cloning), **TikTok
  @thepoinkle / YouTube** (distribution).
- **Key files:** `crypto_alert_scanner.py` (main bot), `explanations.py`
  (19-concept glossary + aliases), `scoring.py`, `chart_generator.py`,
  `assets/` (cards + `poinkle_logo_full.png`), `daily_report.sh`,
  vault docs (`09_Product_Roadmap.md`, `15_Signal_Set_Vetting_Design.md`, etc.).
