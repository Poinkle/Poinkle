# Python Crypto Alert Scanner

A simple Python scanner that watches Coinbase market data and supports manual Telegram `/levels` market-structure requests.

`MAIN_CHAT_SAFE_MODE = True` is enabled near the top of `crypto_alert_scanner.py`.

When safe mode is on:

- Automatic trade alerts are disabled.
- Breakout and confirmation alerts are disabled.
- Entry, stop loss, TP target, and trade plan alerts are disabled.
- The only Telegram message the bot sends is a manual `/levels SYMBOL` response.

The older automatic scanner logic remains in the file for testing/development. If safe mode is turned off later, it can send alerts for:

- EMA 21 crossing above EMA 55
- EMA 21 crossing below EMA 55
- RSI 14 crossing above 70 or below 30
- Volume at least 2x higher than the previous 20 closed candles, only when it happens with a breakout attempt, breakdown attempt, EMA cross, Retest Holding, or Retest Failed context

The scanner only checks fully closed 15-minute candles. It skips the currently forming candle.
Each closed candle is processed once per symbol, and `scanner_state.json` prevents duplicate alerts after restarts.
The main scanner checks every 15 seconds so alerts can be sent shortly after a candle closes.

Every Telegram alert includes:

- Candle Close Time in Eastern Time
- Alert Sent Time in Eastern Time

## Project Focus

Current work is focused on reliability only:

- Breakout and breakdown detection from closed 15m candles
- Confirmation and rejection logic after a level breaks
- 1m tracking updates after an early warning

New feature ideas should go in `FUTURE_IDEAS.md` until the core alert flow is proven stable.

## Telegram Commands

While the scanner is running, send this command in Telegram:

```text
/levels BTC
```

Supported `/levels` symbols:

`BTC`, `ETH`, `SOL`, `XRP`, `BNB`, `DOGE`, `ADA`, `LINK`, `AVAX`, `SUI`, `TON`, `HBAR`, `TAO`, `RENDER`, `FET`, `NEAR`, `AKT`, `ICP`, `AAVE`, `UNI`, `INJ`, `ATOM`, `PEPE`, `SHIB`, `WIF`, `JASMY`, `FARTCOIN`, `HYPE`, `ONDO`, `PENGU`, `NOBODY`, `EDEL`

Uppercase and lowercase both work. If a symbol is not available from the exchange/data source, the bot replies with `Symbol currently unavailable.`

If `/levels SYMBOL` is used in a group chat, the full report is sent privately to the user who requested it. The group only receives a short confirmation or a note asking the user to start the bot first. Set `TELEGRAM_BOT_USERNAME` in `.env` so that start-bot note points to the right bot username.

The bot replies with broad 4H/daily/weekly zones, not exact penny levels:

- Current Price
- Current Location
- Trend
- Trend Reason
- Overall Confidence
- Accumulation Rating
- Summary
- Market Structure with structure label, support-distance position, nearest support/resistance, distance to nearest support/resistance, and volume status
- Accumulation Zones
- Distribution Zones
- EMA Information
- RSI Information
- Score Breakdown
- Best Use Case
- Educational market-structure disclaimer
- Levels Engine version

Zones are built from 4H, daily, and weekly swing highs/lows, major support and resistance areas, consolidation zones, large round-number psychology levels, and ATR spacing. Exact levels are reserved for entries and stops after a confirmed setup.

## Test Mode

`TEST_MODE = True` is near the top of `crypto_alert_scanner.py`.

When test mode is on, support/resistance alerts use temporary levels near the current market price:

- Support = current price * 0.999
- Resistance = current price * 1.001

All Telegram alerts are labeled `TEST MODE`. Set `TEST_MODE = False` to use your normal `KEY_LEVELS`.

When test mode starts, the terminal prints four location-filter examples:

- Bearish break near range low should produce `Late Move / Exhaustion Risk`.
- Bearish break below the middle of the range with room to support should confirm.
- Bullish break near range high should produce `Late Move / Exhaustion Risk`.
- Bullish break above the middle of the range with room to resistance should confirm.

