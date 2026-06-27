import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from scanner import format_scan_message, scan_top_100

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv():
        return None

try:
    import ccxt
except ModuleNotFoundError:
    ccxt = None

try:
    import requests
except ModuleNotFoundError:
    requests = None


TEST_MODE = True
MAIN_CHAT_SAFE_MODE = True
DEBUG = False
BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "BOT_USERNAME")

# Single master symbol list used by the scanner and /levels command.
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
    "DOT/USD",
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
]


# Add your key support and resistance levels here.
# Alerts use candle closes only. Wicks are ignored.
KEY_LEVELS = {symbol: {"support": [], "resistance": []} for symbol in WATCHLIST}

TIMEFRAME = "15m"
TRADE_TRACK_TIMEFRAME = "1m"
TIMEFRAME_MS = 15 * 60 * 1000
CANDLE_LIMIT = 120
POLL_SECONDS = 15
TRADE_TRACK_POLL_SECONDS = 60
TRADE_TRACK_MAX_MINUTES = 60
STATE_FILE = Path("scanner_state.json")
USER_ALERTS_FILE = PROJECT_DIR / "user_alerts.json"
ERROR_COOLDOWN_SECONDS = 300
ALERT_COOLDOWN_SECONDS = 3600
LEVEL_ALERT_TYPES = {"support", "resistance", "all", "critical"}
EASTERN_TIME = ZoneInfo("America/New_York")
ERROR_LOG_STATE = {}


class MarketDataError(RuntimeError):
    pass


def log_info(message):
    print(f"[INFO] {message}")


def log_warn(message):
    print(f"[WARN] {message}")


def log_error(message):
    print(f"[ERROR] {message}")


def throttled_log_warn(symbol, error_key, message):
    now = time.time()
    state_key = (symbol, error_key)
    last_logged = ERROR_LOG_STATE.get(state_key, 0)
    if now - last_logged < ERROR_COOLDOWN_SECONDS:
        return

    ERROR_LOG_STATE[state_key] = now
    log_warn(message)


def throttled_log_error(symbol, error):
    message = str(error) or error.__class__.__name__
    throttled_log_warn(symbol, message, f"{symbol}: {message}")


def candle_error_message(symbol, error):
    text = str(error).lower()
    if "no candles" in text:
        return f"{symbol}: Coinbase returned no candles. Skipping."
    if "malformed" in text or "missing" in text:
        return f"{symbol}: Coinbase returned malformed candles. Skipping."
    if "not enough" in text:
        return f"{symbol}: Not enough candles for indicators. Skipping."
    if "unsupported" in text or "symbol" in text or "market" in text or "not found" in text:
        return f"{symbol}: Unsupported Coinbase pair. Skipping."
    if "timeout" in text or "rate" in text or "429" in text:
        return f"{symbol}: Coinbase candle fetch failed. Will retry quietly."
    return f"{symbol}: Coinbase candle fetch failed. Will retry quietly."


def validate_ohlcv_candles(candles, symbol, min_count=1):
    if not candles:
        raise MarketDataError("Coinbase returned no candles")
    if not isinstance(candles, list):
        raise MarketDataError("Coinbase returned malformed candles")
    if len(candles) < min_count:
        raise MarketDataError("Not enough candles for indicators")

    for candle in candles:
        if not isinstance(candle, (list, tuple)) or len(candle) < 6:
            raise MarketDataError("Coinbase returned malformed candles")
        try:
            for value in candle[:6]:
                float(value)
        except (TypeError, ValueError) as error:
            raise MarketDataError("Coinbase returned malformed candles") from error

    return candles


def ema(values, period):
    if len(values) < period:
        raise ValueError(f"Need at least {period} values to calculate EMA")

    multiplier = 2 / (period + 1)
    current_ema = sum(values[:period]) / period

    for value in values[period:]:
        current_ema = (value - current_ema) * multiplier + current_ema

    return current_ema


def rsi(values, period=14):
    if len(values) <= period:
        raise ValueError(f"Need more than {period} values to calculate RSI")

    gains = []
    losses = []

    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0)
        loss = abs(min(change, 0))
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

    if avg_loss == 0:
        return 100.0

    relative_strength = avg_gain / avg_loss
    return 100 - (100 / (1 + relative_strength))


def atr(candles, period=14):
    if len(candles) <= period:
        raise ValueError(f"Need more than {period} candles to calculate ATR")

    true_ranges = []
    for index in range(1, len(candles)):
        previous_close = candles[index - 1][4]
        high = candles[index][2]
        low = candles[index][3]
        true_ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )

    return sum(true_ranges[-period:]) / period


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def load_user_alerts():
    if not USER_ALERTS_FILE.exists():
        return {}

    try:
        return json.loads(USER_ALERTS_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def save_user_alerts(alerts):
    USER_ALERTS_FILE.write_text(json.dumps(alerts, indent=2, sort_keys=True))


def count_enabled_user_alerts(alerts):
    total = 0
    for alerts_by_symbol in alerts.values():
        total += sum(1 for config in alerts_by_symbol.values() if config.get("enabled"))
    return total


def candle_time(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def eastern_time_from_timestamp(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=EASTERN_TIME).strftime(
        "%Y-%m-%d %I:%M %p ET"
    )


def eastern_time_now():
    return datetime.now(tz=EASTERN_TIME).strftime("%Y-%m-%d %I:%M:%S %p ET")


def scan_header_time():
    return datetime.now(tz=EASTERN_TIME).strftime("%-I:%M %p ET")


def alert_time_text(timestamp_ms):
    return (
        f"<b>Candle Close Time:</b> {eastern_time_from_timestamp(timestamp_ms)}\n"
        f"<b>Alert Sent Time:</b> {eastern_time_now()}\n"
    )


def send_telegram_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()


def bot_mode_text():
    return "TEST" if TEST_MODE else "PRODUCTION"


def update_bot_status(state, status, scanner_state, last_scan_time=None):
    status_state = state.setdefault("__bot_status", {})
    status_state["mode"] = bot_mode_text()
    status_state["status"] = status
    status_state["scanner_state"] = scanner_state
    status_state["updated_at"] = eastern_time_now()
    if last_scan_time is not None:
        status_state["last_scan_time"] = last_scan_time
    else:
        status_state.setdefault("last_scan_time", "Not scanned yet")


def build_bot_status_message(state, indicator=None, include_details=False):
    status_state = state.get("__bot_status", {})
    status = status_state.get("status", "Offline")
    emoji = indicator or ("🟢" if status == "Online" else "🔴")
    lines = [
        f"{emoji} <b>Poinkle Status</b>",
        f"Mode: {bot_mode_text()}",
        f"Status: {status}",
    ]

    if include_details:
        lines.extend(
            [
                f"Last scan time: {status_state.get('last_scan_time', 'Not scanned yet')}",
                f"Scanner state: {status_state.get('scanner_state', 'Unknown')}",
            ]
        )

    return "\n".join(lines)


def send_status_update(telegram_token, telegram_chat_id, state, indicator=None, extra_line=None):
    message = build_bot_status_message(state, indicator=indicator)
    if extra_line:
        message = f"{message}\n{extra_line}"

    try:
        send_telegram_message(telegram_token, telegram_chat_id, message)
    except Exception as error:
        log_warn(f"Could not send status update: {error}")


def get_telegram_updates(token, offset=None):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"timeout": 1}
    if offset is not None:
        params["offset"] = offset

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json().get("result", [])


def bot_username_text():
    clean_username = str(os.getenv("TELEGRAM_BOT_USERNAME", BOT_USERNAME)).strip().lstrip("@") or "BOT_USERNAME"
    return f"@{clean_username}"


def is_private_chat(chat):
    return chat.get("type") == "private"


def levels_dm_success_message(symbol):
    return (
        f"Sent {symbol} levels to your DM. If you did not receive it, "
        f"start the bot first: {bot_username_text()}"
    )


def levels_dm_failed_message():
    return (
        f"I can't DM you yet. Please start me first: {bot_username_text()}, "
        "then try /levels SYMBOL again."
    )


def fetch_closed_ohlcv(exchange, symbol, timeframe, limit, fallback=None):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        validate_ohlcv_candles(candles, symbol, min_count=2)
        return candles[:-1]
    except Exception as error:
        if fallback is not None:
            try:
                validate_ohlcv_candles(fallback, symbol, min_count=2)
                throttled_log_warn(
                    symbol,
                    f"{timeframe}:fallback:{error}",
                    f"{symbol}: {timeframe} candles unavailable. Using fallback candles.",
                )
                return fallback
            except Exception:
                pass

        handled_error = MarketDataError(candle_error_message(symbol, error))
        throttled_log_warn(symbol, f"{timeframe}:{error}", f"{handled_error}")
        raise handled_error from error


def get_current_market_price(exchange, symbol, fallback_price):
    try:
        ticker = exchange.fetch_ticker(symbol)
        price = ticker.get("last") or ticker.get("close") or fallback_price
        return float(price)
    except Exception as error:
        throttled_log_warn(
            symbol,
            f"ticker:{error}",
            f"{symbol}: Coinbase ticker fetch failed. Using fallback price.",
        )
        return float(fallback_price)


def get_key_levels(symbol, current_market_price):
    if TEST_MODE:
        return {
            "support": [current_market_price * 0.999],
            "resistance": [current_market_price * 1.001],
        }

    return KEY_LEVELS.get(symbol, {})


def format_level(level):
    return f"{level:.8g}"


def normalize_symbol(command_symbol):
    clean_symbol = command_symbol.strip().upper().replace("@", " ").split()[0]
    if not clean_symbol:
        return None

    if clean_symbol.startswith("/LEVELS"):
        return None

    if "/" not in clean_symbol:
        clean_symbol = f"{clean_symbol}/USD"

    for watch_symbol in WATCHLIST:
        if clean_symbol == watch_symbol or clean_symbol == watch_symbol.replace("/", ""):
            return watch_symbol

    return None


def get_trend_bias(current_price, ema_21, ema_55, current_rsi):
    if current_price > ema_21 > ema_55 and current_rsi > 50:
        return "Bullish"
    if current_price < ema_21 < ema_55 and current_rsi < 50:
        return "Bearish"
    return "Neutral"


def get_nearest_levels(levels, current_price, side, limit=3):
    if side == "resistance":
        candidates = [level for level in levels if level >= current_price]
        sorted_levels = sorted(candidates, key=lambda level: level - current_price)
    else:
        candidates = [level for level in levels if level <= current_price]
        sorted_levels = sorted(candidates, key=lambda level: current_price - level)

    return sorted_levels[:limit]


def format_level_list(levels):
    if not levels:
        return "None nearby"
    return ", ".join(format_level(level) for level in levels)


def format_zone_price(price):
    if abs(price) >= 1000:
        return f"{price:,.0f}"
    if abs(price) >= 10:
        return f"{price:,.2f}"
    if abs(price) >= 1:
        return f"{price:,.3f}"
    return f"{price:.5f}"


def format_zone(zone):
    if not zone:
        return "None nearby"
    low, high = zone
    return f"{format_zone_price(low)} - {format_zone_price(high)}"


def zone_padding(current_price):
    return max(abs(current_price) * 0.0015, 0.000001)


def find_swing_levels(candles, side, lookback=2):
    levels = []
    if len(candles) < lookback * 2 + 1:
        return levels

    for index in range(lookback, len(candles) - lookback):
        candle = candles[index]
        left = candles[index - lookback:index]
        right = candles[index + 1:index + 1 + lookback]

        if side == "high":
            high = candle[2]
            if all(high > neighbor[2] for neighbor in left + right):
                levels.append(high)
        else:
            low = candle[3]
            if all(low < neighbor[3] for neighbor in left + right):
                levels.append(low)

    return levels


def unique_sorted_levels(levels, current_price):
    padding = zone_padding(current_price)
    sorted_levels = sorted(level for level in levels if level > 0)
    unique_levels = []
    for level in sorted_levels:
        if not unique_levels or abs(level - unique_levels[-1]) > padding * 0.5:
            unique_levels.append(level)
    return unique_levels


def build_zone_around_level(level, levels, current_price):
    padding = zone_padding(current_price)
    clustered_levels = [
        candidate for candidate in levels if abs(candidate - level) <= padding * 2
    ]
    if not clustered_levels:
        clustered_levels = [level]

    return min(clustered_levels) - padding, max(clustered_levels) + padding


def select_near_and_major_zones(levels, current_price, side):
    if side == "resistance":
        candidates = [level for level in levels if level > current_price]
        candidates = sorted(candidates, key=lambda level: level - current_price)
    else:
        candidates = [level for level in levels if level < current_price]
        candidates = sorted(candidates, key=lambda level: current_price - level)

    if not candidates:
        return None, None

    near_zone = build_zone_around_level(candidates[0], levels, current_price)
    major_zone = None
    for candidate in candidates[1:]:
        if side == "resistance" and candidate > near_zone[1] + zone_padding(current_price):
            major_zone = build_zone_around_level(candidate, levels, current_price)
            break
        if side == "support" and candidate < near_zone[0] - zone_padding(current_price):
            major_zone = build_zone_around_level(candidate, levels, current_price)
            break

    return near_zone, major_zone


def build_key_zones(current_price, fifteen_minute_candles, hourly_candles, daily_candles):
    recent_50_low, recent_50_high = get_recent_range(fifteen_minute_candles, 50)
    recent_100_low, recent_100_high = get_recent_range(fifteen_minute_candles, 100)

    previous_day = daily_candles[-1] if daily_candles else None
    previous_day_high = previous_day[2] if previous_day else recent_100_high
    previous_day_low = previous_day[3] if previous_day else recent_100_low

    resistance_levels = (
        find_swing_levels(fifteen_minute_candles[-100:], "high")
        + find_swing_levels(hourly_candles, "high")
        + [previous_day_high, recent_50_high, recent_100_high]
    )
    support_levels = (
        find_swing_levels(fifteen_minute_candles[-100:], "low")
        + find_swing_levels(hourly_candles, "low")
        + [previous_day_low, recent_50_low, recent_100_low]
    )

    resistance_levels = unique_sorted_levels(resistance_levels, current_price)
    support_levels = unique_sorted_levels(support_levels, current_price)
    near_resistance, major_resistance = select_near_and_major_zones(
        resistance_levels, current_price, "resistance"
    )
    near_support, major_support = select_near_and_major_zones(
        support_levels, current_price, "support"
    )

    return {
        "current_range": (recent_100_low, recent_100_high),
        "near_resistance": near_resistance,
        "major_resistance": major_resistance,
        "near_support": near_support,
        "major_support": major_support,
    }


def estimate_atr_from_candles(candles, period=14):
    if len(candles) <= period:
        return max(candles[-1][4] * 0.03, 0.000001) if candles else 0.000001
    return atr(candles, period)


def round_number_step(current_price):
    if current_price >= 100000:
        return 10000
    if current_price >= 50000:
        return 5000
    if current_price >= 10000:
        return 1000
    if current_price >= 1000:
        return 100
    if current_price >= 100:
        return 10
    if current_price >= 10:
        return 1
    if current_price >= 1:
        return 0.1
    if current_price >= 0.1:
        return 0.01
    return 0.001


def round_psych_level_down(price, step):
    return int(price / step) * step


def round_psych_level_up(price, step):
    return (int(price / step) + 1) * step


def chunk_consolidation_levels(candles, side, chunks=4):
    if not candles:
        return []

    chunk_size = max(len(candles) // chunks, 1)
    levels = []
    for index in range(0, len(candles), chunk_size):
        chunk = candles[index:index + chunk_size]
        if len(chunk) < 5:
            continue
        if side == "support":
            levels.append(min(candle[3] for candle in chunk))
        else:
            levels.append(max(candle[2] for candle in chunk))
    return levels


def build_wide_zone(level, current_price, daily_atr):
    width = max(daily_atr * 0.9, current_price * 0.035)
    low = max(level - width * 0.5, 0)
    high = level + width * 0.5
    return low, high


def zone_midpoint(zone):
    return (zone[0] + zone[1]) / 2


def zone_is_far_enough(zone, selected_zones, min_spacing):
    midpoint = zone_midpoint(zone)
    return all(abs(midpoint - zone_midpoint(selected)) >= min_spacing for selected in selected_zones)


def select_wide_zones(levels, current_price, daily_atr, side, limit):
    min_spacing = max(daily_atr * 1.5, current_price * 0.06)
    if side == "support":
        raw_candidates = [level for level in levels if level < current_price - min_spacing * 0.35]
        raw_candidates = sorted(raw_candidates, key=lambda level: current_price - level)
    else:
        raw_candidates = [level for level in levels if level > current_price + min_spacing * 0.25]
        raw_candidates = sorted(raw_candidates, key=lambda level: level - current_price)

    zones = []
    for level in raw_candidates:
        zone = build_wide_zone(level, current_price, daily_atr)
        if side == "support" and zone[1] >= current_price - min_spacing * 0.2:
            continue
        if side == "resistance" and zone[0] <= current_price + min_spacing * 0.1:
            continue
        if zone_is_far_enough(zone, zones, min_spacing):
            zones.append(zone)
        if len(zones) >= limit:
            break

    return zones


def build_market_level_zones(current_price, four_hour_candles, daily_candles, weekly_candles):
    daily_atr = estimate_atr_from_candles(daily_candles, 14)
    step = round_number_step(current_price)

    support_levels = (
        find_swing_levels(daily_candles, "low", lookback=2)
        + find_swing_levels(four_hour_candles, "low", lookback=3)
        + find_swing_levels(weekly_candles, "low", lookback=1)
        + chunk_consolidation_levels(daily_candles[-120:], "support")
        + chunk_consolidation_levels(weekly_candles[-80:], "support")
    )
    resistance_levels = (
        find_swing_levels(daily_candles, "high", lookback=2)
        + find_swing_levels(four_hour_candles, "high", lookback=3)
        + find_swing_levels(weekly_candles, "high", lookback=1)
        + chunk_consolidation_levels(daily_candles[-120:], "resistance")
        + chunk_consolidation_levels(weekly_candles[-80:], "resistance")
    )

    psych_level = round_psych_level_down(current_price * 0.97, step)
    while psych_level > current_price * 0.35:
        support_levels.append(psych_level)
        psych_level -= step

    resistance_psych = round_psych_level_up(current_price * 1.03, step)
    for _ in range(8):
        resistance_levels.append(resistance_psych)
        resistance_psych += step

    support_levels = unique_sorted_levels(support_levels, current_price)
    resistance_levels = unique_sorted_levels(resistance_levels, current_price)
    range_candles = daily_candles[-100:] if len(daily_candles) >= 20 else four_hour_candles[-100:]
    range_low, range_high = get_recent_range(range_candles, min(len(range_candles), 100))

    return {
        "buy_zones": select_wide_zones(support_levels, current_price, daily_atr, "support", 4),
        "resistance_zones": select_wide_zones(resistance_levels, current_price, daily_atr, "resistance", 3),
        "current_range": (range_low, range_high),
        "daily_atr": daily_atr,
    }


def format_numbered_zones(label, zones):
    if not zones:
        return f"<b>{label}:</b>\nNone nearby\n"
    lines = []
    for index, zone in enumerate(zones, start=1):
        lines.append(f"<b>{label} {index}:</b> {format_zone(zone)}")
    return "\n".join(lines) + "\n"


def get_range_position_label(current_price, range_low, range_high):
    range_size = range_high - range_low
    if range_size <= 0:
        return "Unknown"

    position = (current_price - range_low) / range_size
    if position <= 0.25:
        return "Near Support"
    if position >= 0.75:
        return "Near Resistance"
    return "Middle Range"


def calculate_distance_to_zone_pct(current_price, zone):
    if not zone or current_price == 0:
        return None

    midpoint = zone_midpoint(zone)
    return abs(midpoint - current_price) / current_price * 100


def format_distance_pct(distance_pct):
    if distance_pct is None:
        return "Not available"
    return f"{distance_pct:.2f}%"


def classify_support_distance(distance_pct):
    if distance_pct is None:
        return "Support Distance Unknown"
    if distance_pct <= 5:
        return "At Support"
    if distance_pct <= 10:
        return "Near Support"
    if distance_pct <= 20:
        return "Approaching Support"
    return "Far From Support"


def build_trend_reasons(trend_bias, current_price, ema_21, ema_55, current_rsi):
    if trend_bias == "Bullish":
        header = "Bullish because:"
    elif trend_bias == "Bearish":
        header = "Bearish because:"
    else:
        header = "Neutral because:"

    ema_position = (
        "Price above both Daily EMAs"
        if current_price > ema_21 and current_price > ema_55
        else "Price below both Daily EMAs"
        if current_price < ema_21 and current_price < ema_55
        else "Price between Daily EMAs"
    )
    ema_stack = "EMA21 above EMA55" if ema_21 > ema_55 else "EMA21 below EMA55"
    rsi_text = (
        "RSI above 55"
        if current_rsi > 55
        else "RSI below 50"
        if current_rsi < 50
        else "RSI near neutral"
    )

    return header, [ema_position, ema_stack, rsi_text]


def get_rsi_status(current_rsi):
    if current_rsi > 55:
        return "Bullish"
    if current_rsi < 45:
        return "Bearish"
    return "Neutral"


def format_trend_reasons(trend_reason):
    header, reasons = trend_reason
    return "\n".join([header] + [f"• {reason}" for reason in reasons])


def get_momentum_label(current_rsi, ema_21, ema_55):
    if current_rsi >= 55 and ema_21 > ema_55:
        return "strong"
    if current_rsi < 45 and ema_21 < ema_55:
        return "weak"
    return "neutral"


def get_volume_confirmation_label(volume_multiple):
    if volume_multiple >= 1.2:
        return "confirming"
    if volume_multiple < 0.8:
        return "weak"
    return "neutral"


def get_market_structure(candles, lookback=2):
    swing_highs = find_swing_levels(candles, "high", lookback=lookback)[-3:]
    swing_lows = find_swing_levels(candles, "low", lookback=lookback)[-3:]

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        higher_highs = swing_highs[-1] > swing_highs[-2]
        higher_lows = swing_lows[-1] > swing_lows[-2]
        lower_highs = swing_highs[-1] < swing_highs[-2]
        lower_lows = swing_lows[-1] < swing_lows[-2]

        if higher_highs and higher_lows:
            return "Higher Highs / Higher Lows"
        if lower_highs and lower_lows:
            return "Lower Highs / Lower Lows"

    return "Range Bound"


def zone_contains_price(zone, current_price):
    if not zone:
        return False
    low, high = zone
    return low <= current_price <= high


def get_current_location(current_price, accumulation_zones, distribution_zones, support_distance_label, distance_to_resistance):
    if any(zone_contains_price(zone, current_price) for zone in accumulation_zones):
        return "Inside Accumulation Zone"
    if any(zone_contains_price(zone, current_price) for zone in distribution_zones):
        return "Inside Distribution Zone"
    if support_distance_label in {"At Support", "Near Support", "Approaching Support"}:
        return "Approaching Higher-Timeframe Support"
    if distance_to_resistance is not None and distance_to_resistance <= 10:
        return "Approaching Higher-Timeframe Resistance"
    return "Between Major Zones"


def get_market_structure_label(raw_structure, support_distance_label, distance_to_resistance):
    if support_distance_label in {"At Support", "Near Support"}:
        return "Accumulating"
    if support_distance_label == "Approaching Support":
        return "Approaching Support"
    if distance_to_resistance is not None and distance_to_resistance <= 10:
        return "Approaching Resistance"
    if raw_structure == "Higher Highs / Higher Lows":
        return "Trending Higher"
    if raw_structure == "Lower Highs / Lower Lows":
        return "Trending Lower"
    return "Range Bound"


def build_market_summary(
    symbol,
    current_price,
    current_location,
    support_distance_label,
    trend_bias,
    ema_21,
    ema_55,
):
    base_symbol = symbol.split("/")[0]
    ema_text = (
        "Price is above the Daily EMA21 and EMA55"
        if current_price > ema_21 and current_price > ema_55
        else "Price is still below the Daily EMA21 and EMA55"
        if current_price < ema_21 and current_price < ema_55
        else "Price is between the Daily EMA21 and EMA55"
    )
    trend_text = (
        "Trend remains bullish while support holds"
        if trend_bias == "Bullish"
        else "Trend remains bearish until resistance is reclaimed"
        if trend_bias == "Bearish"
        else "Trend remains neutral until price leaves the current range"
    )
    action_text = (
        "patience is favored until support confirms or resistance is reclaimed."
        if trend_bias != "Bullish"
        else "structure supports holding while price remains above key support."
    )

    return (
        f"{base_symbol} is {current_location.lower()}. "
        f"{ema_text}. {trend_text}, and {action_text}"
    )


def grade_accumulation(score):
    if score >= 80:
        return "A", "Excellent accumulation"
    if score >= 65:
        return "B", "Good accumulation"
    if score >= 50:
        return "C", "Neutral"
    if score >= 35:
        return "D", "Weak accumulation"
    return "F", "Avoid"


def score_accumulation_setup(
    current_price,
    trend_bias,
    current_rsi,
    volume_multiple,
    market_structure,
    distance_to_support,
    ema_21,
    ema_55,
):
    score = 0
    positive_reasons = []
    negative_reasons = []
    support_distance_label = classify_support_distance(distance_to_support)

    if support_distance_label == "At Support":
        score += 25
        positive_reasons.append("✓ At support")
    elif support_distance_label == "Near Support":
        score += 20
        positive_reasons.append("✓ Near support")
    elif support_distance_label == "Approaching Support":
        score += 15
        positive_reasons.append("✓ Approaching support")
    else:
        negative_reasons.append("✗ Far from support")

    if trend_bias == "Bullish":
        score += 20
        positive_reasons.append("✓ Bullish trend")
    elif trend_bias == "Neutral":
        score += 10
        positive_reasons.append("✓ Neutral trend")
    else:
        negative_reasons.append("✗ Bearish trend")

    if 40 <= current_rsi <= 55:
        score += 20
        positive_reasons.append("✓ RSI favorable")
    elif 30 <= current_rsi < 40:
        score += 14
        positive_reasons.append("✓ RSI near oversold")
    elif 55 < current_rsi <= 65:
        score += 10
        positive_reasons.append("✓ RSI constructive")
    else:
        negative_reasons.append("✗ RSI not ideal for accumulation")

    if volume_multiple >= 1.2:
        score += 15
        positive_reasons.append("✓ Volume confirming")
    elif volume_multiple >= 0.8:
        score += 10
        positive_reasons.append("✓ Volume neutral")
    else:
        score += 5
        negative_reasons.append("✗ Volume weak")

    if market_structure == "Range Bound":
        score += 20
        positive_reasons.append("✓ Range-bound structure")
    elif market_structure == "Higher Highs / Higher Lows":
        score += 15
        positive_reasons.append("✓ Higher highs / higher lows")
    else:
        score += 5
        negative_reasons.append("✗ Lower highs / lower lows")

    if current_price > ema_21:
        positive_reasons.append("✓ Above EMA21")
    else:
        negative_reasons.append("✗ Below EMA21")

    if current_price > ema_55:
        positive_reasons.append("✓ Above EMA55")
    else:
        negative_reasons.append("✗ Below EMA55")

    grade, label = grade_accumulation(score)
    return {
        "score": min(score, 100),
        "grade": grade,
        "label": label,
        "support_distance_label": support_distance_label,
        "positive_reasons": positive_reasons,
        "negative_reasons": negative_reasons,
    }


def format_score_breakdown(positive_reasons, negative_reasons):
    lines = positive_reasons[:]
    if positive_reasons and negative_reasons:
        lines.append("")
    lines.extend(negative_reasons)
    return "\n".join(lines)


def calculate_overall_confidence(
    trend_bias,
    market_structure_label,
    current_rsi,
    volume_multiple,
    distance_to_support,
    distance_to_resistance,
):
    confidence = 0

    if trend_bias == "Bullish":
        confidence += 22
    elif trend_bias == "Neutral":
        confidence += 14
    else:
        confidence += 8

    if market_structure_label in {"Accumulating", "Range Bound", "Trending Higher"}:
        confidence += 22
    elif market_structure_label in {"Approaching Support", "Approaching Resistance"}:
        confidence += 15
    else:
        confidence += 8

    if 40 <= current_rsi <= 60:
        confidence += 18
    elif 30 <= current_rsi < 40 or 60 < current_rsi <= 70:
        confidence += 12
    else:
        confidence += 6

    if volume_multiple >= 1.2:
        confidence += 14
    elif volume_multiple >= 0.8:
        confidence += 10
    else:
        confidence += 5

    if distance_to_support is not None and distance_to_support <= 10:
        confidence += 14
    elif distance_to_support is not None and distance_to_support <= 20:
        confidence += 9
    else:
        confidence += 4

    if distance_to_resistance is not None and distance_to_resistance >= 10:
        confidence += 10
    elif distance_to_resistance is not None and distance_to_resistance >= 5:
        confidence += 6
    else:
        confidence += 3

    return min(confidence, 100)


def get_best_use_cases(accumulation_grade, support_distance_label, range_position, trend_bias, market_structure):
    if range_position == "Near Resistance":
        return ["✓ Trim Position", "✓ Wait For Pullback"]
    if accumulation_grade in {"A", "B"} and support_distance_label in {"At Support", "Near Support"}:
        return ["✓ DCA", "✓ Long-Term Hold", "✗ Breakout Trade"]
    if trend_bias == "Bullish" and market_structure == "Higher Highs / Higher Lows":
        return ["✓ Long-Term Hold", "✓ Wait For Pullback"]
    return ["✓ Watch Only"]


def format_best_use_cases(use_cases):
    return "\n".join(use_cases)


def get_rsi_trend(direction, current_rsi):
    if direction == "LONG":
        if current_rsi > 50:
            return "Aligned bullish"
        return "Not aligned for long"

    if current_rsi < 50:
        return "Aligned bearish"
    return "Not aligned for short"


def get_ema_trend(direction, ema_21, ema_55):
    if ema_21 > ema_55:
        trend = "Bullish"
    elif ema_21 < ema_55:
        trend = "Bearish"
    else:
        trend = "Neutral"

    aligned = (
        direction == "LONG" and trend == "Bullish"
    ) or (
        direction == "SHORT" and trend == "Bearish"
    )
    return f"{trend} EMA trend" if aligned else f"{trend} EMA trend, not aligned"


def score_rsi(direction, current_rsi):
    if direction == "LONG":
        if 50 <= current_rsi <= 70:
            return 20
        if 45 <= current_rsi < 50 or 70 < current_rsi <= 75:
            return 14
        if current_rsi > 75:
            return 8
        return 5

    if 30 <= current_rsi <= 50:
        return 20
    if 50 < current_rsi <= 55 or 25 <= current_rsi < 30:
        return 14
    if current_rsi < 25:
        return 8
    return 5


def score_ema_alignment(direction, ema_21, ema_55):
    if direction == "LONG" and ema_21 > ema_55:
        return 20
    if direction == "SHORT" and ema_21 < ema_55:
        return 20

    return 5


def score_volume(volume_multiple):
    if volume_multiple >= 2:
        return 40
    if volume_multiple >= 1.5:
        return 32
    if volume_multiple >= 1:
        return 20
    if volume_multiple >= 0.75:
        return 8

    return 0


def get_volume_status(volume_multiple):
    if volume_multiple >= 2:
        return "Strong confirmation volume"
    if volume_multiple >= 1.5:
        return "Good confirmation volume"
    if volume_multiple >= 1:
        return "Average confirmation volume"

    return "Below-average volume"


def score_confirmation_candle(direction, candle):
    timestamp, open_price, high, low, close, volume = candle
    candle_range = high - low
    if candle_range <= 0:
        return 5

    body_ratio = abs(close - open_price) / candle_range
    directional_close = (
        direction == "LONG" and close > open_price
    ) or (
        direction == "SHORT" and close < open_price
    )

    if not directional_close:
        return 0
    if body_ratio >= 0.65:
        return 10
    if body_ratio >= 0.45:
        return 8
    if body_ratio >= 0.25:
        return 5

    return 2


def score_retest_quality(level, confirmation_close, atr_14):
    if atr_14 <= 0:
        return 0, "Unknown"

    distance_from_level = abs(confirmation_close - level)
    distance_in_atr = distance_from_level / atr_14

    if distance_in_atr <= 0.25:
        return 10, "Excellent, close to broken level"
    if distance_in_atr <= 0.5:
        return 8, "Good, near broken level"
    if distance_in_atr <= 1:
        return 5, "Fair, somewhat extended"

    return 1, "Weak, extended from broken level"


def get_recent_range(candles, lookback=50):
    range_candles = candles[-lookback:] if len(candles) >= lookback else candles
    highs = [candle[2] for candle in range_candles]
    lows = [candle[3] for candle in range_candles]
    return min(lows), max(highs)


def get_range_location(close, range_low, range_high):
    range_size = range_high - range_low
    if range_size <= 0:
        return "Unknown", 0.5

    position = (close - range_low) / range_size
    if position <= 0.2:
        return "Lower Range", position
    if position >= 0.8:
        return "Upper Range", position

    return "Middle Range", position


def get_next_target(direction, close, range_low, range_high):
    range_size = range_high - range_low
    if range_size <= 0:
        return close

    if direction == "LONG":
        if close < range_high:
            return range_high
        return close + range_size * 0.5

    if close > range_low:
        return range_low
    return close - range_size * 0.5


def get_distance_to_target_pct(direction, close, next_target):
    if close == 0:
        return 0

    if direction == "LONG":
        distance = max(next_target - close, 0)
    else:
        distance = max(close - next_target, 0)

    return distance / close * 100


def get_room_to_target(distance_to_target_pct):
    if distance_to_target_pct >= 1:
        return "Excellent"
    if distance_to_target_pct >= 0.4:
        return "Good"
    return "Limited"


def get_location_quality(location_label, room_to_target):
    if room_to_target == "Excellent":
        return "A"
    if room_to_target == "Good":
        return "B"
    return "C"


def get_range_context(direction, close, range_low, range_high):
    range_position, range_position_value = get_range_location(close, range_low, range_high)
    next_target = get_next_target(direction, close, range_low, range_high)
    distance_to_target_pct = get_distance_to_target_pct(direction, close, next_target)
    room_to_target = get_room_to_target(distance_to_target_pct)
    location_quality = get_location_quality(range_position, room_to_target)

    return {
        "range_low": range_low,
        "range_high": range_high,
        "range_position": range_position,
        "range_position_value": range_position_value,
        "next_target": next_target,
        "distance_to_target_pct": distance_to_target_pct,
        "room_to_target": room_to_target,
        "location_quality": location_quality,
    }


def get_location_filter(direction, close, low, range_low, range_high, level):
    range_context = get_range_context(direction, close, range_low, range_high)
    location_label = range_context["range_position"]
    breaks_beyond_range = (
        direction == "LONG" and close > range_high
    ) or (
        direction == "SHORT" and close < range_low
    )

    if breaks_beyond_range:
        return {
            "allowed": True,
            "label": range_context["range_position"],
            "note": "Break confirmed with room to next target",
            **range_context,
        }

    if direction == "SHORT":
        wicked_below_and_reclaimed = low < level and close >= level
        if location_label == "Lower Range" or wicked_below_and_reclaimed:
            return {
                "allowed": False,
                "label": "Lower Range",
                "note": "Late Move / Exhaustion Risk",
                **range_context,
                "location_quality": "C",
            }

    if direction == "LONG" and location_label == "Upper Range":
        return {
            "allowed": False,
            "label": "Upper Range",
            "note": "Late Move / Exhaustion Risk",
            **range_context,
            "location_quality": "C",
        }

    return {
        "allowed": True,
        "label": location_label,
        "note": "Break confirmed with room to next target",
        **range_context,
    }


def run_test_mode_location_filter_examples():
    print("\nTEST MODE location filter examples")
    examples = [
        {
            "name": "1. Bearish break near range low",
            "direction": "SHORT",
            "close": 82,
            "low": 81,
            "range_low": 80,
            "range_high": 100,
            "level": 83,
            "expected": "Late Move / Exhaustion Risk",
        },
        {
            "name": "2. Bearish break below middle with room to support",
            "direction": "SHORT",
            "close": 91,
            "low": 90.5,
            "range_low": 80,
            "range_high": 100,
            "level": 92,
            "expected": "Bearish confirmation",
        },
        {
            "name": "3. Bullish break near range high",
            "direction": "LONG",
            "close": 98,
            "low": 96,
            "range_low": 80,
            "range_high": 100,
            "level": 97,
            "expected": "Late Move / Exhaustion Risk",
        },
        {
            "name": "4. Bullish break above middle with room to resistance",
            "direction": "LONG",
            "close": 89,
            "low": 87,
            "range_low": 80,
            "range_high": 100,
            "level": 88,
            "expected": "Bullish confirmation",
        },
    ]

    for example in examples:
        result = get_location_filter(
            example["direction"],
            example["close"],
            example["low"],
            example["range_low"],
            example["range_high"],
            example["level"],
        )
        actual = (
            "Late Move / Exhaustion Risk"
            if not result["allowed"]
            else (
                "Bullish confirmation"
                if example["direction"] == "LONG"
                else "Bearish confirmation"
            )
        )
        status = "PASS" if actual == example["expected"] else "CHECK"
        print(
            f"{status}: {example['name']} | "
            f"Expected: {example['expected']} | Actual: {actual} | "
            f"Location: {result['label']} | Note: {result['note']}"
        )
    print()


def classify_setup(direction, confidence_score):
    if confidence_score < 55:
        return "Neutral"
    if direction == "LONG":
        return "Bullish"

    return "Bearish"


def trade_quality_rating(confidence_score, volume_multiple):
    if volume_multiple < 1:
        return "Avoid"
    if confidence_score >= 90:
        return "A+"
    if confidence_score >= 80:
        return "A"
    if confidence_score >= 68:
        return "B"
    if confidence_score >= 55:
        return "C"

    return "Avoid"


def score_close_strength_beyond_level(direction, close, level, atr_14):
    if atr_14 <= 0:
        return 0

    if direction == "LONG":
        distance_beyond_level = max(close - level, 0)
    else:
        distance_beyond_level = max(level - close, 0)

    distance_in_atr = distance_beyond_level / atr_14
    if distance_in_atr >= 0.75:
        return 15
    if distance_in_atr >= 0.5:
        return 12
    if distance_in_atr >= 0.25:
        return 8
    if distance_in_atr > 0:
        return 4
    return 0


def score_distance_to_target(distance_to_target_pct):
    if distance_to_target_pct >= 1:
        return 10
    if distance_to_target_pct >= 0.4:
        return 7
    if distance_to_target_pct > 0:
        return 3
    return 0


def calculate_break_strength(
    direction,
    close,
    level,
    atr_14,
    current_rsi,
    ema_21,
    ema_55,
    volume_multiple,
    retest_score,
    distance_to_target_pct,
):
    volume_strength = min(score_volume(volume_multiple), 30)
    rsi_alignment = score_rsi(direction, current_rsi)
    ema_alignment = 15 if score_ema_alignment(direction, ema_21, ema_55) == 20 else 3
    close_strength = score_close_strength_beyond_level(direction, close, level, atr_14)
    retest_strength = min(retest_score, 10)
    target_room = score_distance_to_target(distance_to_target_pct)

    return min(
        100,
        volume_strength
        + rsi_alignment
        + ema_alignment
        + close_strength
        + retest_strength
        + target_room,
    )


def is_rsi_aligned(direction, current_rsi):
    return (direction == "LONG" and current_rsi > 50) or (
        direction == "SHORT" and current_rsi < 50
    )


def is_ema_aligned(direction, ema_21, ema_55):
    return (direction == "LONG" and ema_21 > ema_55) or (
        direction == "SHORT" and ema_21 < ema_55
    )


def is_poor_range_location(direction, range_context):
    range_position = range_context.get("range_position") or range_context.get("label")
    return (direction == "LONG" and range_position == "Upper Range") or (
        direction == "SHORT" and range_position == "Lower Range"
    )


def setup_quality_status(setup_quality):
    if setup_quality in {"A+", "A"}:
        return "High Interest Setup"
    if setup_quality == "B":
        return "Watch Closely"
    if setup_quality == "C":
        return "Watch Only"
    if setup_quality in {"D", "F"}:
        return "Weak Setup / Avoid Chasing"
    return "Watch Closely"


def setup_quality_from_score(break_strength_score):
    if break_strength_score >= 90:
        return "A+"
    if break_strength_score >= 80:
        return "A"
    if break_strength_score >= 70:
        return "B"
    if break_strength_score >= 60:
        return "C"
    if break_strength_score >= 50:
        return "D"
    return "F"


def adjusted_break_strength_for_setup(
    break_strength_score,
    direction,
    volume_multiple,
    current_rsi,
    ema_21,
    ema_55,
    range_context,
):
    adjusted_score = break_strength_score
    room_to_target = range_context.get("room_to_target", "Limited")
    poor_location = is_poor_range_location(direction, range_context)
    weak_volume = volume_multiple < 1
    weak_momentum = not is_rsi_aligned(direction, current_rsi) or not is_ema_aligned(
        direction, ema_21, ema_55
    )

    if poor_location:
        adjusted_score = min(adjusted_score, 59)
    if room_to_target == "Limited" and volume_multiple < 2:
        adjusted_score = min(adjusted_score, 69)
    if weak_momentum and weak_volume:
        adjusted_score = min(adjusted_score, 49)

    return adjusted_score


def grade_setup_quality(
    direction,
    break_strength_score,
    volume_multiple,
    current_rsi,
    ema_21,
    ema_55,
    range_context,
):
    return setup_quality_from_score(break_strength_score)


def build_setup_warning(
    direction,
    setup_quality,
    range_context,
    volume_multiple,
    current_rsi,
    ema_21,
    ema_55,
):
    warnings = []
    failed_break_text = "failed breakout" if direction == "LONG" else "failed breakdown"

    if setup_quality in {"D", "F"}:
        warnings.append("Weak setup. Avoid chasing this setup.")
    if range_context.get("room_to_target") == "Limited":
        warnings.append("Limited room to target.")
    if is_poor_range_location(direction, range_context):
        warnings.append(f"Price is in a poor range location. Watch for rejection or {failed_break_text}.")
    if volume_multiple < 1:
        warnings.append("Volume is weak.")
    if not is_rsi_aligned(direction, current_rsi):
        warnings.append("RSI is not aligned yet.")
    if not is_ema_aligned(direction, ema_21, ema_55):
        warnings.append("EMA trend is not aligned yet.")

    if not warnings:
        warnings.append("Momentum and location are favorable. Wait for confirmation.")

    return "\n".join(f"- {warning}" for warning in warnings)


def build_setup_quality_snapshot(
    direction,
    level,
    current_candle,
    atr_14,
    ema_21,
    ema_55,
    current_rsi,
    volume_avg,
    range_context,
):
    current_close = current_candle[4]
    current_volume = current_candle[5]
    volume_multiple = current_volume / volume_avg if volume_avg > 0 else 0
    break_strength_score = calculate_break_strength(
        direction,
        current_close,
        level,
        atr_14,
        current_rsi,
        ema_21,
        ema_55,
        volume_multiple,
        4,
        range_context.get("distance_to_target_pct", 0),
    )
    break_strength_score = adjusted_break_strength_for_setup(
        break_strength_score,
        direction,
        volume_multiple,
        current_rsi,
        ema_21,
        ema_55,
        range_context,
    )
    setup_quality = grade_setup_quality(
        direction,
        break_strength_score,
        volume_multiple,
        current_rsi,
        ema_21,
        ema_55,
        range_context,
    )

    return {
        "setup_quality": setup_quality,
        "setup_status": setup_quality_status(setup_quality),
        "break_strength_score": break_strength_score,
        "volume_multiple": volume_multiple,
        "warning": build_setup_warning(
            direction,
            setup_quality,
            range_context,
            volume_multiple,
            current_rsi,
            ema_21,
            ema_55,
        ),
    }


def is_stalling_near_level(close, level, atr_14):
    if atr_14 <= 0:
        return False
    return abs(close - level) <= atr_14 * 0.25


def build_trade_plan(
    direction,
    level,
    first_candle,
    confirmation_candle,
    atr_14,
    ema_21,
    ema_55,
    current_rsi,
    volume_avg,
    location_filter,
):
    first_timestamp, first_open, first_high, first_low, first_close, first_volume = first_candle
    (
        confirmation_timestamp,
        confirmation_open,
        confirmation_high,
        confirmation_low,
        confirmation_close,
        confirmation_volume,
    ) = confirmation_candle
    entry = confirmation_close
    atr_buffer = atr_14 * 0.25
    volume_multiple = confirmation_volume / volume_avg if volume_avg > 0 else 0
    retest_score, retest_quality = score_retest_quality(
        level, confirmation_close, atr_14
    )
    break_strength_score = calculate_break_strength(
        direction,
        confirmation_close,
        level,
        atr_14,
        current_rsi,
        ema_21,
        ema_55,
        volume_multiple,
        retest_score,
        location_filter.get("distance_to_target_pct", 0),
    )
    break_strength_score = adjusted_break_strength_for_setup(
        break_strength_score,
        direction,
        volume_multiple,
        current_rsi,
        ema_21,
        ema_55,
        location_filter,
    )
    setup_quality = grade_setup_quality(
        direction,
        break_strength_score,
        volume_multiple,
        current_rsi,
        ema_21,
        ema_55,
        location_filter,
    )

    if direction == "LONG":
        entry_zone_low = min(level, confirmation_close)
        entry_zone_high = max(level, confirmation_close)
        stop_loss = min(level, first_low, confirmation_low) - atr_buffer
        risk = abs(entry - stop_loss)
        tp1 = entry + risk
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3
    else:
        entry_zone_low = min(confirmation_close, level)
        entry_zone_high = max(confirmation_close, level)
        stop_loss = max(level, first_high, confirmation_high) + atr_buffer
        risk = abs(entry - stop_loss)
        tp1 = entry - risk
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3

    confidence_score = (
        score_rsi(direction, current_rsi)
        + score_ema_alignment(direction, ema_21, ema_55)
        + score_volume(volume_multiple)
        + score_confirmation_candle(direction, confirmation_candle)
        + retest_score
    )
    if volume_multiple < 1:
        confidence_score = min(confidence_score, 45)

    return {
        "direction": direction,
        "classification": classify_setup(direction, confidence_score),
        "confidence_score": confidence_score,
        "break_strength_score": break_strength_score,
        "setup_quality": setup_quality,
        "setup_status": setup_quality_status(setup_quality),
        "trade_quality": trade_quality_rating(confidence_score, volume_multiple),
        "level": level,
        "first_close": first_close,
        "confirmation_close": confirmation_close,
        "entry": entry,
        "entry_zone_low": entry_zone_low,
        "entry_zone_high": entry_zone_high,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "volume_multiple": volume_multiple,
        "volume_status": get_volume_status(volume_multiple),
        "rsi": current_rsi,
        "rsi_trend": get_rsi_trend(direction, current_rsi),
        "ema_21": ema_21,
        "ema_55": ema_55,
        "ema_trend": get_ema_trend(direction, ema_21, ema_55),
        "retest_quality": retest_quality,
        "weak_volume": volume_multiple < 1,
        "failed_follow_through": (
            volume_multiple < 1 and is_stalling_near_level(confirmation_close, level, atr_14)
        ),
    }


def candle_body_percent(open_price, close):
    if open_price == 0:
        return 0

    return abs(close - open_price) / open_price * 100


def build_alert(symbol, candle, alert, ema_21, ema_55, current_rsi, volume_avg):
    timestamp, open_price, high, low, close, volume = candle
    test_mode_text = "🧪 <b>TEST MODE</b>\n" if TEST_MODE else ""
    time_text = alert_time_text(timestamp)
    if alert.get("type", "").endswith(":weak_break"):
        trade_plan = alert["trade_plan"]
        location = alert.get("location_filter", {})
        return (
            f"⚠️ <b>{symbol} Weak Break / Watch Only</b>\n\n"
            f"{test_mode_text}"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Timeframe:</b> 15m\n"
            f"{time_text}"
            f"<b>Direction:</b> {trade_plan['direction']}\n"
            f"<b>Level:</b> {format_level(trade_plan['level'])}\n"
            f"<b>Close:</b> {format_level(close)}\n"
            f"<b>Setup Quality:</b> {trade_plan['setup_quality']}\n"
            f"<b>Setup Status:</b> {trade_plan['setup_status']}\n"
            f"<b>Break Strength Score:</b> {trade_plan['break_strength_score']}/100\n"
            f"<b>Volume status:</b> {trade_plan['volume_status']}\n"
            f"<b>RSI status:</b> {trade_plan['rsi_trend']}\n"
            f"<b>EMA trend:</b> {trade_plan['ema_trend']}\n"
            f"<b>Next key level:</b> {format_level(location.get('next_target', close))}\n\n"
            f"<b>Reason:</b> Break detected, but momentum/volume did not confirm.\n"
            f"<b>Action:</b> Watch only / No trade confirmation"
        )

    if alert.get("type", "").endswith(":failed_follow_through"):
        trade_plan = alert["trade_plan"]
        location = alert.get("location_filter", {})
        return (
            f"⚠️ <b>{symbol} Failed Follow-Through</b>\n\n"
            f"{test_mode_text}"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Timeframe:</b> 15m\n"
            f"{time_text}"
            f"<b>Direction:</b> {trade_plan['direction']}\n"
            f"<b>Level:</b> {format_level(trade_plan['level'])}\n"
            f"<b>Close:</b> {format_level(close)}\n"
            f"<b>Setup Quality:</b> {trade_plan['setup_quality']}\n"
            f"<b>Setup Status:</b> {trade_plan['setup_status']}\n"
            f"<b>Break Strength Score:</b> {trade_plan['break_strength_score']}/100\n"
            f"<b>Volume status:</b> {trade_plan['volume_status']}\n"
            f"<b>RSI status:</b> {trade_plan['rsi_trend']}\n"
            f"<b>EMA trend:</b> {trade_plan['ema_trend']}\n"
            f"<b>Next key level:</b> {format_level(location.get('next_target', close))}\n\n"
            f"<b>Reason:</b> Price stalled around the broken level with weak volume.\n"
            f"<b>Action:</b> Watch only / No trade confirmation"
        )

    if alert.get("type", "").endswith(":late_move"):
        location = alert["location_filter"]
        return (
            f"⚠️ <b>{symbol} Late Move / Exhaustion Risk</b>\n\n"
            f"{test_mode_text}"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Timeframe:</b> 15m\n"
            f"{time_text}"
            f"<b>Direction blocked:</b> {alert['blocked_direction']}\n"
            f"<b>Level:</b> {format_level(alert['level'])}\n"
            f"<b>Close:</b> {format_level(close)}\n"
            f"<b>Setup Quality:</b> {alert.get('setup_quality', 'D')}\n"
            f"<b>Setup Status:</b> {setup_quality_status(alert.get('setup_quality', 'D'))}\n"
            f"<b>Break Strength Score:</b> {alert.get('break_strength_score', 'N/A')}/100\n"
            f"<b>Range low:</b> {format_level(location['range_low'])}\n"
            f"<b>Range high:</b> {format_level(location['range_high'])}\n"
            f"<b>Range Position:</b> {location['label']}\n\n"
            f"Avoid chasing. Watch for reclaim, rejection, or reversal."
        )

    trade_plan = alert.get("trade_plan")
    if trade_plan:
        location = alert.get("location_filter", {})
        location_text = ""
        if location:
            location_text = (
                f"<b>Range Position:</b> {location['label']}\n"
                f"<b>Range low:</b> {format_level(location['range_low'])}\n"
                f"<b>Range high:</b> {format_level(location['range_high'])}\n\n"
                f"<b>Room To Target:</b> {location['room_to_target']}\n"
                f"<b>Location Quality:</b> {location['location_quality']}\n"
                f"<b>Next Target:</b> {format_level(location['next_target'])}\n"
                f"<b>Distance To Next Target:</b> "
                f"{location['distance_to_target_pct']:.2f}%\n\n"
            )

        return (
            f"✅ <b>{symbol} 15m Break Confirmed</b>\n\n"
            f"{test_mode_text}"
            f"{time_text}"
            f"<b>Setup:</b> {trade_plan['classification']}\n"
            f"<b>Setup Quality:</b> {trade_plan['setup_quality']}\n"
            f"<b>Setup Status:</b> {trade_plan['setup_status']}\n"
            f"<b>Confidence:</b> {trade_plan['confidence_score']}/100\n"
            f"<b>Trade quality:</b> {trade_plan['trade_quality']}\n"
            f"<b>Break Strength Score:</b> {trade_plan['break_strength_score']}/100\n"
            f"<b>Direction:</b> {trade_plan['direction']}\n"
            f"<b>Level broken:</b> {format_level(trade_plan['level'])}\n"
            f"<b>First candle close:</b> {format_level(trade_plan['first_close'])}\n"
            f"<b>Confirmation close:</b> "
            f"{format_level(trade_plan['confirmation_close'])}\n\n"
            f"<b>RSI:</b> {trade_plan['rsi']:.2f} - {trade_plan['rsi_trend']}\n"
            f"<b>EMA trend:</b> {trade_plan['ema_trend']}\n"
            f"<b>EMA21:</b> {format_level(trade_plan['ema_21'])}\n"
            f"<b>EMA55:</b> {format_level(trade_plan['ema_55'])}\n"
            f"<b>Volume:</b> {trade_plan['volume_multiple']:.2f}x - "
            f"{trade_plan['volume_status']}\n"
            f"<b>Retest quality:</b> {trade_plan['retest_quality']}\n\n"
            f"{location_text}"
            f"<b>Suggested plan:</b>\n"
            f"<b>Entry:</b> {format_level(trade_plan['entry'])}\n"
            f"<b>Entry zone:</b> {format_level(trade_plan['entry_zone_low'])} - "
            f"{format_level(trade_plan['entry_zone_high'])}\n"
            f"<b>Stop loss:</b> {format_level(trade_plan['stop_loss'])}\n"
            f"<b>TP1:</b> {format_level(trade_plan['tp1'])}\n"
            f"<b>TP2:</b> {format_level(trade_plan['tp2'])}\n"
            f"<b>TP3:</b> {format_level(trade_plan['tp3'])}\n"
            f"<b>Risk note:</b>\n"
            f"Educational alert only. Wait for your own confirmation and manage risk."
        )

    if alert.get("type") == "volume_spike":
        body_percent = candle_body_percent(open_price, close)
        if alert.get("direction") == "bullish":
            participation_text = "High volume detected. Watch for breakout confirmation."
        elif alert.get("direction") == "bearish":
            participation_text = "High selling volume detected. Watch for breakdown confirmation."
        else:
            participation_text = (
                "High volume detected. No trade confirmation yet. "
                "Watch for level break and follow-through."
            )

        return (
            f"{alert['emoji']} <b>{symbol} {alert['label']}</b>\n\n"
            f"{test_mode_text}"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Timeframe:</b> 15m\n\n"
            f"{time_text}"
            f"\n"
            f"<b>Open:</b> {format_level(open_price)}\n"
            f"<b>High:</b> {format_level(high)}\n"
            f"<b>Low:</b> {format_level(low)}\n"
            f"<b>Close:</b> {format_level(close)}\n"
            f"<b>Candle body %:</b> {body_percent:.2f}%\n\n"
            f"<b>Volume:</b> {volume:.4f}\n"
            f"<b>20-candle average:</b> {volume_avg:.4f}\n"
            f"<b>Volume multiple:</b> {alert['volume_multiple']:.2f}x\n\n"
            f"<b>RSI:</b> {current_rsi:.2f}\n"
            f"<b>RSI Status:</b> {get_rsi_status(current_rsi)}\n"
            f"<b>EMA21:</b> {format_level(ema_21)}\n"
            f"<b>EMA55:</b> {format_level(ema_55)}\n\n"
            f"{participation_text}"
        )

    level_text = ""
    if alert.get("level") is not None:
        level_text = f"🎯 <b>Level:</b> {format_level(alert['level'])}\n"

    range_text = ""
    range_context = alert.get("range_context")
    if range_context:
        range_text = (
            f"📍 <b>Range High:</b> {format_level(range_context['range_high'])}\n"
            f"📍 <b>Range Low:</b> {format_level(range_context['range_low'])}\n"
            f"📌 <b>Range Position:</b> {range_context['range_position']}\n"
            f"🎯 <b>Next Target Level:</b> "
            f"{format_level(range_context['next_target'])}\n"
            f"📏 <b>Distance To Next Target %:</b> "
            f"{range_context['distance_to_target_pct']:.2f}%\n"
        )

    detail_text = ""
    if alert.get("detail"):
        detail_text = f"📝 <b>Note:</b> {alert['detail']}\n"

    setup_text = ""
    if alert.get("setup_quality"):
        setup_text = (
            f"⭐ <b>Setup Quality:</b> {alert['setup_quality']}\n"
            f"📌 <b>Setup Status:</b> {alert.get('setup_status', setup_quality_status(alert['setup_quality']))}\n"
            f"💪 <b>Break Strength:</b> {alert.get('break_strength_score', 'N/A')}/100\n"
        )

    warning_text = ""
    if alert.get("warning"):
        warning_text = f"\n⚠️ <b>Warning:</b>\n{alert['warning']}\n"

    return (
        f"{alert['emoji']} <b>{symbol} {alert['label']}</b>\n"
        f"{test_mode_text}"
        f"{detail_text}"
        f"{setup_text}"
        f"🏷️ <b>Symbol:</b> {symbol}\n"
        f"⏱️ <b>Timeframe:</b> 15m\n"
        f"🕯️ {time_text}"
        f"{level_text}"
        f"{range_text}"
        f"{warning_text}"
        f"💵 <b>Close:</b> {close:.6g}\n"
        f"📈 <b>EMA 21:</b> {ema_21:.6g}\n"
        f"📉 <b>EMA 55:</b> {ema_55:.6g}\n"
        f"📊 <b>RSI 14:</b> {current_rsi:.2f}\n"
        f"📊 <b>RSI Status:</b> {get_rsi_status(current_rsi)}\n"
        f"🔊 <b>Volume:</b> {volume:.4f}\n"
        f"📦 <b>20-candle avg volume:</b> {volume_avg:.4f}"
    )


def print_confirmation_debug(symbol, alert, candle, ema_21, ema_55, current_rsi, volume_avg):
    if not DEBUG:
        return

    location_filter = alert.get("location_filter", {})
    trade_plan = alert.get("trade_plan", {})
    direction = alert.get("blocked_direction") or trade_plan.get("direction", "UNKNOWN")
    close = candle[4]
    volume_multiple = (
        trade_plan.get("volume_multiple")
        if trade_plan
        else candle[5] / volume_avg
        if volume_avg > 0
        else 0
    )
    confidence = trade_plan.get("confidence_score", "N/A")
    break_strength = trade_plan.get("break_strength_score") or alert.get(
        "break_strength_score", "N/A"
    )
    setup_quality = trade_plan.get("setup_quality") or alert.get("setup_quality", "N/A")
    decision = "ACCEPTED" if trade_plan else "REJECTED"
    if alert.get("type", "").endswith(":confirmation"):
        reason = "Break confirmed with room to next target"
    elif alert.get("type", "").endswith(":failed_follow_through"):
        reason = "Price stalled around the broken level with weak volume"
        decision = "REJECTED"
    elif alert.get("type", "").endswith(":weak_break"):
        reason = "Break detected, but momentum/volume did not confirm"
        decision = "REJECTED"
    else:
        reason = "Late Move / Exhaustion Risk"
    ema_trend = trade_plan.get("ema_trend") or get_ema_trend(direction, ema_21, ema_55)

    print("Confirmation debug")
    print(f"Symbol: {symbol}")
    print(f"Direction: {direction}")
    print(f"Level broken: {format_level(alert.get('level', close))}")
    print(f"Range position: {location_filter.get('label', 'Unknown')}")
    print(f"Confidence: {confidence}")
    print(f"Setup Quality: {setup_quality}")
    print(f"Break Strength Score: {break_strength}")
    print(f"Volume multiple: {volume_multiple:.2f}x")
    print(f"RSI: {current_rsi:.2f}")
    print(f"EMA trend: {ema_trend}")
    print(f"Decision: {decision}")
    print(f"Reason: {reason}")


def get_scan_decision(sent_alert_labels):
    if not sent_alert_labels:
        return "NO ALERT", "No break, no confirmation, or filters not met."

    return "ALERT SENT", ", ".join(sent_alert_labels)


def is_break_attempt_alert(alert):
    return alert.get("type", "").endswith(":early_warning") and alert.get("label") in {
        "Breakout Attempt",
        "Breakdown Attempt",
    }


def is_ema_cross_alert(alert):
    return alert.get("type") in {"ema_cross_above", "ema_cross_below"}


def has_volume_alert_context(alerts, active_trade_status=None):
    if active_trade_status in {"Retest Holding", "Retest Failed"}:
        return True

    return any(
        is_break_attempt_alert(alert) or is_ema_cross_alert(alert)
        for alert in alerts
        if alert.get("type") != "volume_spike"
    )


def should_send_telegram_alert(alert, alerts, active_trade_status=None):
    if alert.get("type") != "volume_spike":
        return True

    return has_volume_alert_context(alerts, active_trade_status)


def log_suppressed_volume_alert(symbol, candle, alert, volume_avg, reason):
    timestamp, open_price, high, low, close, volume = candle
    volume_multiple = alert.get("volume_multiple")
    if volume_multiple is None:
        volume_multiple = volume / volume_avg if volume_avg > 0 else 0

    print(
        "Volume event logged - "
        f"{symbol} {eastern_time_from_timestamp(timestamp)} - "
        f"{alert.get('label', 'High Volume Alert')} - "
        f"Vol {volume_multiple:.2f}x - {reason}"
    )


def compact_range_label(range_position):
    if range_position == "Middle Range":
        return "Mid range"
    if range_position == "Lower Range":
        return "Lower range"
    if range_position == "Upper Range":
        return "Upper range"
    return range_position


def build_compact_scan_line(symbol, candle, current_rsi, volume_avg, range_low, range_high, sent_alert_labels):
    timestamp, open_price, high, low, close, volume = candle
    volume_multiple = volume / volume_avg if volume_avg > 0 else 0
    range_position, _ = get_range_location(close, range_low, range_high)
    alert_text = ", ".join(sent_alert_labels) if sent_alert_labels else "No alert"
    short_symbol = symbol.split("/")[0]
    return (
        f"{short_symbol}: {alert_text} | {compact_range_label(range_position)} | "
        f"Vol {volume_multiple:.2f}x | RSI {current_rsi:.0f}"
    )


def should_print_full_scan_debug(sent_alert_types, tracking_is_active):
    important_suffixes = (
        ":early_warning",
        ":confirmation",
        ":late_move",
        ":weak_break",
        ":failed_follow_through",
    )
    return tracking_is_active or any(
        alert_type.endswith(important_suffixes) for alert_type in sent_alert_types
    )


def print_compact_scan_summary(lines):
    if not lines:
        return

    print(f"\n[{scan_header_time()} SCAN]")
    for line in lines:
        print(line)


def build_levels_command_message(exchange, symbol):
    closed_candles = fetch_closed_ohlcv(exchange, symbol, TIMEFRAME, CANDLE_LIMIT)
    if len(closed_candles) < 80:
        raise RuntimeError(f"Not enough candle history for {symbol}")

    four_hour_candles = fetch_closed_ohlcv(
        exchange,
        symbol,
        "4h",
        180,
        fallback=closed_candles[-100:],
    )
    daily_candles = fetch_closed_ohlcv(
        exchange,
        symbol,
        "1d",
        180,
        fallback=closed_candles[-100:],
    )
    weekly_candles = fetch_closed_ohlcv(
        exchange,
        symbol,
        "1w",
        104,
        fallback=daily_candles[-60:],
    )
    latest_closed = closed_candles[-1]
    current_price = get_current_market_price(exchange, symbol, latest_closed[4])
    daily_closes = [candle[4] for candle in daily_candles]
    if len(daily_closes) >= 55:
        analysis_candles = daily_candles
        analysis_closes = daily_closes
        ema_timeframe = "Daily"
    else:
        analysis_candles = closed_candles
        analysis_closes = [candle[4] for candle in closed_candles]
        ema_timeframe = "15m fallback"

    ema_21 = ema(analysis_closes, 21)
    ema_55 = ema(analysis_closes, 55)
    current_rsi = rsi(analysis_closes, 14)
    previous_20_volumes = [candle[5] for candle in closed_candles[-21:-1]]
    volume_average = sum(previous_20_volumes) / len(previous_20_volumes)
    current_volume = latest_closed[5]
    volume_multiple = current_volume / volume_average if volume_average > 0 else 0
    volume_status = get_volume_status(volume_multiple)
    trend_bias = get_trend_bias(current_price, ema_21, ema_55, current_rsi)
    rsi_status = get_rsi_status(current_rsi)
    market_structure = get_market_structure(analysis_candles)
    zones = build_market_level_zones(current_price, four_hour_candles, daily_candles, weekly_candles)
    range_low, range_high = zones["current_range"]
    buy_zones = zones["buy_zones"]
    resistance_zones = zones["resistance_zones"]
    range_position = get_range_position_label(current_price, range_low, range_high)
    nearest_support = format_zone(buy_zones[0]) if buy_zones else "None nearby"
    nearest_resistance = format_zone(resistance_zones[0]) if resistance_zones else "None nearby"
    distance_to_support = calculate_distance_to_zone_pct(
        current_price, buy_zones[0] if buy_zones else None
    )
    distance_to_resistance = calculate_distance_to_zone_pct(
        current_price, resistance_zones[0] if resistance_zones else None
    )
    trend_reasons = build_trend_reasons(trend_bias, current_price, ema_21, ema_55, current_rsi)
    momentum_label = get_momentum_label(current_rsi, ema_21, ema_55)
    volume_confirmation = get_volume_confirmation_label(volume_multiple)
    accumulation = score_accumulation_setup(
        current_price,
        trend_bias,
        current_rsi,
        volume_multiple,
        market_structure,
        distance_to_support,
        ema_21,
        ema_55,
    )
    support_distance_label = accumulation["support_distance_label"]
    current_location = get_current_location(
        current_price,
        buy_zones,
        resistance_zones,
        support_distance_label,
        distance_to_resistance,
    )
    market_structure_label = get_market_structure_label(
        market_structure,
        support_distance_label,
        distance_to_resistance,
    )
    overall_confidence = calculate_overall_confidence(
        trend_bias,
        market_structure_label,
        current_rsi,
        volume_multiple,
        distance_to_support,
        distance_to_resistance,
    )
    best_use_cases = get_best_use_cases(
        accumulation["grade"],
        support_distance_label,
        range_position,
        trend_bias,
        market_structure,
    )
    summary = build_market_summary(
        symbol,
        current_price,
        current_location,
        support_distance_label,
        trend_bias,
        ema_21,
        ema_55,
    )

    return (
        f"📍 <b>{symbol} Market Levels</b>\n\n"
        f"{alert_time_text(latest_closed[0])}"
        f"<b>Current Price:</b>\n"
        f"{format_zone_price(current_price)}\n\n"
        f"<b>Current Location:</b>\n"
        f"{current_location}\n\n"
        f"<b>Trend:</b>\n"
        f"{trend_bias}\n\n"
        f"<b>Reason:</b>\n"
        f"{format_trend_reasons(trend_reasons)}\n\n"
        f"<b>Overall Confidence:</b> {overall_confidence}%\n\n"
        f"🧱 <b>Accumulation Rating:</b> {accumulation['grade']}\n"
        f"{accumulation['label']}\n\n"
        f"🧠 <b>Summary</b>\n"
        f"{summary}\n\n"
        f"📊 <b>Market Structure</b>\n"
        f"<b>Structure:</b> {market_structure_label}\n"
        f"<b>Position:</b> {support_distance_label}\n"
        f"<b>Nearest Support:</b> {nearest_support}\n"
        f"<b>Nearest Resistance:</b> {nearest_resistance}\n"
        f"<b>Distance To Nearest Support:</b> "
        f"{format_distance_pct(distance_to_support)} ({support_distance_label})\n"
        f"<b>Distance To Nearest Resistance:</b> {format_distance_pct(distance_to_resistance)}\n"
        f"<b>Volume:</b> {volume_status} ({volume_multiple:.2f}x)\n\n"
        f"🟢 <b>Accumulation Zones</b>\n"
        f"{format_numbered_zones('Zone', buy_zones)}\n"
        f"🔴 <b>Distribution Zones</b>\n"
        f"{format_numbered_zones('Zone', resistance_zones)}\n"
        f"<b>EMA Information</b>\n"
        f"<b>EMA Timeframe:</b> {ema_timeframe}\n"
        f"<b>EMA21:</b> {format_zone_price(ema_21)}\n"
        f"<b>EMA55:</b> {format_zone_price(ema_55)}\n\n"
        f"<b>RSI Information</b>\n"
        f"<b>RSI:</b> {current_rsi:.2f}\n"
        f"<b>RSI Status:</b> {rsi_status}\n\n"
        f"<b>Score Breakdown</b>\n"
        f"{format_score_breakdown(accumulation['positive_reasons'], accumulation['negative_reasons'])}\n\n"
        f"🎯 <b>Best Use Case:</b>\n"
        f"{format_best_use_cases(best_use_cases)}\n\n"
        f"<b>Disclaimer:</b>\n"
        f"Educational market structure only. Not financial advice. Use your own risk management.\n\n"
        f"Levels Engine v1.0"
    )


def build_levels_scan_snapshot(exchange, symbol):
    closed_candles = fetch_closed_ohlcv(exchange, symbol, TIMEFRAME, CANDLE_LIMIT)
    if len(closed_candles) < 80:
        raise RuntimeError(f"Not enough candle history for {symbol}")

    four_hour_candles = fetch_closed_ohlcv(
        exchange,
        symbol,
        "4h",
        180,
        fallback=closed_candles[-100:],
    )
    daily_candles = fetch_closed_ohlcv(
        exchange,
        symbol,
        "1d",
        180,
        fallback=closed_candles[-100:],
    )
    weekly_candles = fetch_closed_ohlcv(
        exchange,
        symbol,
        "1w",
        104,
        fallback=daily_candles[-60:],
    )
    latest_closed = closed_candles[-1]
    current_price = get_current_market_price(exchange, symbol, latest_closed[4])
    daily_closes = [candle[4] for candle in daily_candles]
    if len(daily_closes) >= 55:
        analysis_candles = daily_candles
        analysis_closes = daily_closes
    else:
        analysis_candles = closed_candles
        analysis_closes = [candle[4] for candle in closed_candles]

    ema_21 = ema(analysis_closes, 21)
    ema_55 = ema(analysis_closes, 55)
    current_rsi = rsi(analysis_closes, 14)
    previous_20_volumes = [candle[5] for candle in closed_candles[-21:-1]]
    volume_average = sum(previous_20_volumes) / len(previous_20_volumes)
    current_volume = latest_closed[5]
    volume_multiple = current_volume / volume_average if volume_average > 0 else 0
    trend_bias = get_trend_bias(current_price, ema_21, ema_55, current_rsi)
    market_structure = get_market_structure(analysis_candles)
    zones = build_market_level_zones(current_price, four_hour_candles, daily_candles, weekly_candles)
    range_low, range_high = zones["current_range"]
    buy_zones = zones["buy_zones"]
    resistance_zones = zones["resistance_zones"]
    range_position = get_range_position_label(current_price, range_low, range_high)
    distance_to_support = calculate_distance_to_zone_pct(
        current_price, buy_zones[0] if buy_zones else None
    )
    distance_to_resistance = calculate_distance_to_zone_pct(
        current_price, resistance_zones[0] if resistance_zones else None
    )
    accumulation = score_accumulation_setup(
        current_price,
        trend_bias,
        current_rsi,
        volume_multiple,
        market_structure,
        distance_to_support,
        ema_21,
        ema_55,
    )
    support_distance_label = accumulation["support_distance_label"]
    current_location = get_current_location(
        current_price,
        buy_zones,
        resistance_zones,
        support_distance_label,
        distance_to_resistance,
    )
    market_structure_label = get_market_structure_label(
        market_structure,
        support_distance_label,
        distance_to_resistance,
    )
    market_score = calculate_overall_confidence(
        trend_bias,
        market_structure_label,
        current_rsi,
        volume_multiple,
        distance_to_support,
        distance_to_resistance,
    )
    strategy = get_best_use_cases(
        accumulation["grade"],
        support_distance_label,
        range_position,
        trend_bias,
        market_structure,
    )

    return {
        "symbol": symbol,
        "current_price": current_price,
        "ema_21": ema_21,
        "ema_55": ema_55,
        "rsi": current_rsi,
        "support_zones": buy_zones,
        "resistance_zones": resistance_zones,
        "market_score": market_score,
        "bias": trend_bias,
        "accumulation_grade": accumulation["grade"],
        "accumulation_label": accumulation["label"],
        "strategy": strategy,
        "location": current_location,
        "support_distance_label": support_distance_label,
        "distance_to_support": distance_to_support,
        "distance_to_resistance": distance_to_resistance,
        "market_structure": market_structure,
        "market_structure_label": market_structure_label,
    }


def handle_help_command(telegram_token, telegram_chat_id):
    help_text = (
        "🤖 Poinkle Beta\n\n"
        "Commands:\n"
        "/help - Show this help menu\n"
        "/status - Show bot status\n"
        "/levels BTC - Get market levels\n\n"
        "/scan - Top 100 market opportunities\n"
        "/scan support - Filter scan results\n\n"
        "Examples:\n"
        "/levels BTC\n"
        "/levels SOL\n"
        "/levels TAO\n"
        "/scan bearish\n\n"
        "Supported coins:\n"
        + ", ".join(symbol.replace("/USD", "") for symbol in WATCHLIST)
        + "\n\n⚠️ Beta: Poinkle is under active development."
    )
    send_telegram_message(telegram_token, telegram_chat_id, help_text)


def handle_scan_command(
    exchange,
    telegram_token,
    telegram_chat_id,
    message_text,
    source_chat=None,
):
    parts = message_text.strip().split()
    scan_filter = parts[1].lower() if len(parts) > 1 else None
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))

    log_info(f"Received {message_text.strip()}")
    log_info(f"Running Top 100 scan{f' with {scan_filter} filter' if scan_filter else ''}")

    try:
        results = scan_top_100(
            exchange,
            requests,
            build_levels_scan_snapshot,
            scan_filter=scan_filter,
            limit=10,
        )
        message = format_scan_message(results, format_zone_price, scan_filter=scan_filter)
    except Exception as error:
        log_warn(f"Error running /scan: {error}")
        message = "Top 100 scan is temporarily unavailable. Please try again soon."

    send_telegram_message(telegram_token, response_chat_id, message)