Range labels are printed as `Lower Range`, `Middle Range`, or `Upper Range`. Quality is determined by the confidence score, not the range label.
Normal scans print one compact terminal summary per cycle. Full debug details only print when an early warning triggers, tracking mode is active, a trade is confirmed, or a trade is rejected.
High-volume events that do not have confirmation context are logged in the terminal only. They are not sent to Telegram.

## Trade Tracking Mode

When an early 15m support/resistance setup alert is sent, the symbol is added to an active tracking list in `scanner_state.json`.

Tracked symbols are checked every 60 seconds on a lower timeframe for up to 60 minutes. The tracker watches:

- Price relative to the broken level
- RSI direction
- Volume changes
- Retest success or failure
- EMA alignment

Telegram tracking updates are only sent when status changes:

- Strengthening
- Weakening
- Retest Holding
- Retest Failed
- Trade Confirmed
- Trade Invalidated
- Failed Breakout
- Failed Breakdown

Tracking stops after `Trade Confirmed`, `Trade Invalidated`, `Failed Breakout`, `Failed Breakdown`, or 60 minutes.

Fake-break detection watches the first 1-3 lower-timeframe candles after an early warning:

- Bullish breakout fails if price closes back below the broken level.
- Bearish breakdown fails if price closes back above the broken level.
- Failed breakout/breakdown alerts recalculate Break Strength and Setup Quality from the reclaim candle. They are downgraded to `D` / `Watch Only` so invalidated trades do not keep the original A, B, or C rating.

Early breakout/breakdown warnings include:

- Setup Quality
- Setup Status
- Break Strength Score
- Range High
- Range Low
- Range Position
- Next Target Level
- Distance To Next Target %

Confirmation alerts include:

- Setup Quality
- Setup Status
- Room To Target
- Location Quality
- Break Strength Score
- RSI status
- EMA trend
- Volume status

Break Strength Score runs from 0-100 and includes volume strength, RSI alignment, EMA alignment, candle close strength beyond the level, retest behavior, and distance to the next target.

Setup Quality grades use this scale:

- `90-100` = `A+`
- `80-89` = `A`
- `70-79` = `B`
- `60-69` = `C`
- `50-59` = `D`
- Below `50` = `F`

Setup status uses the grade:

- `A+` / `A` = `High Interest Setup`
- `B` = `Watch Closely`
- `C` = `Watch Only`
- `D` / `F` = `Weak Setup / Avoid Chasing`

Trade plans are only sent when Break Strength is 70+, volume is not weak, price has room to the next target, `Location Quality` is not `C`, and `Setup Quality` is not `D` or `F`. Weak setups are replaced with `Weak Break / Watch Only`, `Failed Follow-Through`, or `Late Move / Exhaustion Risk`.

## Tests

Run the local logic tests with:

```bash
python3 -m unittest discover -s tests -v
```

The tests use fake candle data and do not require Telegram or Coinbase access.

## Support And Resistance Levels

Add your levels near the top of `crypto_alert_scanner.py`:

```python
KEY_LEVELS = {
    "BTC/USD": {"support": [100000], "resistance": [110000]},
    "ETH/USD": {"support": [], "resistance": []},
}
```

Support/resistance alerts use candle closes only. Wicks are ignored.

- Close below support sends a Breakdown Attempt.
- Close above resistance sends a Breakout Attempt.
- The next 15m candle must close beyond the same level to send confirmation.
- If the next candle closes back inside the level, the pending setup is cleared.
- Early warnings include Setup Quality, Break Strength, range position, distance to target, and a warning note.
- Confirmed break alerts include a setup classification, Setup Quality, confidence score, Break Strength Score, entry zone, structure-based stop loss, and 1R/2R/3R targets.

## Watchlist

Edit the single master `WATCHLIST` near the top of `crypto_alert_scanner.py` to add or remove symbols. The scanner, startup `Watching:` output, `/levels`, and symbol aliases all use this same list:

```python
WATCHLIST = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "XRP/USD",
    "BNB/USD",
    "DOGE/USD",
    "ADA/USD",
    "LINK/USD",
    "AVAX/USD",
    "SUI/USD",
    "TON/USD",
    "HBAR/USD",
    "TAO/USD",
    "RENDER/USD",
    "FET/USD",
    "NEAR/USD",
    "AKT/USD",
    "ICP/USD",
    "AAVE/USD",
    "UNI/USD",
    "INJ/USD",
    "ATOM/USD",
    "PEPE/USD",
    "SHIB/USD",
    "WIF/USD",
    "JASMY/USD",
    "FARTCOIN/USD",
    "HYPE/USD",
    "ONDO/USD",
    "PENGU/USD",
    "NOBODY/USD",
    "EDEL/USD",
]
```

## Mac Setup Using VS Code

1. Install Python 3

   Open Terminal and check:

   ```bash
   python3 --version
   ```

   If Python is not installed, install it from [python.org](https://www.python.org/downloads/macos/).

2. Open the project in VS Code

   In VS Code, choose `File > Open Folder...` and open this folder:

   ```text
   crypto-alert-scanner
   ```

3. Create a virtual environment

   Open the VS Code terminal with `Terminal > New Terminal`, then run:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

4. Install dependencies

   ```bash
   pip install -r requirements.txt
   ```

5. Create your `.env` file

   Copy `.env.example` to `.env`:

   ```bash
   cp .env.example .env
   ```

   Then open `.env` in VS Code and fill in:

   ```text
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   TELEGRAM_CHAT_ID=your_telegram_chat_id_here
   ```

## Getting Telegram Values

1. In Telegram, message `@BotFather`.
2. Send `/newbot` and follow the prompts.
3. Copy the bot token into `TELEGRAM_BOT_TOKEN`.
4. Send a message to your new bot so Telegram creates a chat.
5. Open this URL in your browser, replacing `YOUR_TOKEN_HERE`:

   ```text
   https://api.telegram.org/botYOUR_TOKEN_HERE/getUpdates
   ```

6. Find the `chat` object and copy its `id` into `TELEGRAM_CHAT_ID`.

## Get Your Chat ID With The Helper Script

You can also use the included helper script.

1. Make sure your `.env` file has `TELEGRAM_BOT_TOKEN` filled in.
2. Send a message to your Telegram bot.
3. Run:

   ```bash
   python get_chat_id.py
   ```

4. Copy the chat ID printed in the terminal into your `.env` file:

   ```text
   TELEGRAM_CHAT_ID=the_chat_id_printed_by_the_script
   ```

If your scanner already sends Telegram alerts, your `TELEGRAM_CHAT_ID` is working. `get_chat_id.py` only reads inbound updates sent to the bot. Alerts the bot sends to you do not appear in `getUpdates`.

## Run The Scanner

With your virtual environment active:

```bash
python crypto_alert_scanner.py
```

Leave the terminal open while you want alerts. Stop it with `Control + C`.

## Notes

- The script polls every 60 seconds.
- Coinbase usually returns the active candle as the latest candle, so the scanner uses the second-to-last candle for alerts.
- RSI alerts only fire when RSI first crosses below 30 or first crosses above 70. They do not repeat while RSI remains outside those levels.
- Volume spike alerts still fire once per qualifying candle. Bullish spikes require close above EMA21 and RSI above 50. Bearish spikes require close below EMA21 and RSI below 50. If EMA and RSI do not agree, the alert is labeled High Volume Alert with no trade confirmation yet.
- Support/resistance confirmations only fire when the next 15m candle closes beyond the same level.
- Confirmed support/resistance breaks include an educational trade plan based on ATR 14, the broken level, and the first/confirmation candle structure.
- Confirmation confidence scores use RSI, EMA alignment, volume multiple, confirmation candle strength, and retest quality. Volume is a major factor.
- If confirmation volume is below the 20-candle average, the setup is heavily penalized and rated `Avoid`.
- Confirmation alerts now check location inside the recent range. Shorts near range lows and longs near range highs are blocked as late move/exhaustion risk unless price breaks and holds beyond the range.
- `scanner_state.json` is created automatically to remember checked candles and prevent repeated Telegram messages after restarts.
- If Coinbase blocks access from your region or does not return data for a symbol, ccxt may show an exchange access error.