def handle_status_command(telegram_token, telegram_chat_id, state, source_chat=None):
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    send_telegram_message(
        telegram_token,
        response_chat_id,
        build_bot_status_message(state, include_details=True),
    )


def base_symbol(symbol):
    return symbol.split("/")[0]


def alert_dm_chat_id(source_chat, from_user, fallback_chat_id):
    source_chat = source_chat or {}
    if is_private_chat(source_chat):
        return str(source_chat.get("id", fallback_chat_id))
    if from_user and from_user.get("id"):
        return str(from_user["id"])
    return str(fallback_chat_id)


def alert_usage_text():
    return (
        "Use: /alerts XRP support\n"
        "Or: /alerts XRP resistance\n"
        "Or: /alerts XRP all\n"
        "Or: /alerts XRP critical\n"
        "Or: /alerts XRP off"
    )


def level_alert_confirmation(ticker, alert_type):
    if alert_type == "support":
        return (
            f"✅ Support alerts enabled for {ticker}.\n"
            f"I’ll DM you when {ticker} reaches a Poinkle accumulation/support zone."
        )
    if alert_type == "resistance":
        return (
            f"✅ Resistance alerts enabled for {ticker}.\n"
            f"I’ll DM you when {ticker} reaches a Poinkle profit-review/resistance zone."
        )
    if alert_type == "all":
        return (
            f"✅ All Poinkle level alerts enabled for {ticker}.\n"
            f"I’ll DM you when {ticker} reaches support or resistance zones."
        )
    return (
        f"✅ Critical alerts enabled for {ticker}. "
        f"I’ll DM you when {ticker} reaches an important Poinkle level."
    )


def handle_alerts_command(
    telegram_token,
    telegram_chat_id,
    message_text,
    source_chat=None,
    from_user=None,
):
    parts = message_text.strip().split()
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    from_user = from_user or {}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    user_chat_id = alert_dm_chat_id(source_chat, from_user, telegram_chat_id)

    if len(parts) == 2 and parts[1].lower() == "off":
        user_alerts = load_user_alerts()
        user_alerts.pop(user_chat_id, None)
        save_user_alerts(user_alerts)
        send_telegram_message(telegram_token, response_chat_id, "✅ All alerts turned off.")
        return

    if len(parts) < 3:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            alert_usage_text(),
        )
        return

    symbol = normalize_symbol(parts[1])
    action = parts[2].lower()
    if symbol is None:
        send_telegram_message(telegram_token, response_chat_id, "Symbol currently unavailable.")
        return

    ticker = base_symbol(symbol)
    user_alerts = load_user_alerts()

    if action in LEVEL_ALERT_TYPES:
        user_alerts.setdefault(user_chat_id, {})[ticker] = {
            "type": action,
            "enabled": True,
            "last_triggered": {},
        }
        save_user_alerts(user_alerts)
        send_telegram_message(
            telegram_token,
            response_chat_id,
            level_alert_confirmation(ticker, action),
        )
        return

    if action == "off":
        if user_chat_id in user_alerts:
            user_alerts[user_chat_id].pop(ticker, None)
            if not user_alerts[user_chat_id]:
                user_alerts.pop(user_chat_id, None)
            save_user_alerts(user_alerts)
        send_telegram_message(telegram_token, response_chat_id, f"✅ {ticker} alerts turned off.")
        return

    send_telegram_message(
        telegram_token,
        response_chat_id,
        alert_usage_text(),
    )


def handle_myalerts_command(
    telegram_token,
    telegram_chat_id,
    source_chat=None,
    from_user=None,
):
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    user_chat_id = alert_dm_chat_id(source_chat, from_user or {}, telegram_chat_id)
    user_alerts = load_user_alerts().get(user_chat_id, {})
    active_alerts = [
        (ticker, config)
        for ticker, config in sorted(user_alerts.items())
        if config.get("enabled")
    ]

    if not active_alerts:
        send_telegram_message(telegram_token, response_chat_id, "You do not have active Poinkle alerts.")
        return

    lines = ["Your active Poinkle alerts:"]
    for ticker, config in active_alerts:
        lines.append(f"• {ticker} — {config.get('type', 'critical')}")
    send_telegram_message(telegram_token, response_chat_id, "\n".join(lines))


def handle_levels_command(
    exchange,
    telegram_token,
    telegram_chat_id,
    message_text,
    source_chat=None,
    from_user=None,
):
    parts = message_text.strip().split()
    log_info(f"Received {message_text.strip()}")
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    from_user = from_user or {}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    is_private = is_private_chat(source_chat)

    if len(parts) < 2:
        log_warn("Missing symbol for /levels command")
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Use: /levels BTC\nExample: /levels DOGE",
        )
        return

    symbol = normalize_symbol(parts[1])
    log_info(f"Mapped symbol: {symbol or 'UNKNOWN'}")
    if symbol is None:
        log_warn(f"Unsupported /levels symbol: {parts[1]}")
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Symbol currently unavailable.",
        )
        return

    try:
        message = build_levels_command_message(exchange, symbol)
    except Exception as error:
        log_warn(f"{symbol}: /levels unavailable: {error}")
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Symbol currently unavailable.",
        )
        return

    if is_private:
        log_info("Sending levels response")
        send_telegram_message(telegram_token, response_chat_id, message)
        log_info(f"Answered /levels command for {symbol}")
        return

    user_id = from_user.get("id")
    if not user_id:
        log_warn("Missing Telegram user id for DM delivery")
        send_telegram_message(telegram_token, response_chat_id, levels_dm_failed_message())
        return

    try:
        send_telegram_message(telegram_token, str(user_id), message)
        send_telegram_message(
            telegram_token,
            response_chat_id,
            levels_dm_success_message(symbol),
        )
        log_info(f"Sent {symbol} levels to DM for user {user_id}")
    except Exception as error:
        log_warn(f"Could not DM levels to user {user_id}: {error}")
        send_telegram_message(telegram_token, response_chat_id, levels_dm_failed_message())


def level_alert_zones(snapshot, alert_type):
    zones = []
    if alert_type in {"support", "all", "critical"}:
        for index, zone in enumerate(snapshot.get("support_zones", []), start=1):
            zones.append((f"support_{index}", f"Accumulation Review Zone {index}", zone, "support"))
    if alert_type in {"resistance", "all", "critical"}:
        for index, zone in enumerate(snapshot.get("resistance_zones", []), start=1):
            zones.append((f"resistance_{index}", f"Profit Review Zone {index}", zone, "resistance"))
    return zones


def build_level_alert_message(ticker, price, zone_name, zone_side, alert_type):
    if alert_type == "critical":
        return (
            f"🔔 {ticker} reached a critical Poinkle level.\n\n"
            f"Price: ${format_zone_price(price)}\n"
            f"Zone: {zone_name}\n\n"
            f"Before acting, slow down:\n"
            f"• Is this part of your plan?\n"
            f"• Are you adding, waiting, or doing nothing?\n"
            f"• Are you reacting emotionally?\n"
            f"• What happens if price keeps moving against you?\n\n"
            f"Educational only. Not financial advice."
        )

    if zone_side == "support":
        return (
            f"🔔 {ticker} reached a Poinkle support review zone.\n\n"
            f"Price: ${format_zone_price(price)}\n"
            f"Zone: {zone_name}\n\n"
            f"Before acting, slow down:\n"
            f"• Is this part of your DCA plan?\n"
            f"• Are you following your strategy or reacting emotionally?\n"
            f"• How much of your position were you planning to manage?\n"
            f"• What happens if price keeps moving lower?\n\n"
            f"Educational only. Not financial advice."
        )

    return (
        f"🔔 {ticker} reached a Poinkle resistance review zone.\n\n"
        f"Price: ${format_zone_price(price)}\n"
        f"Zone: {zone_name}\n\n"
        f"Before acting, slow down:\n"
        f"• Does your plan include trimming here?\n"
        f"• Are you protecting gains or reacting to fear?\n"
        f"• Are you managing a small portion or your full core position?\n"
        f"• What happens if price breaks higher and does not come back?\n\n"
        f"Educational only. Not financial advice."
    )


def should_send_level_alert(trigger_record, now):
    if not trigger_record:
        return True
    if not trigger_record.get("active"):
        return True

    last_timestamp = trigger_record.get("timestamp", 0)
    return now - last_timestamp >= ALERT_COOLDOWN_SECONDS


def check_user_level_alerts(exchange, telegram_token):
    user_alerts = load_user_alerts()
    if not user_alerts:
        return

    now = int(time.time())
    changed = False

    for user_chat_id, alerts_by_symbol in list(user_alerts.items()):
        for ticker, alert_config in list(alerts_by_symbol.items()):
            alert_type = alert_config.get("type", "critical")
            if not alert_config.get("enabled") or alert_type not in LEVEL_ALERT_TYPES:
                continue

            symbol = normalize_symbol(ticker)
            if symbol is None:
                continue

            try:
                snapshot = build_levels_scan_snapshot(exchange, symbol)
            except Exception as error:
                throttled_log_warn(
                    symbol,
                    f"user-alert:{alert_type}:{error}",
                    f"{symbol}: Could not check {alert_type} user alert. Will retry quietly.",
                )
                continue

            price = snapshot["current_price"]
            last_triggered = alert_config.setdefault("last_triggered", {})
            active_zone_ids = set()

            for zone_id, zone_name, zone, zone_side in level_alert_zones(snapshot, alert_type):
                if not zone_contains_price(zone, price):
                    continue

                active_zone_ids.add(zone_id)
                trigger_record = last_triggered.get(zone_id)
                if not should_send_level_alert(trigger_record, now):
                    continue

                try:
                    send_telegram_message(
                        telegram_token,
                        user_chat_id,
                        build_level_alert_message(ticker, price, zone_name, zone_side, alert_type),
                    )
                    last_triggered[zone_id] = {
                        "zone": zone_name,
                        "type": alert_type,
                        "timestamp": now,
                        "price": price,
                        "active": True,
                    }
                    changed = True
                    log_info(f"Sent {alert_type} level alert for {ticker} to {user_chat_id}")
                except Exception as error:
                    log_warn(f"Could not send {alert_type} alert for {ticker} to {user_chat_id}: {error}")

            for zone_id, trigger_record in list(last_triggered.items()):
                if zone_id in active_zone_ids or not trigger_record.get("active"):
                    continue
                trigger_record["active"] = False
                changed = True

    if changed:
        save_user_alerts(user_alerts)


def process_telegram_commands(exchange, telegram_token, telegram_chat_id, state):
    command_state = state.setdefault("__telegram_commands", {})
    last_update_id = command_state.get("last_update_id")

    try:
        offset = last_update_id + 1 if last_update_id is not None else None
        updates = get_telegram_updates(telegram_token, offset)
    except Exception as error:
        throttled_log_warn(
            "telegram",
            f"updates:{error}",
            "Telegram command polling failed. Will retry quietly.",
        )
        return

    for update in updates:
        update_id = update["update_id"]
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()
        lower_text = text.lower()

        if lower_text.startswith("/help"):
           handle_help_command(telegram_token, chat_id)
        elif lower_text.startswith("/status"):
            handle_status_command(
                telegram_token,
                chat_id,
                state,
                source_chat=chat,
            )
        elif lower_text.startswith("/myalerts"):
            handle_myalerts_command(
                telegram_token,
                chat_id,
                source_chat=chat,
                from_user=message.get("from", {}),
            )
        elif lower_text.startswith("/alerts"):
            handle_alerts_command(
                telegram_token,
                chat_id,
                text,
                source_chat=chat,
                from_user=message.get("from", {}),
            )
        elif lower_text.startswith("/scan"):
            handle_scan_command(
                exchange,
                telegram_token,
                chat_id,
                text,
                source_chat=chat,
            )
        elif lower_text.startswith("/levels"):
                handle_levels_command(
                exchange,
                telegram_token,
                chat_id,
                text,
                source_chat=chat,
                from_user=message.get("from", {}),
            )

        command_state["last_update_id"] = update_id
        save_state(state)

    save_state(state)


def print_scan_debug(
    symbol,
    candle,
    ema_21,
    ema_55,
    current_rsi,
    volume_avg,
    range_low,
    range_high,
    pending_setup_exists,
    sent_alert_labels,
):
    if not DEBUG:
        return

    timestamp, open_price, high, low, close, volume = candle
    volume_multiple = volume / volume_avg if volume_avg > 0 else 0
    range_position, _ = get_range_location(close, range_low, range_high)
    decision, reason = get_scan_decision(sent_alert_labels)

    print("Scan debug")
    print(f"Symbol: {symbol}")
    print(f"Candle time: {candle_time(timestamp)}")
    print(f"Close: {format_level(close)}")
    print(f"RSI: {current_rsi:.2f}")
    print(f"EMA21: {format_level(ema_21)}")
    print(f"EMA55: {format_level(ema_55)}")
    print(f"Volume multiple: {volume_multiple:.2f}x")
    print(f"Pending setup: {'yes' if pending_setup_exists else 'no'}")
    print(f"Range position: {range_position}")
    print(f"Decision: {decision}")
    print(f"Reason: {reason}")


def current_time_ms():
    return int(time.time() * 1000)


def direction_from_alert(alert):
    alert_type = alert.get("type", "")
    if "breakout" in alert_type:
        return "LONG"
    if "breakdown" in alert_type:
        return "SHORT"
    return None


def add_active_trade(state, symbol, alert, candle):
    direction = direction_from_alert(alert)
    level = alert.get("level")
    range_context = alert.get("range_context", {})
    if not direction or level is None:
        return

    active_trades = state.setdefault("__active_trades", {})
    active_trades[symbol] = {
        "symbol": symbol,
        "direction": direction,
        "level": level,
        "started_at": current_time_ms(),
        "last_monitor_at": current_time_ms(),
        "last_status": None,
        "last_rsi": None,
        "last_volume": None,
        "retest_seen": False,
        "lower_tf_candles_checked": 0,
        "fake_break_checked": False,
        "source_alert": alert.get("label", "Setup Alert"),
        "setup_quality": alert.get("setup_quality", "N/A"),
        "setup_status": alert.get("setup_status", "Watch Closely"),
        "early_break_strength_score": alert.get("break_strength_score"),
        "setup_candle": candle[0],
        "next_target": range_context.get("next_target"),
        "distance_to_target_pct": range_context.get("distance_to_target_pct", 0),
        "range_position": range_context.get("range_position", "Middle Range"),
        "location_quality": range_context.get("location_quality", "B"),
    }


def remove_active_trade(state, symbol):
    state.setdefault("__active_trades", {}).pop(symbol, None)


def clear_pending_setups(state, symbol):
    state.setdefault(symbol, {}).setdefault("pending_setups", {}).clear()


def build_trade_tracking_message(symbol, trade, status, reason, metrics):
    time_text = alert_time_text(metrics["candle_timestamp"])
    title = (
        f"⚠️ {symbol} {status}"
        if status in {
            "Failed Breakout",
            "Failed Breakdown",
        }
        else f"📈 {symbol} Trade Tracking Update"
    )
    action_text = ""
    if status in {
        "Failed Breakout",
        "Failed Breakdown",
    }:
        action_text = (
            f"<b>Setup Quality:</b> {metrics['setup_quality']}\n"
            f"<b>Setup Status:</b> {setup_quality_status(metrics['setup_quality']) if metrics['setup_quality'] != 'N/A' else 'N/A'}\n"
            f"<b>Break Strength Score:</b> {metrics['break_strength_score']}/100\n"
            f"<b>Volume status:</b> {metrics['volume_status']}\n"
            f"<b>RSI status:</b> {metrics['rsi_status']}\n"
            f"<b>EMA trend:</b> {metrics['ema_trend']}\n"
            f"<b>Next key level:</b> {format_level(metrics['next_target'])}\n"
            f"<b>Action:</b> Watch only / No trade confirmation\n\n"
        )
    return (
        f"<b>{title}</b>\n\n"
        f"<b>Symbol:</b> {symbol}\n"
        f"<b>Tracking timeframe:</b> {TRADE_TRACK_TIMEFRAME}\n"
        f"{time_text}"
        f"<b>Status:</b> {status}\n"
        f"<b>Setup Quality:</b> {metrics['setup_quality']}\n"
        f"<b>Setup Status:</b> {metrics['setup_status']}\n"
        f"<b>Direction:</b> {trade['direction']}\n"
        f"<b>Broken level:</b> {format_level(trade['level'])}\n"
        f"<b>Price:</b> {format_level(metrics['price'])}\n"
        f"<b>RSI:</b> {metrics['rsi']:.2f} ({metrics['rsi_direction']})\n"
        f"<b>Volume:</b> {metrics['volume_direction']}\n"
        f"<b>EMA alignment:</b> {metrics['ema_alignment']}\n"
        f"<b>Retest:</b> {metrics['retest_status']}\n\n"
        f"{action_text}"
        f"<b>Reason:</b> {reason}"
    )


def print_tracking_debug(symbol, trade, status, reason, metrics):
    if not DEBUG:
        return

    print("Tracking debug")
    print(f"Symbol: {symbol}")
    print(f"Direction: {trade['direction']}")
    print(f"Broken level: {format_level(trade['level'])}")
    print(f"Candle Close Time: {eastern_time_from_timestamp(metrics['candle_timestamp'])}")
    print(f"Price: {format_level(metrics['price'])}")
    print(f"Status: {status}")
    print(f"Setup Quality: {metrics['setup_quality']}")
    print(f"Setup Status: {metrics['setup_status']}")
    print(f"Break Strength Score: {metrics['break_strength_score']}/100")
    print(f"Volume multiple: {metrics['volume_multiple']:.2f}x")
    print(f"Volume status: {metrics['volume_status']}")
    print(f"RSI: {metrics['rsi']:.2f} ({metrics['rsi_status']})")
    print(f"EMA trend: {metrics['ema_trend']}")
    print(f"Retest: {metrics['retest_status']}")
    print(f"Reason: {reason}")


def evaluate_active_trade(trade, price, candles):
    closed_candles = candles[:-1]
    closes = [candle[4] for candle in closed_candles]
    latest_closed = closed_candles[-1]
    latest_close = latest_closed[4]
    current_rsi = rsi(closes, 14)
    ema_21 = ema(closes, 21)
    ema_55 = ema(closes, 55)
    current_volume = latest_closed[5]
    recent_volumes = [candle[5] for candle in closed_candles[-21:-1]]
    current_volume_avg = sum(recent_volumes) / len(recent_volumes) if recent_volumes else current_volume
    volume_multiple = current_volume / current_volume_avg if current_volume_avg > 0 else 0
    volume_status = get_volume_status(volume_multiple)
    previous_volume = trade.get("last_volume")
    level = trade["level"]
    direction = trade["direction"]
    atr_14 = atr(closed_candles, 14)
    retest_buffer = atr_14 * 0.15
    lower_tf_candles_after_setup = [
        candle for candle in closed_candles if candle[0] >= trade.get("started_at", 0) - 60000
    ]
    first_lower_tf_candles = lower_tf_candles_after_setup[:3]
    trade["lower_tf_candles_checked"] = max(
        trade.get("lower_tf_candles_checked", 0),
        min(len(lower_tf_candles_after_setup), 3),
    )

    previous_rsi = trade.get("last_rsi")
    rsi_direction = (
        "rising"
        if previous_rsi is not None and current_rsi > previous_rsi
        else "falling"
        if previous_rsi is not None and current_rsi < previous_rsi
        else "flat"
    )
    volume_direction = (
        "increasing"
        if previous_volume is not None and current_volume > previous_volume
        else "decreasing"
        if previous_volume is not None and current_volume < previous_volume
        else "flat"
    )
    volume_fading_badly = (
        previous_volume is not None and current_volume < previous_volume * 0.65
    )

    ema_aligned = (
        direction == "LONG" and ema_21 > ema_55
    ) or (
        direction == "SHORT" and ema_21 < ema_55
    )
    ema_strongly_opposed = (
        direction == "LONG" and ema_21 < ema_55 and latest_close < ema_21
    ) or (
        direction == "SHORT" and ema_21 > ema_55 and latest_close > ema_21
    )
    ema_alignment = (
        "aligned"
        if ema_aligned
        else "strongly opposed"
        if ema_strongly_opposed
        else "not aligned"
    )

    if direction == "LONG":
        holds_level = latest_close >= level
        invalidated = price < level - retest_buffer
        retest_now = latest_closed[3] <= level + retest_buffer and latest_closed[4] >= level
        fake_break = any(candle[4] < level for candle in first_lower_tf_candles)
        rsi_supports_direction = current_rsi > 50
        strengthening = (
            holds_level
            and rsi_supports_direction
            and rsi_direction == "rising"
            and volume_direction == "increasing"
            and not ema_strongly_opposed
        )
        failed_break_status = "Failed Breakout"
        failed_break_reason = (
            "Trade invalidated by reclaim. Price closed back below the broken level within the first 1-3 lower-timeframe candles."
        )
    else:
        holds_level = latest_close <= level
        invalidated = price > level + retest_buffer
        retest_now = latest_closed[2] >= level - retest_buffer and latest_closed[4] <= level
        fake_break = any(candle[4] > level for candle in first_lower_tf_candles)
        rsi_supports_direction = current_rsi < 50
        strengthening = (
            holds_level
            and rsi_supports_direction
            and rsi_direction == "falling"
            and volume_direction == "increasing"
            and not ema_strongly_opposed
        )
        failed_break_status = "Failed Breakdown"
        failed_break_reason = (
            "Trade invalidated by reclaim. Price closed back above the broken level within the first 1-3 lower-timeframe candles."
        )

    if retest_now:
        trade["retest_seen"] = True

    if retest_now:
        retest_score = 10
    elif trade.get("retest_seen"):
        retest_score = 8
    elif holds_level:
        retest_score = 4
    else:
        retest_score = 0

    distance_to_target_pct = trade.get("distance_to_target_pct", 0)
    break_strength_score = calculate_break_strength(
        direction,
        latest_close,
        level,
        atr_14,
        current_rsi,
        ema_21,
        ema_55,
        volume_multiple,
        retest_score,
        distance_to_target_pct,
    )
    tracking_range_context = {
        "room_to_target": get_room_to_target(distance_to_target_pct),
        "location_quality": trade.get("location_quality", "B"),
        "range_position": trade.get("range_position", "Middle Range"),
    }
    break_strength_score = adjusted_break_strength_for_setup(
        break_strength_score,
        direction,
        volume_multiple,
        current_rsi,
        ema_21,
        ema_55,
        tracking_range_context,
    )
    setup_quality = grade_setup_quality(
        direction,
        break_strength_score,
        volume_multiple,
        current_rsi,
        ema_21,
        ema_55,
        tracking_range_context,
    )
    invalidated_by_reclaim = fake_break or invalidated or not holds_level
    if invalidated_by_reclaim:
        break_strength_score = min(break_strength_score, 25)
        setup_quality = setup_quality_from_score(break_strength_score)

    weak_volume = volume_multiple < 1
    failed_follow_through = (
        holds_level
        and weak_volume
        and is_stalling_near_level(latest_close, level, atr_14)
    )

    valid_confirmation = (
        holds_level
        and trade.get("retest_seen")
        and rsi_supports_direction
        and not ema_strongly_opposed
        and not volume_fading_badly
        and not weak_volume
        and break_strength_score >= 70
        and setup_quality not in {"D", "F"}
        and distance_to_target_pct >= 0.4
    )

    if fake_break:
        status = failed_break_status
        reason = failed_break_reason
    elif invalidated:
        status = "Trade Invalidated"
        reason = "Price moved back through the broken level."
    elif failed_follow_through:
        status = "Weakening"
        reason = "Price stalled around the broken level with weak volume."
    elif valid_confirmation and strengthening:
        status = "Trade Confirmed"
        reason = (
            "Price held beyond the level, retest held, RSI supports direction, "
            "EMA is not strongly opposed, volume is not fading badly, and Break Strength is 70+."
        )
    elif retest_now:
        status = "Retest Holding"
        reason = "Price retested the broken level and held."
    elif not holds_level:
        status = "Retest Failed"
        reason = "Price failed to hold the broken level."
    elif strengthening:
        status = "Strengthening"
        reason = "Price is holding the level with improving RSI, volume, and EMA alignment."
    else:
        status = "Weakening"
        reason = "Price is holding, but RSI, volume, or EMA alignment is not improving."

    metrics = {
        "candle_timestamp": latest_closed[0],
        "price": price,
        "rsi": current_rsi,
        "rsi_direction": rsi_direction,
        "volume_direction": volume_direction,
        "volume_status": volume_status,
        "volume_multiple": volume_multiple,
        "ema_alignment": ema_alignment,
        "ema_trend": get_ema_trend(direction, ema_21, ema_55),
        "rsi_status": get_rsi_trend(direction, current_rsi),
        "retest_status": "seen" if trade.get("retest_seen") else "not yet",
        "current_volume": current_volume,
        "lower_tf_candles_checked": trade["lower_tf_candles_checked"],
        "break_strength_score": break_strength_score,
        "setup_quality": setup_quality,
        "setup_status": setup_quality_status(setup_quality),
        "next_target": trade.get("next_target") or price,
    }
    return status, reason, metrics


def monitor_active_trades(exchange, telegram_token, telegram_chat_id, state):
    if MAIN_CHAT_SAFE_MODE:
        if state.setdefault("__active_trades", {}):
            log_info("MAIN_CHAT_SAFE_MODE active - trade tracking Telegram updates are disabled.")
        return

    active_trades = state.setdefault("__active_trades", {})
    now = current_time_ms()

    for symbol, trade in list(active_trades.items()):
        if now - trade.get("last_monitor_at", 0) < TRADE_TRACK_POLL_SECONDS * 1000:
            continue

        if now - trade.get("started_at", now) > TRADE_TRACK_MAX_MINUTES * 60 * 1000:
            remove_active_trade(state, symbol)
            save_state(state)
            continue

        try:
            candles = exchange.fetch_ohlcv(
                symbol, timeframe=TRADE_TRACK_TIMEFRAME, limit=CANDLE_LIMIT
            )
            validate_ohlcv_candles(candles, symbol, min_count=56)
            price = get_current_market_price(exchange, symbol, candles[-1][4])
            status, reason, metrics = evaluate_active_trade(trade, price, candles)
            print_tracking_debug(symbol, trade, status, reason, metrics)
            trade["last_monitor_at"] = now
            trade["last_rsi"] = metrics["rsi"]
            trade["last_volume"] = metrics["current_volume"]

            if trade.get("last_status") != status:
                message = build_trade_tracking_message(symbol, trade, status, reason, metrics)
                send_telegram_message(telegram_token, telegram_chat_id, message)
                log_info(f"Trade tracking update: {symbol} - {status}")
                trade["last_status"] = status

            if status in {
                "Trade Confirmed",
                "Trade Invalidated",
                "Failed Breakout",
                "Failed Breakdown",
            }:
                clear_pending_setups(state, symbol)
                remove_active_trade(state, symbol)

            save_state(state)

        except Exception as error:
            throttled_log_warn(
                symbol,
                f"active-trade:{error}",
                f"{symbol}: Active trade monitor failed. Will retry quietly.",
            )


def build_level_alerts(
    symbol,
    previous_candle,
    current_candle,
    symbol_state,
    atr_14,
    current_market_price,
    range_low,
    range_high,
    ema_21,
    ema_55,
    current_rsi,
    volume_avg,
):
    levels = get_key_levels(symbol, current_market_price)
    supports = levels.get("support", [])
    resistances = levels.get("resistance", [])
    mode_prefix = "test" if TEST_MODE else "live"

    previous_close = previous_candle[4]
    current_timestamp = current_candle[0]
    current_close = current_candle[4]
    pending_setups = symbol_state.setdefault("pending_setups", {})
    alerts = []

    for setup_key, setup in list(pending_setups.items()):
        level = setup["level"]
        direction = setup["direction"]
        expected_candle = setup["expected_confirmation_candle"]

        if current_timestamp < expected_candle:
            continue

        if current_timestamp > expected_candle:
            del pending_setups[setup_key]
            continue

        confirmed = (
            direction == "breakdown" and current_close < level
        ) or (
            direction == "breakout" and current_close > level
        )

        if confirmed:
            is_breakdown = direction == "breakdown"
            label = "Breakdown Confirmation" if is_breakdown else "Breakout Confirmation"
            trade_direction = "SHORT" if is_breakdown else "LONG"
            location_filter = get_location_filter(
                trade_direction,
                current_close,
                current_candle[3],
                range_low,
                range_high,
                level,
            )

            if not location_filter["allowed"] or location_filter["location_quality"] == "C":
                alerts.append(
                    {
                        "type": f"{setup_key}:late_move",
                        "label": "Late Move / Exhaustion Risk",
                        "emoji": "⚠️",
                        "level": level,
                        "blocked_direction": trade_direction,
                        "location_filter": location_filter,
                        "setup_quality": setup.get("setup_quality", "D"),
                        "break_strength_score": setup.get("break_strength_score", 0),
                    }
                )
                del pending_setups[setup_key]
                continue

            trade_plan = build_trade_plan(
                trade_direction,
                level,
                [
                    setup.get("first_candle", current_timestamp - TIMEFRAME_MS),
                    setup.get("first_candle_open", level),
                    setup.get("first_candle_high", level),
                    setup.get("first_candle_low", level),
                    setup.get("first_candle_close", level),
                    setup.get("first_candle_volume", 0),
                ],
                current_candle,
                atr_14,
                ema_21,
                ema_55,
                current_rsi,
                volume_avg,
                location_filter,
            )

            if trade_plan["setup_quality"] in {"D", "F"}:
                alerts.append(
                    {
                        "type": f"{setup_key}:weak_break",
                        "label": "Weak Break / Watch Only",
                        "emoji": "⚠️",
                        "level": level,
                        "detail": "Break detected, but setup quality is D.",
                        "trade_plan": trade_plan,
                        "location_filter": location_filter,
                    }
                )
                del pending_setups[setup_key]
                continue

            if trade_plan["failed_follow_through"]:
                alerts.append(
                    {
                        "type": f"{setup_key}:failed_follow_through",
                        "label": "Failed Follow-Through",
                        "emoji": "⚠️",
                        "level": level,
                        "detail": "Price stalled around the broken level with weak volume.",
                        "trade_plan": trade_plan,
                        "location_filter": location_filter,
                    }
                )
                del pending_setups[setup_key]
                continue

            if (
                trade_plan["break_strength_score"] < 70
                or trade_plan["weak_volume"]
                or location_filter["room_to_target"] == "Limited"
            ):
                alerts.append(
                    {
                        "type": f"{setup_key}:weak_break",
                        "label": "Weak Break / Watch Only",
                        "emoji": "⚠️",
                        "level": level,
                        "detail": "Break detected, but momentum/volume did not confirm.",
                        "trade_plan": trade_plan,
                        "location_filter": location_filter,
                    }
                )
                del pending_setups[setup_key]
                continue

            alerts.append(
                {
                    "type": f"{setup_key}:confirmation",
                    "label": label,
                    "emoji": "✅",
                    "level": level,
                    "detail": "First confirmation candle closed beyond the level.",
                    "trade_plan": trade_plan,
                    "location_filter": location_filter,
                }
            )

        del pending_setups[setup_key]

    for level in supports:
        setup_key = f"{mode_prefix}:breakdown:{level}"
        if setup_key in pending_setups:
            continue

        if previous_close >= level and current_close < level:
            range_context = get_range_context("SHORT", current_close, range_low, range_high)
            setup_snapshot = build_setup_quality_snapshot(
                "SHORT",
                level,
                current_candle,
                atr_14,
                ema_21,
                ema_55,
                current_rsi,
                volume_avg,
                range_context,
            )
            pending_setups[setup_key] = {
                "direction": "breakdown",
                "level": level,
                "first_candle": current_timestamp,
                "first_candle_open": current_candle[1],
                "first_candle_high": current_candle[2],
                "first_candle_low": current_candle[3],
                "first_candle_close": current_close,
                "first_candle_volume": current_candle[5],
                "expected_confirmation_candle": current_timestamp + TIMEFRAME_MS,
                "setup_quality": setup_snapshot["setup_quality"],
                "setup_status": setup_snapshot["setup_status"],
                "break_strength_score": setup_snapshot["break_strength_score"],
            }
            alerts.append(
                {
                    "type": f"{setup_key}:early_warning",
                    "label": "Breakdown Attempt",
                    "emoji": "⚠️",
                    "level": level,
                    "range_context": range_context,
                    **setup_snapshot,
                    "detail": (
                        "First candle broke the level. "
                        "Waiting for confirmation candle to close beyond the level."
                    ),
                }
            )

    for level in resistances:
        setup_key = f"{mode_prefix}:breakout:{level}"
        if setup_key in pending_setups:
            continue

        if previous_close <= level and current_close > level:
            range_context = get_range_context("LONG", current_close, range_low, range_high)
            setup_snapshot = build_setup_quality_snapshot(
                "LONG",
                level,
                current_candle,
                atr_14,
                ema_21,
                ema_55,
                current_rsi,
                volume_avg,
                range_context,
            )
            pending_setups[setup_key] = {
                "direction": "breakout",
                "level": level,
                "first_candle": current_timestamp,
                "first_candle_open": current_candle[1],
                "first_candle_high": current_candle[2],
                "first_candle_low": current_candle[3],
                "first_candle_close": current_close,
                "first_candle_volume": current_candle[5],
                "expected_confirmation_candle": current_timestamp + TIMEFRAME_MS,
                "setup_quality": setup_snapshot["setup_quality"],
                "setup_status": setup_snapshot["setup_status"],
                "break_strength_score": setup_snapshot["break_strength_score"],
            }
            alerts.append(
                {
                    "type": f"{setup_key}:early_warning",
                    "label": "Breakout Attempt",
                    "emoji": "⚠️",
                    "level": level,
                    "range_context": range_context,
                    **setup_snapshot,
                    "detail": (
                        "First candle broke the level. "
                        "Waiting for confirmation candle to close beyond the level."
                    ),
                }
            )

    return alerts


def scan_symbol(exchange, symbol):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=CANDLE_LIMIT)
        validate_ohlcv_candles(candles, symbol, min_count=80)
    except Exception as error:
        raise MarketDataError(candle_error_message(symbol, error)) from error

    if len(candles) < 80:
        raise MarketDataError("Not enough candles for indicators")

    # Coinbase includes the currently forming candle as the last item.
    # The second-to-last candle is the most recent fully closed 15m candle.
    previous_closed_candles = candles[:-2]
    closed_candles = candles[:-1]
    previous_closed = closed_candles[-2]
    latest_closed = closed_candles[-1]
    range_low, range_high = get_recent_range(closed_candles[:-1], 50)

    previous_closes = [candle[4] for candle in previous_closed_candles]
    closes = [candle[4] for candle in closed_candles]

    previous_ema_21 = ema(previous_closes, 21)
    previous_ema_55 = ema(previous_closes, 55)
    current_ema_21 = ema(closes, 21)
    current_ema_55 = ema(closes, 55)
    previous_rsi = rsi(previous_closes, 14)
    current_rsi = rsi(closes, 14)
    current_atr_14 = atr(closed_candles, 14)

    previous_20_volumes = [candle[5] for candle in closed_candles[-21:-1]]
    volume_average = sum(previous_20_volumes) / len(previous_20_volumes)
    current_volume = latest_closed[5]

    alerts = []

    crossed_above = previous_ema_21 <= previous_ema_55 and current_ema_21 > current_ema_55
    crossed_below = previous_ema_21 >= previous_ema_55 and current_ema_21 < current_ema_55
    rsi_crossed_above_70 = previous_rsi <= 70 and current_rsi > 70
    rsi_crossed_below_30 = previous_rsi >= 30 and current_rsi < 30

    if crossed_above:
        alerts.append(
            {
                "type": "ema_cross_above",
                "label": "EMA 21 crossed above EMA 55",
                "emoji": "🟢",
            }
        )

    if crossed_below:
        alerts.append(
            {
                "type": "ema_cross_below",
                "label": "EMA 21 crossed below EMA 55",
                "emoji": "🔴",
            }
        )

    if rsi_crossed_above_70:
        alerts.append(
            {
                "type": "rsi_cross_above_70",
                "label": "RSI crossed above 70",
                "emoji": "🔥",
            }
        )
    elif rsi_crossed_below_30:
        alerts.append(
            {
                "type": "rsi_cross_below_30",
                "label": "RSI crossed below 30",
                "emoji": "🧊",
            }
        )

    if volume_average > 0 and current_volume >= volume_average * 2:
        close = latest_closed[4]
        volume_multiple = current_volume / volume_average
        bullish_confirmation = close > current_ema_21 and current_rsi > 50
        bearish_confirmation = close < current_ema_21 and current_rsi < 50

        if bullish_confirmation:
            volume_label = "Bullish Volume Spike"
            volume_emoji = "🟢"
            volume_direction = "bullish"
        elif bearish_confirmation:
            volume_label = "Bearish Volume Spike"
            volume_emoji = "🔴"
            volume_direction = "bearish"
        else:
            volume_label = "High Volume Alert"
            volume_emoji = "⚪"
            volume_direction = "neutral"

        alerts.append(
            {
                "type": "volume_spike",
                "label": volume_label,
                "emoji": volume_emoji,
                "direction": volume_direction,
                "volume_multiple": volume_multiple,
            }
        )

    return (
        previous_closed,
        latest_closed,
        alerts,
        current_ema_21,
        current_ema_55,
        current_rsi,
        current_atr_14,
        volume_average,
        range_low,
        range_high,
    )


def run_once(exchange, telegram_token, telegram_chat_id, state):
    compact_scan_lines = []
    for symbol in WATCHLIST:
        try:
            symbol_state = state.setdefault(symbol, {})
            (
                previous_candle,
                candle,
                alerts,
                ema_21,
                ema_55,
                current_rsi,
                current_atr_14,
                volume_avg,
                range_low,
                range_high,
            ) = scan_symbol(exchange, symbol)
            candle_id = str(candle[0])
            sent_alerts = symbol_state.setdefault("sent_alerts", {})

            if symbol_state.get("last_checked_candle") == candle_id:
                continue

            pending_before_scan = bool(symbol_state.get("pending_setups"))
            tracking_is_active = symbol in state.setdefault("__active_trades", {})
            current_market_price = get_current_market_price(exchange, symbol, candle[4])
            if MAIN_CHAT_SAFE_MODE:
                if alerts:
                    log_info(
                        f"MAIN_CHAT_SAFE_MODE active - suppressed automatic alerts for {symbol}: "
                        f"{', '.join(alert['label'] for alert in alerts)}"
                    )
                alerts = []
            else:
                alerts.extend(
                    build_level_alerts(
                        symbol,
                        previous_candle,
                        candle,
                        symbol_state,
                        current_atr_14,
                        current_market_price,
                        range_low,
                        range_high,
                        ema_21,
                        ema_55,
                        current_rsi,
                        volume_avg,
                    )
                )

            sent_alert_labels = []
            sent_alert_types = []
            for alert in alerts:
                event_key = f"{candle_id}:{alert['type']}"
                if sent_alerts.get(alert["type"]) == event_key:
                    continue

                if MAIN_CHAT_SAFE_MODE:
                    log_info(
                        f"MAIN_CHAT_SAFE_MODE active - skipped Telegram alert for {symbol}: "
                        f"{alert['label']}"
                    )
                    sent_alerts[alert["type"]] = event_key
                    sent_alert_types.append(alert["type"])
                    save_state(state)
                    continue

                active_trade_status = (
                    state.setdefault("__active_trades", {})
                    .get(symbol, {})
                    .get("last_status")
                )
                if not should_send_telegram_alert(alert, alerts, active_trade_status):
                    log_suppressed_volume_alert(
                        symbol,
                        candle,
                        alert,
                        volume_avg,
                        (
                            "No breakout attempt, breakdown attempt, EMA cross, "
                            "Retest Holding, or Retest Failed context."
                        ),
                    )
                    sent_alerts[alert["type"]] = event_key
                    sent_alert_types.append(alert["type"])
                    save_state(state)
                    continue

                location_filter = alert.get("location_filter")
                if location_filter:
                    print_confirmation_debug(
                        symbol,
                        alert,
                        candle,
                        ema_21,
                        ema_55,
                        current_rsi,
                        volume_avg,
                    )

                message = build_alert(
                    symbol, candle, alert, ema_21, ema_55, current_rsi, volume_avg
                )
                send_telegram_message(telegram_token, telegram_chat_id, message)
                sent_alerts[alert["type"]] = event_key
                sent_alert_labels.append(alert["label"])
                sent_alert_types.append(alert["type"])
                if alert["type"].endswith(":early_warning"):
                    add_active_trade(state, symbol, alert, candle)
                    tracking_is_active = True
                elif alert["type"].endswith(":confirmation") or alert["type"].endswith(":late_move"):
                    remove_active_trade(state, symbol)
                save_state(state)
                log_info(f"Sent alert: {symbol} - {alert['label']}")

            symbol_state["last_checked_candle"] = candle_id
            symbol_state["last_checked_time"] = candle_time(candle[0])
            compact_scan_lines.append(
                build_compact_scan_line(
                    symbol,
                    candle,
                    current_rsi,
                    volume_avg,
                    range_low,
                    range_high,
                    sent_alert_labels,
                )
            )
            if should_print_full_scan_debug(sent_alert_types, tracking_is_active):
                print_scan_debug(
                    symbol,
                    candle,
                    ema_21,
                    ema_55,
                    current_rsi,
                    volume_avg,
                    range_low,
                    range_high,
                    pending_before_scan or bool(symbol_state.get("pending_setups")),
                    sent_alert_labels,
                )
            save_state(state)

        except Exception as error:
            throttled_log_warn(
                symbol,
                str(error),
                candle_error_message(symbol, error),
            )

    print_compact_scan_summary(compact_scan_lines)
    save_state(state)


def main():
    load_dotenv()

    if ccxt is None:
        raise SystemExit("Missing ccxt. Run: pip install -r requirements.txt")
    if requests is None:
        raise SystemExit("Missing requests. Run: pip install -r requirements.txt")

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not telegram_token or not telegram_chat_id:
        raise SystemExit(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID. Add them to your .env file."
        )

    exchange = ccxt.coinbase()
    state = load_state()
    update_bot_status(state, "Online", "Starting")
    save_state(state)
    send_status_update(telegram_token, telegram_chat_id, state, indicator="🟢")

    log_info("Poinkle scanner started.")
    log_info(f"Watching {len(WATCHLIST)} symbols.")
    log_info(f"Loaded {count_enabled_user_alerts(load_user_alerts())} user alerts.")
    if TEST_MODE and DEBUG:
        run_test_mode_location_filter_examples()

    try:
        while True:
            update_bot_status(state, "Online", "Checking commands")
            save_state(state)
            process_telegram_commands(exchange, telegram_token, telegram_chat_id, state)

            update_bot_status(state, "Online", "Scanning")
            save_state(state)
            run_once(exchange, telegram_token, telegram_chat_id, state)
            update_bot_status(state, "Online", "Scan complete", last_scan_time=eastern_time_now())
            save_state(state)

            check_user_level_alerts(exchange, telegram_token)
            monitor_active_trades(exchange, telegram_token, telegram_chat_id, state)

            update_bot_status(state, "Online", "Waiting")
            save_state(state)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        update_bot_status(state, "Offline", "Updating...")
        save_state(state)
        send_status_update(
            telegram_token,
            telegram_chat_id,
            state,
            indicator="🔴",
            extra_line="Updating...",
        )
        log_info("Poinkle scanner stopped.")


if __name__ == "__main__":
    main()
