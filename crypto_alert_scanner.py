import json
import math
import os
import sys
import time
import html
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from chart_generator import generate_levels_chart
except ModuleNotFoundError:
    generate_levels_chart = None

try:
    from prb_card_renderer import (
        render_alert_card,
        render_mike_list_card,
        render_prb_cards,
        render_reference_card,
        render_welcome_card,
    )
except ModuleNotFoundError:
    render_alert_card = None
    render_mike_list_card = None
    render_prb_cards = None
    render_reference_card = None
    render_welcome_card = None

LAST_LEVELS_CHART_DATA = {}
LAST_RESEARCH_CHART_DATA = {}
TELEGRAM_COMMAND_JOB_QUEUE = deque()
TELEGRAM_HTTP_SESSION = None
COINGECKO_COIN_METADATA_CACHE = {}

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from scanner import format_scan_message, scan_top_100
from explanations import available_concepts, concept_display_name, explain_concept, normalize_concept_key

ASSETS_DIR = PROJECT_DIR / "assets"
WELCOME_BANNER_PATH = ASSETS_DIR / "welcome_banner.jpg"
TELEGRAM_PHOTO_CAPTION_LIMIT = 1024
CONCEPT_TEACHING_CARD_FILES = {
    "rsi": "rsi.png",
    "support": "support.png",
    "resistance": "resist.png",
    "breakout": "breakout.png",
    "breakdown": "breakdown.png",
    "confluence": "con.png",
    "trend": "trend.png",
    "ema": "ema.png",
    "volume_spike": "volume.png",
    "confirmation": "confirmation.png",
    "candle": "candle.png",
    "range": "range.png",
    "key_level": "keylevel.png",
    "liquidity": "liquidity.png",
    "market_structure": "structure.png",
    "accumulation": "accumulation.png",
    "retest": "retest.png",
    "follow_through": "followthrough.png",
    "trade_plan": "tradeplan.png",
}

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
DEBUG = False
LIVE_ALERT_TEST_CHAT_ID = ""
BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "Poinkle_Bot").strip().lstrip("@")
ALPHA_ONBOARDED_USERS = set()
WATCHLIST_FILE = Path(__file__).resolve().parent / "watchlist.json"
SYMBOL_ALIASES = {
    "XAO": "XAU",
    "GOLD": "XAU",
}
COINGECKO_DEMO_API_BASE_URL = "https://api.coingecko.com/api/v3"
COINGECKO_COIN_METADATA_TTL_SECONDS = 6 * 60 * 60
COINGECKO_COIN_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "DOGE": "dogecoin",
    "TRX": "tron",
    "ADA": "cardano",
    "HYPE": "hyperliquid",
    "SUI": "sui",
    "LINK": "chainlink",
    "XLM": "stellar",
    "BCH": "bitcoin-cash",
    "AVAX": "avalanche-2",
    "TON": "the-open-network",
    "SHIB": "shiba-inu",
    "HBAR": "hedera-hashgraph",
    "LTC": "litecoin",
    "DOT": "polkadot",
    "PEPE": "pepe",
    "UNI": "uniswap",
    "AAVE": "aave",
    "TAO": "bittensor",
    "NEAR": "near",
    "ICP": "internet-computer",
    "ETC": "ethereum-classic",
    "ONDO": "ondo-finance",
    "APT": "aptos",
    "POL": "polygon-ecosystem-token",
    "CRO": "crypto-com-chain",
    "VET": "vechain",
    "ALGO": "algorand",
    "FIL": "filecoin",
    "ATOM": "cosmos",
    "ARB": "arbitrum",
    "FET": "fetch-ai",
    "RENDER": "render-token",
    "ENA": "ethena",
    "WLD": "worldcoin-wld",
    "SEI": "sei-network",
    "OP": "optimism",
    "INJ": "injective-protocol",
    "XMR": "monero",
    "JUP": "jupiter-exchange-solana",
    "BONK": "bonk",
    "IMX": "immutable-x",
    "STX": "blockstack",
    "QNT": "quant-network",
    "GRT": "the-graph",
    "FLOKI": "floki",
    "RUNE": "thorchain",
    "LDO": "lido-dao",
    "PYTH": "pyth-network",
    "GALA": "gala",
    "JASMY": "jasmycoin",
    "SAND": "the-sandbox",
}
OFFICIAL_COIN_LINKS = {
    "BTC": "https://bitcoin.org",
    "ETH": "https://ethereum.org",
    "SOL": "https://solana.com",
    "XRP": "https://xrpl.org",
    "BNB": "https://bnbchain.org",
    "DOGE": "https://dogecoin.com",
    "ADA": "https://cardano.org",
    "LINK": "https://chain.link",
    "AVAX": "https://www.avax.network",
    "DOT": "https://polkadot.com",
    "LTC": "https://litecoin.org",
    "BCH": "https://bitcoincash.org",
    "XLM": "https://stellar.org",
    "TON": "https://ton.org",
    "TRX": "https://tron.network",
}


def load_watchlist_symbols(path=WATCHLIST_FILE):
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    symbols = []
    seen = set()
    for item in data.get("symbols", []):
        if not item.get("enabled", True):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol or symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)
    return symbols


# Single master symbol list used by the scanner, snapshots, research, and command normalization.
WATCHLIST = load_watchlist_symbols()
UNSUPPORTED_SYMBOLS_THIS_SESSION = set()


def validate_watchlist_against_exchange(exchange, watchlist):
    try:
        markets = exchange.load_markets()
    except Exception as error:
        log_warn(f"Could not load exchange markets for validation: {error}")
        return list(watchlist), []

    supported = []
    unsupported = []
    for symbol in watchlist:
        if symbol in markets or resolve_data_source(symbol) == "kraken":
            supported.append(symbol)
        else:
            unsupported.append(symbol)

    if unsupported:
        log_warn(
            f"{len(unsupported)} watchlist symbol(s) are not supported on this "
            f"exchange and will be skipped for this session: {', '.join(unsupported)}"
        )
        log_warn(
            "Fix: either remove these from watchlist.json (set enabled: false), "
            "or confirm the correct Coinbase market name and update the symbol."
        )

    return supported, unsupported


def symbol_base(symbol):
    return str(symbol or "").strip().upper().split("/", 1)[0]


def official_coin_link(symbol):
    return OFFICIAL_COIN_LINKS.get(symbol_base(symbol))


def official_coin_link_text(symbol):
    link = official_coin_link(symbol)
    if not link:
        return ""
    return f"\n\n<b>Learn more:</b> {link}"


# Add your key support and resistance levels here.
# Alerts use candle closes only. Wicks are ignored.
KEY_LEVELS = {symbol: {"support": [], "resistance": []} for symbol in WATCHLIST}

TIMEFRAME = "1d"
TRADE_TRACK_TIMEFRAME = "1m"
ANCHOR_TIMEFRAME = "1d"
MIDDLE_TIMEFRAME = "6h"
ENTRY_TIMEFRAME = "2h"
TIMEFRAME_MS = 24 * 60 * 60 * 1000
CANDLE_LIMIT = 120
POLL_SECONDS = 15
TELEGRAM_POLL_EVERY_N_SYMBOLS = 15
TELEGRAM_COMMAND_JOB_QUEUE_LIMIT = 50
TELEGRAM_COMMAND_JOB_BATCH_LIMIT = 50
TELEGRAM_JOB_BUDGET_SECONDS_PER_CHUNK = 8
TELEGRAM_JOB_LIGHT = "light"
TELEGRAM_JOB_HEAVY = "heavy"
TELEGRAM_LIGHT_JOB_ESTIMATE_SECONDS = 1.0
HEAVY_TELEGRAM_JOB_ACTIONS = {"snapshot", "research", "whynot"}
TRADE_TRACK_POLL_SECONDS = 60
TRADE_TRACK_MAX_MINUTES = 60
TRADE_TRACKING_TELEGRAM_ENABLED = False
SECONDARY_TIMEFRAME_BASE = "1h"
SECONDARY_TIMEFRAME_1H_LIMIT = 480
STATE_FILE = PROJECT_DIR / "scanner_state.json"
DIAGNOSTICS_FILE = PROJECT_DIR / "diagnostics" / "alert_diagnostics.jsonl"
USER_ALERTS_FILE = PROJECT_DIR / "user_alerts.json"
USER_WATCHLISTS_FILE = PROJECT_DIR / "user_watchlists.json"
USER_PROFILES_FILE = PROJECT_DIR / "user_profiles.json"
BOT_CONFIG_FILE = PROJECT_DIR / "bot_config.json"
ERROR_COOLDOWN_SECONDS = 300
ALERT_COOLDOWN_SECONDS = 3600
SCAN_ALERT_COOLDOWN_SECONDS = 86400
SCAN_TIER2_ALERT_COOLDOWN_SECONDS = 86400
ROLLING_CONFLUENCE_WINDOW_SECONDS = 86400
SCAN_PERFORMANCE_TARGET_SYMBOLS = 150
COINBASE_PUBLIC_REQUESTS_PER_SECOND = 10
ACCURACY_AUDIT_SYMBOLS = {"BTC/USD", "ETH/USD", "SOL/USD", "AAVE/USD", "PEPE/USD"}
ALERT_DELIVERY_METRIC_LIMIT = 100
TELEGRAM_CALLBACK_DEDUPE_LIMIT = 200
LEVEL_ALERT_TYPES = {"support", "resistance", "all", "critical"}
BREAKOUT_BODY_ATR_MULT = 1.0
TREND_GATE_FAST_EMA = 21
TREND_GATE_SLOW_EMA = 55
SUPPORT_ZONE_DEEP_FRACTION = 0.33
SR_SWING_LOOKBACK = 3
SR_LEVEL_DEDUPE_PCT = 0.5
SR_MAX_LEVELS_PER_SIDE = 6
ALERT_DEDUPE_LEVEL_PCT = 0.5
MAX_USER_WATCHLIST = 10
MAX_TOTAL_SCAN_SYMBOLS = 200
EASTERN_TIME = ZoneInfo("America/New_York")
ERROR_LOG_STATE = {}
DEFAULT_BOT_CONFIG = {
    "developer_mode": False,
    "maintenance_mode": False,
    "live_alerts_enabled": False,
}
PUBLIC_BOT_COMMANDS = [
    {"command": "snapshot", "description": "Full visual chart and breakdown"},
    {"command": "snap", "description": "Quick version of snapshot"},
    {"command": "research", "description": "Deeper multi-card research brief"},
    {"command": "whynot", "description": "See why a coin is waiting"},
    {"command": "why", "description": "Alias for whynot"},
    {"command": "levels", "description": "Legacy text-only version"},
    {"command": "alerts", "description": "Set a personal price-zone alert"},
    {"command": "myalerts", "description": "View your active alerts"},
    {"command": "watch", "description": "Add a coin to your watchlist"},
    {"command": "unwatch", "description": "Remove a coin from your watchlist"},
    {"command": "clearwatch", "description": "Clear watched coins by number"},
    {"command": "mywatch", "description": "View your watched coins"},
    {"command": "watching", "description": "View your watched coins"},
    {"command": "mike", "description": "Mike's curated watchlist"},
    {"command": "guide", "description": "Command and coin reference card"},
    {"command": "explain", "description": "Learn a market concept"},
    {"command": "learn", "description": "Learn a market concept"},
    {"command": "coins", "description": "See every coin I track"},
    {"command": "help", "description": "Full help message"},
    {"command": "start", "description": "Welcome message"},
]
MIKES_LIST = [
    "JASMY/USD",
    "ICP/USD",
    "HYPE/USD",
    "VIRTUAL/USD",
    "BRETT/USD",
    "TAO/USD",
    "SUPER/USD",
    "SOL/USD",
    "JCT/USD",
    "PENGU/USD",
]
MIKE_ALTERNATE_EXCHANGE_ID = "kucoin"
MIKE_ALTERNATE_SYMBOLS = {
    "BRETT/USD": "BRETT/USDT",
    "JCT/USD": "JCT/USDT",
}
MIKE_ALTERNATE_EXCHANGE = None
KRAKEN_EXCHANGE_ID = "kraken"
KRAKEN_EXCHANGE = None
KRAKEN_FALLBACK_SYMBOLS = frozenset(
    {
        "XMR/USD",
        "TRX/USD",
        "KAS/USD",
        "JUP/USD",
        "RUNE/USD",
        "GALA/USD",
        "BTT/USD",
        "XDC/USD",
        "CFX/USD",
        "AR/USD",
        "NOT/USD",
        "LUNC/USD",
        "QTUM/USD",
        "SC/USD",
        "NEO/USD",
        "GMX/USD",
        "DYDX/USD",
        "OP/USD",
        "DAI/USD",
        "FLOKI/USD",
        "FLOW/USD",
        "RAY/USD",
        "KAVA/USD",
        "CHZ/USD",
        "STRK/USD",
        "BEAM/USD",
        "APE/USD",
        "MOG/USD",
        "GMT/USD",
        "1INCH/USD",
        "BLUR/USD",
        "CELO/USD",
        "MASK/USD",
        "LPT/USD",
        "OSMO/USD",
        "CVX/USD",
        "BAL/USD",
        "BAND/USD",
        "TRAC/USD",
        "AUDIO/USD",
        "COTI/USD",
        "API3/USD",
    }
)


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


def ensure_diagnostics_dir():
    DIAGNOSTICS_FILE.parent.mkdir(parents=True, exist_ok=True)


def append_diagnostic_record(record):
    try:
        ensure_diagnostics_dir()
        line_record = dict(record)
        line_record["logged_at"] = datetime.now(timezone.utc).isoformat()
        with DIAGNOSTICS_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line_record, separators=(",", ":"), sort_keys=True))
            handle.write("\n")
            handle.flush()
    except Exception as error:
        log_warn(f"Could not write diagnostic record: {error}")


def scan_cycle_benchmark(elapsed_seconds, scanned_symbols, skipped_symbols=0, failed_symbols=0):
    scanned_symbols = int(scanned_symbols)
    skipped_symbols = int(skipped_symbols)
    failed_symbols = int(failed_symbols)
    elapsed_seconds = max(float(elapsed_seconds), 0.0)
    average_seconds = elapsed_seconds / scanned_symbols if scanned_symbols else 0.0
    public_requests = scanned_symbols * 2
    rate_limit_floor_seconds = public_requests / COINBASE_PUBLIC_REQUESTS_PER_SECOND if public_requests else 0.0
    target_rate_limit_floor_seconds = (
        (SCAN_PERFORMANCE_TARGET_SYMBOLS * 2) / COINBASE_PUBLIC_REQUESTS_PER_SECOND
    )
    return {
        "elapsed_seconds": elapsed_seconds,
        "scanned_symbols": scanned_symbols,
        "skipped_symbols": skipped_symbols,
        "failed_symbols": failed_symbols,
        "average_seconds_per_symbol": average_seconds,
        "estimated_public_requests": public_requests,
        "rate_limit_floor_seconds": rate_limit_floor_seconds,
        "target_symbols": SCAN_PERFORMANCE_TARGET_SYMBOLS,
        "target_rate_limit_floor_seconds": target_rate_limit_floor_seconds,
    }


def format_scan_cycle_benchmark(benchmark):
    return (
        "Scan benchmark: "
        f"{benchmark['scanned_symbols']} scanned, "
        f"{benchmark['skipped_symbols']} skipped, "
        f"{benchmark['failed_symbols']} failed in "
        f"{benchmark['elapsed_seconds']:.2f}s "
        f"({benchmark['average_seconds_per_symbol']:.3f}s/symbol). "
        f"Estimated public calls: {benchmark['estimated_public_requests']}; "
        f"Coinbase 10 req/s floor: {benchmark['rate_limit_floor_seconds']:.1f}s. "
        f"150-symbol target floor: {benchmark['target_rate_limit_floor_seconds']:.1f}s."
    )


def candle_close_timestamp_ms(candle):
    return int(candle[0]) + TIMEFRAME_MS


def alert_delivery_delay_seconds(candle, sent_at=None):
    sent_at = time.time() if sent_at is None else float(sent_at)
    return max(0.0, sent_at - (candle_close_timestamp_ms(candle) / 1000))


def alert_delivery_metrics(state):
    return state.setdefault("__alert_delivery_metrics", [])


def alert_delivery_summary(metrics):
    if not metrics:
        return "No alert delivery metrics recorded yet."

    delays = [float(metric["delay_seconds"]) for metric in metrics]
    average_delay = sum(delays) / len(delays)
    return (
        f"Alert delivery delay over last {len(delays)} alert(s): "
        f"min {min(delays):.1f}s, max {max(delays):.1f}s, avg {average_delay:.1f}s."
    )


def record_alert_delivery_metric(state, symbol, candle, alerts, sent_at=None, delivery_type="unknown"):
    sent_at = time.time() if sent_at is None else float(sent_at)
    candle_close_ms = candle_close_timestamp_ms(candle)
    metric = {
        "symbol": symbol,
        "alert_types": [alert.get("type", "unknown") for alert in alerts],
        "alert_labels": [alert.get("label", "Market Alert") for alert in alerts],
        "candle_close_time": eastern_time_from_timestamp(candle_close_ms),
        "sent_time": datetime.fromtimestamp(sent_at, tz=EASTERN_TIME).strftime("%Y-%m-%d %I:%M:%S %p ET"),
        "delay_seconds": alert_delivery_delay_seconds(candle, sent_at=sent_at),
        "delivery_type": delivery_type,
    }
    metrics = alert_delivery_metrics(state)
    metrics.append(metric)
    del metrics[:-ALERT_DELIVERY_METRIC_LIMIT]
    return metric


def log_alert_delivery_metric(metric, metrics):
    log_info(
        "Alert delivery timing: "
        f"{metric['symbol']} "
        f"{' + '.join(metric['alert_labels'])} | "
        f"candle close {metric['candle_close_time']} | "
        f"sent {metric['sent_time']} | "
        f"delay {metric['delay_seconds']:.1f}s | "
        f"delivery {metric['delivery_type']}"
    )
    log_info(alert_delivery_summary(metrics))


def accuracy_audit_symbols():
    configured = os.getenv("POINKLE_ACCURACY_AUDIT_SYMBOLS", "").strip()
    if not configured:
        return ACCURACY_AUDIT_SYMBOLS
    return {
        normalize_symbol(part.strip()) or part.strip().upper()
        for part in configured.split(",")
        if part.strip()
    }


def log_accuracy_audit_snapshot(symbol, candle, current_market_price, ema_21, ema_55, current_rsi):
    if symbol not in accuracy_audit_symbols():
        return
    candle_close_time = eastern_time_from_timestamp(candle_close_timestamp_ms(candle))
    log_info(
        "Accuracy audit snapshot: "
        f"{symbol} | "
        f"candle close {candle_close_time} | "
        f"price {format_level(current_market_price)} | "
        f"close {format_level(candle[4])} | "
        f"RSI14 {current_rsi:.2f} | "
        f"EMA21 {format_level(ema_21)} | "
        f"EMA55 {format_level(ema_55)}"
    )
    append_diagnostic_record(
        {
            "record_type": "accuracy_audit",
            "symbol": symbol,
            "candle_close_time": candle_close_time,
            "current_market_price": current_market_price,
            "candle_close": candle[4],
            "rsi14": current_rsi,
            "ema21": ema_21,
            "ema55": ema_55,
        }
    )


def format_loop_phase_benchmark(command_seconds, scan_seconds, user_alert_seconds, active_trade_seconds):
    total = command_seconds + scan_seconds + user_alert_seconds + active_trade_seconds
    return (
        "Loop phase benchmark: "
        f"commands {command_seconds:.2f}s | "
        f"scan {scan_seconds:.2f}s | "
        f"user alerts {user_alert_seconds:.2f}s | "
        f"active trades {active_trade_seconds:.2f}s | "
        f"total before sleep {total:.2f}s"
    )


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


def classify_scan_failure_error(error):
    text = str(error).lower()
    if "timeout" in text or "rate" in text or "429" in text:
        return "network_or_rate_limit"
    if "no candles" in text or "malformed" in text or "missing" in text or "not enough" in text:
        return "insufficient_or_missing_candles"
    return "other"


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


def resample_candles(candles, group_size):
    """
    Groups consecutive OHLCV candles into larger bars.
    Example: group_size=4 turns four 1h candles into one 4h candle.
    Each candle is [timestamp, open, high, low, close, volume].
    """
    resampled = []
    for index in range(0, len(candles) - group_size + 1, group_size):
        group = candles[index:index + group_size]
        if len(group) < group_size:
            continue
        timestamp = group[0][0]
        open_price = group[0][1]
        high = max(candle[2] for candle in group)
        low = min(candle[3] for candle in group)
        close = group[-1][4]
        volume = sum(candle[5] for candle in group)
        resampled.append([timestamp, open_price, high, low, close, volume])
    return resampled


def timeframe_indicator_context(candles):
    if len(candles) < 56:
        raise MarketDataError("Not enough candles for secondary timeframe indicators")

    latest_closed = candles[-1]
    closes = [candle[4] for candle in candles]
    previous_20_volumes = [candle[5] for candle in candles[-21:-1]]
    volume_average = sum(previous_20_volumes) / len(previous_20_volumes)
    current_volume = latest_closed[5]
    volume_multiple = current_volume / volume_average if volume_average > 0 else 0

    return {
        "latest_close": latest_closed[4],
        "ema_21": ema(closes, 21),
        "ema_55": ema(closes, 55),
        "rsi_14": rsi(closes, 14),
        "volume_average": volume_average,
        "current_volume": current_volume,
        "volume_multiple": volume_multiple,
        "candle_count": len(candles),
        "latest_candle_time": latest_closed[0],
    }


def get_secondary_timeframe_context(exchange, symbol):
    try:
        six_hour_candles = fetch_swing_ohlcv(exchange, symbol, MIDDLE_TIMEFRAME, CANDLE_LIMIT)
        validate_ohlcv_candles(six_hour_candles, symbol, min_count=56)
        closed_six_hour_candles = six_hour_candles[:-1]
        validate_ohlcv_candles(closed_six_hour_candles, symbol, min_count=56)
        return {
            MIDDLE_TIMEFRAME: timeframe_indicator_context(closed_six_hour_candles),
        }
    except Exception as error:
        throttled_log_warn(
            symbol,
            "secondary-timeframe-context",
            f"{symbol}: secondary timeframe context unavailable: {error}",
        )
        return None


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
    except (json.JSONDecodeError, OSError) as error:
        log_warn(f"Could not load scanner state from {STATE_FILE}: {error}")
        return {}


def write_json_file_atomic(path, payload, label):
    tmp_path = path.with_name(f".{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp_path, path)
    except Exception as error:
        log_warn(f"Could not save {label} to {path}: {error}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def save_state(state):
    write_json_file_atomic(STATE_FILE, state, "scanner state")


def load_user_alerts():
    if not USER_ALERTS_FILE.exists():
        return {}

    try:
        return json.loads(USER_ALERTS_FILE.read_text())
    except (json.JSONDecodeError, OSError) as error:
        log_warn(f"Could not load user alerts from {USER_ALERTS_FILE}: {error}")
        return {}


def save_user_alerts(alerts):
    write_json_file_atomic(USER_ALERTS_FILE, alerts, "user alerts")


def load_user_watchlists():
    if not USER_WATCHLISTS_FILE.exists():
        return {}

    try:
        return json.loads(USER_WATCHLISTS_FILE.read_text())
    except (json.JSONDecodeError, OSError) as error:
        log_warn(f"Could not load user watchlists from {USER_WATCHLISTS_FILE}: {error}")
        return {}


def save_user_watchlists(watchlists):
    write_json_file_atomic(USER_WATCHLISTS_FILE, watchlists, "user watchlists")


def load_user_profiles():
    if not USER_PROFILES_FILE.exists():
        return {}
    try:
        return json.loads(USER_PROFILES_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_user_profiles(profiles):
    write_json_file_atomic(USER_PROFILES_FILE, profiles, "user profiles")


def iso_utc_now():
    return datetime.now(timezone.utc).isoformat()


def data_as_of_label(now=None):
    now = now or datetime.now(tz=EASTERN_TIME)
    return f"as of {now.strftime('%-I:%M %p ET')}"


def user_profile(user_id):
    if not user_id:
        return {}
    return load_user_profiles().get(str(user_id), {})


def user_skill_level(user_id):
    return user_profile(user_id).get("skill_level")


def user_preference(user_id, key, default=None):
    preferences = user_profile(user_id).get("preferences", {})
    if not isinstance(preferences, dict):
        return default
    return preferences.get(key, default)


def set_user_preference(user_id, key, value):
    profiles = load_user_profiles()
    profile = profiles.setdefault(str(user_id), {})
    preferences = profile.setdefault("preferences", {})
    if not isinstance(preferences, dict):
        preferences = {}
        profile["preferences"] = preferences
    preferences[key] = value
    save_user_profiles(profiles)
    return profile


def set_user_skill_level(user_id, skill_level):
    profiles = load_user_profiles()
    profile = profiles.setdefault(str(user_id), {})
    profile["skill_level"] = skill_level
    save_user_profiles(profiles)
    return profile


def mark_skill_onboarding_prompted(user_id):
    profiles = load_user_profiles()
    profile = profiles.setdefault(str(user_id), {})
    profile["skill_onboarding_prompted"] = True
    save_user_profiles(profiles)
    return profile


def skill_onboarding_prompted(user_id):
    return bool(user_profile(user_id).get("skill_onboarding_prompted"))


def load_bot_config():
    if not BOT_CONFIG_FILE.exists():
        return DEFAULT_BOT_CONFIG.copy()

    try:
        config = json.loads(BOT_CONFIG_FILE.read_text())
    except json.JSONDecodeError:
        return DEFAULT_BOT_CONFIG.copy()

    merged_config = DEFAULT_BOT_CONFIG.copy()
    merged_config.update(config)
    return merged_config


def save_bot_config(config):
    BOT_CONFIG_FILE.write_text(json.dumps(config, indent=2, sort_keys=True))


def live_alerts_enabled():
    return bool(load_bot_config().get("live_alerts_enabled", False))


def main_chat_safe_mode_enabled():
    return not live_alerts_enabled()


def split_env_ids(value):
    if not value:
        return set()
    return {str(item).strip() for item in str(value).replace(";", ",").split(",") if str(item).strip()}


def configured_owner_ids():
    owner_ids = set()
    for env_name in ("OWNER_ID", "TELEGRAM_OWNER_ID", "OWNER_TELEGRAM_ID"):
        value = os.getenv(env_name)
        if value:
            owner_ids.add(str(value).strip())
    owner_ids.update(split_env_ids(os.getenv("OWNER_IDS")))
    return {owner_id for owner_id in owner_ids if owner_id}


def configured_admin_ids():
    admin_ids = set(configured_owner_ids())
    for env_name in ("ADMIN_ID", "TELEGRAM_ADMIN_ID", "ADMIN_TELEGRAM_ID"):
        value = os.getenv(env_name)
        if value:
            admin_ids.add(str(value).strip())
    admin_ids.update(split_env_ids(os.getenv("ADMIN_IDS")))
    admin_ids.update(split_env_ids(os.getenv("TELEGRAM_ADMIN_IDS")))
    admin_ids.update(split_env_ids(os.getenv("ADMIN_TELEGRAM_IDS")))
    return {admin_id for admin_id in admin_ids if admin_id}


def owner_telegram_id():
    owner_ids = sorted(configured_owner_ids())
    return owner_ids[0] if owner_ids else ""


def admin_telegram_ids():
    return configured_admin_ids()


def telegram_user_id(source_chat=None, from_user=None, fallback_chat_id=""):
    from_user = from_user or {}
    source_chat = source_chat or {}
    if from_user.get("id"):
        return str(from_user["id"])
    return str(source_chat.get("id", fallback_chat_id))


def is_owner_user(user_id):
    return str(user_id) in {str(owner_id) for owner_id in configured_owner_ids()}


def is_admin_user(user_id):
    return str(user_id) in {str(admin_id) for admin_id in admin_telegram_ids()}


def username_from_user(from_user):
    from_user = from_user or {}
    username = from_user.get("username") or ""
    if username:
        return f"@{username}"
    first_name = from_user.get("first_name") or ""
    last_name = from_user.get("last_name") or ""
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    return full_name or "Unknown"


def value_with_type(value):
    return f"{value!r} ({type(value).__name__})"


def configured_id_debug_values():
    env_names = [
        "OWNER_ID",
        "OWNER_IDS",
        "TELEGRAM_OWNER_ID",
        "OWNER_TELEGRAM_ID",
        "ADMIN_ID",
        "ADMIN_IDS",
        "TELEGRAM_ADMIN_ID",
        "ADMIN_TELEGRAM_ID",
        "TELEGRAM_ADMIN_IDS",
        "ADMIN_TELEGRAM_IDS",
    ]
    return {env_name: os.getenv(env_name) for env_name in env_names}


def log_mode_command_debug(command_text, user_id, username, chat_id):
    owner_ids = sorted(configured_owner_ids())
    admin_ids = sorted(admin_telegram_ids())
    normalized_user_id = str(user_id)
    normalized_admin_ids = {str(admin_id) for admin_id in admin_ids}
    admin_check = normalized_user_id in normalized_admin_ids
    configured_values = configured_id_debug_values()
    print("----------------------------------------")
    print("Command:")
    print(command_text)
    print("")
    print("update.effective_user.id:")
    print(value_with_type(user_id) if user_id else "Unknown")
    print("")
    print("update.effective_user.username:")
    print(value_with_type(username))
    print("")
    print("update.effective_chat.id:")
    print(value_with_type(chat_id) if chat_id else "Unknown")
    print("")
    print("Configured OWNER_ID / OWNER_IDS / ADMIN_ID values:")
    for name, value in configured_values.items():
        print(f"{name}: {value_with_type(value)}")
    print(f"TELEGRAM_CHAT_ID destination only: {value_with_type(os.getenv('TELEGRAM_CHAT_ID'))}")
    print("")
    print("Normalized Owner ID(s):")
    print(", ".join(owner_ids) if owner_ids else "Not configured")
    print("")
    print("Normalized Admin ID(s):")
    print(", ".join(admin_ids) if admin_ids else "Not configured")
    print("")
    print("Comparison:")
    print(f"str(update.effective_user.id): {normalized_user_id!r}")
    print(f"normalized admin set: {sorted(normalized_admin_ids)}")
    print("")
    print("Admin Check Result:")
    print(admin_check)
    if not admin_check:
        print("")
        print("Permission mismatch:")
        print(f"Bot received Telegram User ID: {normalized_user_id!r}")
        print(f"Bot expected one of: {sorted(normalized_admin_ids) if normalized_admin_ids else 'Not configured'}")
    print("----------------------------------------")


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
        f"Candle Close Time: {eastern_time_from_timestamp(timestamp_ms)}\n"
        f"Alert Sent Time: {eastern_time_now()}\n"
    )


def telegram_http_session():
    global TELEGRAM_HTTP_SESSION
    if TELEGRAM_HTTP_SESSION is None:
        TELEGRAM_HTTP_SESSION = requests.Session()
    return TELEGRAM_HTTP_SESSION


def send_telegram_message(token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = json.dumps(reply_markup)
        response = telegram_http_session().post(
            url,
            json=payload,
            timeout=20,
        )
        if response.status_code != 200:
            print(f"[WARN] Telegram send failed: {response.status_code} {response.text}")
    except Exception as e:
        print(f"[WARN] Telegram send exception: {e}")


def answer_telegram_callback(token, callback_query_id, text=""):
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    try:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        response = telegram_http_session().post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"[WARN] Telegram callback answer failed: {response.status_code} {response.text}")
    except Exception as e:
        print(f"[WARN] Telegram callback answer exception: {e}")


def clear_telegram_message_keyboard(token, chat_id, message_id):
    if not chat_id or not message_id:
        return False
    url = f"https://api.telegram.org/bot{token}/editMessageReplyMarkup"
    try:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": json.dumps({"inline_keyboard": []}),
        }
        response = telegram_http_session().post(url, json=payload, timeout=10)
        if response.status_code != 200:
            if response.status_code == 400 and "message is not modified" in response.text.lower():
                return True
            log_warn(f"Telegram keyboard cleanup failed: {response.status_code} {response.text}")
            return False
        return True
    except Exception as error:
        log_warn(f"Telegram keyboard cleanup exception: {error}")
        return False


def clear_callback_message_keyboard(telegram_token, callback_query):
    message = (callback_query or {}).get("message") or {}
    chat = message.get("chat") or {}
    return clear_telegram_message_keyboard(
        telegram_token,
        str(chat.get("id") or ""),
        message.get("message_id"),
    )


def send_telegram_photo(token, chat_id, photo_path, caption="", reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(photo_path, "rb") as photo:
            payload = {
                "chat_id": chat_id,
                "caption": caption[:1024],
                "parse_mode": "HTML",
            }
            if reply_markup is not None:
                payload["reply_markup"] = json.dumps(reply_markup)
            response = telegram_http_session().post(
                url,
                data=payload,
                files={"photo": photo},
                timeout=30,
            )
        if response.status_code != 200:
            print(f"[WARN] Telegram photo send failed: {response.status_code} {response.text}")
            return False
        return True
    except Exception as e:
        print(f"[WARN] Telegram photo send exception: {e}")
        return False


def send_telegram_photo_url(token, chat_id, photo_url, caption=""):
    if not photo_url:
        return False
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        response = telegram_http_session().post(
            url,
            json={
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": caption[:1024],
                "parse_mode": "HTML",
            },
            timeout=20,
        )
        if response.status_code != 200:
            log_warn(f"Telegram photo URL send failed: {response.status_code} {response.text}")
            return False
        return True
    except Exception as error:
        log_warn(f"Telegram photo URL send exception: {error}")
        return False


def send_telegram_media_group(token, chat_id, photo_paths):
    photo_paths = list(photo_paths or [])
    if not photo_paths:
        return False
    if len(photo_paths) == 1:
        return send_telegram_photo(token, chat_id, photo_paths[0])

    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    files = {}
    handles = []
    try:
        media = []
        for index, photo_path in enumerate(photo_paths):
            attachment_name = f"photo{index}"
            photo = open(photo_path, "rb")
            handles.append(photo)
            files[attachment_name] = photo
            media.append({"type": "photo", "media": f"attach://{attachment_name}"})

        response = telegram_http_session().post(
            url,
            data={
                "chat_id": chat_id,
                "media": json.dumps(media),
            },
            files=files,
            timeout=60,
        )
        if response.status_code != 200:
            print(f"[WARN] Telegram media group send failed: {response.status_code} {response.text}")
            return False
        return True
    except Exception as e:
        print(f"[WARN] Telegram media group send exception: {e}")
        return False
    finally:
        for handle in handles:
            try:
                handle.close()
            except Exception:
                pass


def register_bot_commands(token):
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    try:
        response = telegram_http_session().post(
            url,
            json={"commands": PUBLIC_BOT_COMMANDS},
            timeout=20,
        )
        if response.status_code != 200:
            log_warn(f"Telegram command registration failed: {response.status_code} {response.text}")
            return False
        log_info("Telegram command menu registered.")
        return True
    except Exception as error:
        log_warn(f"Telegram command registration exception: {error}")
        return False


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


def get_telegram_updates(token, offset=None, poll_timeout=1):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"timeout": poll_timeout}
    if offset is not None:
        params["offset"] = offset

    response = telegram_http_session().get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json().get("result", [])


def handled_telegram_callback_ids(command_state):
    handled_ids = command_state.setdefault("handled_callback_ids", [])
    if not isinstance(handled_ids, list):
        handled_ids = []
        command_state["handled_callback_ids"] = handled_ids
    return handled_ids


def telegram_callback_already_handled(command_state, callback_query_id):
    if not callback_query_id:
        return False
    return str(callback_query_id) in set(handled_telegram_callback_ids(command_state))


def mark_telegram_callback_handled(command_state, callback_query_id):
    if not callback_query_id:
        return
    callback_query_id = str(callback_query_id)
    handled_ids = handled_telegram_callback_ids(command_state)
    if callback_query_id in handled_ids:
        return
    handled_ids.append(callback_query_id)
    del handled_ids[:-TELEGRAM_CALLBACK_DEDUPE_LIMIT]


def handled_telegram_message_keys(command_state):
    handled_keys = command_state.setdefault("handled_message_keys", [])
    if not isinstance(handled_keys, list):
        handled_keys = []
        command_state["handled_message_keys"] = handled_keys
    return handled_keys


def telegram_message_dedupe_key(message, text):
    message = message or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if chat_id is None or message_id is None or not text:
        return None
    return f"{chat_id}:{message_id}:{text.strip()}"


def telegram_message_already_handled(command_state, message_key):
    if not message_key:
        return False
    return str(message_key) in set(handled_telegram_message_keys(command_state))


def mark_telegram_message_handled(command_state, message_key):
    if not message_key:
        return
    message_key = str(message_key)
    handled_keys = handled_telegram_message_keys(command_state)
    if message_key in handled_keys:
        return
    handled_keys.append(message_key)
    del handled_keys[:-TELEGRAM_CALLBACK_DEDUPE_LIMIT]


def heavy_command_action_for_text(message_text):
    if is_snapshot_command(message_text):
        return "snapshot"
    if is_research_command(message_text):
        return "research"
    if is_whynot_command(message_text):
        return "whynot"
    return ""


def should_enqueue_heavy_command(message_text):
    return bool(heavy_command_action_for_text(message_text)) and len(message_text.strip().split()) >= 2


def telegram_command_job_weight(action):
    return TELEGRAM_JOB_HEAVY if action in HEAVY_TELEGRAM_JOB_ACTIONS else TELEGRAM_JOB_LIGHT


def telegram_command_job_estimate_seconds(job):
    weight = job.get("weight") or telegram_command_job_weight(job.get("action"))
    if weight == TELEGRAM_JOB_LIGHT:
        return TELEGRAM_LIGHT_JOB_ESTIMATE_SECONDS
    return TELEGRAM_JOB_BUDGET_SECONDS_PER_CHUNK + 1


def telegram_command_job_ticker(message_text):
    parts = str(message_text or "").strip().split()
    if len(parts) < 2:
        return ""
    symbol = normalize_trade_symbol_input(parts[1])
    return base_symbol(symbol) if symbol else str(parts[1]).strip().upper()


def heavy_job_ack_message(action, message_text):
    ticker = telegram_command_job_ticker(message_text)
    if action == "research":
        return f"Building your {ticker} research brief - one moment."
    if action == "snapshot":
        return f"Building your {ticker} snapshot - one moment."
    if action == "whynot":
        return f"Checking {ticker} now - one moment."
    return "Building that for you - one moment."


def cached_coingecko_metadata_for_message(message_text):
    parts = str(message_text or "").strip().split()
    if len(parts) < 2:
        return None
    symbol = normalize_trade_symbol_input(parts[1])
    coin_id = coingecko_coin_id_for_symbol(symbol)
    if not coin_id:
        return None
    return cached_coingecko_coin_metadata(coin_id)


def ack_link(label, url):
    clean_url = str(url or "").strip()
    if not clean_url:
        return ""
    return f'<a href="{html.escape(clean_url, quote=True)}">{html.escape(label)}</a>'


def heavy_job_ack_links(metadata):
    links = [
        ack_link("Site", metadata.get("homepage_url")),
        ack_link("Whitepaper", metadata.get("whitepaper_url")),
    ]
    explorer_urls = metadata.get("explorer_urls") or []
    if explorer_urls:
        links.append(ack_link("Explorer", explorer_urls[0]))
    return " / ".join(link for link in links if link)


def heavy_job_ack_caption(action, message_text, metadata):
    ticker = telegram_command_job_ticker(message_text)
    name = str(metadata.get("name") or ticker).strip()
    symbol = str(metadata.get("symbol") or ticker).strip().upper()
    links = heavy_job_ack_links(metadata)
    lines = [
        f"<b>{html.escape(name)} ({html.escape(symbol)})</b>",
        heavy_job_ack_message(action, message_text),
    ]
    if links:
        lines.append(f"Official sources: {links}")
    lines.append("Always read the project's own docs - don't take anyone's word for it, including ours.")
    return "\n".join(lines)


def send_heavy_job_ack_card(telegram_token, chat_id, action, message_text):
    if action not in {"research", "snapshot"}:
        return False
    metadata = cached_coingecko_metadata_for_message(message_text)
    if not metadata:
        return False
    image_url = str(metadata.get("image_url") or "").strip()
    if not image_url:
        return False
    return send_telegram_photo_url(
        telegram_token,
        chat_id,
        image_url,
        caption=heavy_job_ack_caption(action, message_text, metadata),
    )


def send_heavy_job_acknowledgment(telegram_token, chat_id, action, message_text):
    if telegram_command_job_weight(action) != TELEGRAM_JOB_HEAVY:
        return
    try:
        if send_heavy_job_ack_card(telegram_token, chat_id, action, message_text):
            return
    except Exception as error:
        log_warn(f"Could not send {action} job acknowledgment card to {chat_id}: {error}")
    try:
        send_telegram_message(telegram_token, chat_id, heavy_job_ack_message(action, message_text))
    except Exception as error:
        log_warn(f"Could not send {action} job acknowledgment to {chat_id}: {error}")


def enqueue_telegram_command_job(action, telegram_chat_id, message_text, source_chat=None, from_user=None):
    if len(TELEGRAM_COMMAND_JOB_QUEUE) >= TELEGRAM_COMMAND_JOB_QUEUE_LIMIT:
        log_warn(f"Telegram command job queue full; dropped {action} job for {message_text!r}.")
        return False
    TELEGRAM_COMMAND_JOB_QUEUE.append(
        {
            "action": action,
            "telegram_chat_id": str(telegram_chat_id),
            "message_text": message_text,
            "source_chat": source_chat or {"id": telegram_chat_id, "type": "private"},
            "from_user": from_user or {},
            "weight": telegram_command_job_weight(action),
        }
    )
    return True


def run_telegram_command_job(exchange, telegram_token, job):
    action = job.get("action")
    telegram_chat_id = job.get("telegram_chat_id")
    message_text = job.get("message_text", "")
    source_chat = job.get("source_chat") or {"id": telegram_chat_id, "type": "private"}
    from_user = job.get("from_user") or {}

    if action == "snapshot":
        handle_levels_command(
            exchange,
            telegram_token,
            telegram_chat_id,
            message_text,
            source_chat=source_chat,
            from_user=from_user,
        )
        return True
    if action == "research":
        handle_research_command(
            exchange,
            telegram_token,
            telegram_chat_id,
            message_text,
            source_chat=source_chat,
            from_user=from_user,
        )
        return True
    if action == "whynot":
        handle_whynot_command(
            exchange,
            telegram_token,
            telegram_chat_id,
            message_text,
            source_chat=source_chat,
            from_user=from_user,
        )
        return True

    log_warn(f"Unknown Telegram command job action: {action}")
    return False


def process_telegram_command_jobs(
    exchange,
    telegram_token,
    max_jobs=TELEGRAM_COMMAND_JOB_BATCH_LIMIT,
    time_budget_seconds=None,
    allowed_weights=None,
):
    processed = 0
    inspected = 0
    initial_queue_size = len(TELEGRAM_COMMAND_JOB_QUEUE)
    started_at = time.perf_counter()
    allowed_weights = set(allowed_weights or [])
    while TELEGRAM_COMMAND_JOB_QUEUE and processed < max_jobs and inspected < initial_queue_size:
        job = TELEGRAM_COMMAND_JOB_QUEUE.popleft()
        inspected += 1
        weight = job.get("weight") or telegram_command_job_weight(job.get("action"))
        if allowed_weights and weight not in allowed_weights:
            TELEGRAM_COMMAND_JOB_QUEUE.append(job)
            continue
        if time_budget_seconds is not None:
            elapsed = time.perf_counter() - started_at
            remaining = time_budget_seconds - elapsed
            if remaining < telegram_command_job_estimate_seconds(job):
                TELEGRAM_COMMAND_JOB_QUEUE.appendleft(job)
                break
        try:
            run_telegram_command_job(exchange, telegram_token, job)
        except Exception as error:
            log_warn(f"Telegram command job failed for {job.get('action')}: {error}")
        processed += 1
        if (
            time_budget_seconds is not None
            and time.perf_counter() - started_at >= time_budget_seconds
        ):
            break
    return processed


def bot_username_text():
    clean_username = str(os.getenv("TELEGRAM_BOT_USERNAME", BOT_USERNAME)).strip().lstrip("@")
    if clean_username:
        return f"@{clean_username}"
    return "@Poinkle_Bot"


def poinkle_alpha_chat_id():
    return str(os.getenv("POINKLE_ALPHA_CHAT_ID") or os.getenv("TEST_CHAT_ID") or "").strip()


def is_alpha_onboarding_chat(chat):
    alpha_chat_id = poinkle_alpha_chat_id()
    return bool(alpha_chat_id) and str(chat.get("id", "")) == alpha_chat_id and not is_private_chat(chat)


def alpha_onboarding_message():
    return (
        "👋 Welcome to Poinkle Alpha.\n\n"
        "Try:\n\n"
        "/snapshot BTC\n"
        "/snap ETH\n"
        "/help\n\n"
        "Layer 1 helps you read:\n"
        "Trend → Key Levels → Liquidity → Confirmation → Decision\n\n"
        "Educational market structure only.\n"
        "Not financial advice."
    )


def skill_onboarding_message():
    return (
        "Hey — quick one before we go further. When you look at a chart "
        "like this, are you mostly still getting your bearings, or do "
        "things like support, resistance, and RSI already make sense to "
        "you?\n\n"
        "Reply with one:\n"
        "Still getting my bearings\n"
        "This already makes sense to me"
    )


def maybe_send_skill_onboarding(telegram_token, source_chat, from_user, allow_private=False):
    source_chat = source_chat or {}
    from_user = from_user or {}
    source_is_private = is_private_chat(source_chat)
    if source_is_private and not allow_private:
        return False
    if from_user.get("is_bot"):
        return False

    user_id = str(from_user.get("id") or "")
    if not user_id and source_is_private and allow_private:
        user_id = str(source_chat.get("id") or "")
    if not user_id:
        return False
    if user_skill_level(user_id) or skill_onboarding_prompted(user_id):
        return False

    try:
        send_telegram_message(telegram_token, user_id, skill_onboarding_message())
    except Exception as error:
        log_warn(f"Could not DM skill onboarding to user {user_id}: {error}")
    finally:
        mark_skill_onboarding_prompted(user_id)
    return True


def parse_skill_level_reply(text):
    normalized = " ".join(str(text or "").strip().lower().split())
    if normalized == "still getting my bearings":
        return "beginner"
    if normalized == "this already makes sense to me":
        return "experienced"
    return None


def handle_skill_level_reply(telegram_token, chat, text, from_user=None):
    if not is_private_chat(chat or {}):
        return False
    skill_level = parse_skill_level_reply(text)
    if not skill_level:
        return False
    user_id = telegram_user_id(chat, from_user, str((chat or {}).get("id", "")))
    if not user_id:
        return False

    set_user_skill_level(user_id, skill_level)
    if skill_level == "beginner":
        message = "Got it. I’ll keep the chart notes a little more plain-language."
    else:
        message = "Got it. I’ll keep the chart notes tighter."
    send_telegram_message(telegram_token, str((chat or {}).get("id", user_id)), message)
    return True


def maybe_send_alpha_onboarding(telegram_token, chat, text, from_user):
    if not is_alpha_onboarding_chat(chat):
        return False
    if not text or text.startswith("/"):
        return False
    if (from_user or {}).get("is_bot"):
        return False

    user_id = str((from_user or {}).get("id") or "")
    if not user_id or user_id in ALPHA_ONBOARDED_USERS:
        return False

    ALPHA_ONBOARDED_USERS.add(user_id)
    send_telegram_message(
        telegram_token,
        str(chat.get("id")),
        alpha_onboarding_message(),
    )
    return True


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
                    f"{timeframe}:fallback",
                    f"{symbol}: {timeframe} candles unavailable. Using fallback candles.",
                )
                return fallback
            except Exception:
                pass

        handled_error = MarketDataError(candle_error_message(symbol, error))
        throttled_log_warn(symbol, f"{timeframe}:{handled_error}", f"{handled_error}")
        raise handled_error from error


PRICE_SOURCE_LIVE_TICKER = "live_ticker"
PRICE_SOURCE_DAILY_CLOSE_FALLBACK = "daily_close_fallback"


def get_current_market_price_info(exchange, symbol, fallback_price):
    source = resolve_data_source(symbol)
    source_label = "Kraken" if source == "kraken" else "Coinbase"
    try:
        if source == "kraken":
            ticker_exchange = kraken_exchange()
            if ticker_exchange is None:
                raise RuntimeError("Kraken exchange unavailable")
            ticker = ticker_exchange.fetch_ticker(kraken_ohlcv_symbol(symbol))
        else:
            ticker = exchange.fetch_ticker(symbol)
        price = ticker.get("last") or ticker.get("close")
        if price is None:
            return {
                "price": float(fallback_price),
                "price_source": PRICE_SOURCE_DAILY_CLOSE_FALLBACK,
            }
        return {
            "price": float(price),
            "price_source": PRICE_SOURCE_LIVE_TICKER,
        }
    except Exception as error:
        throttled_log_warn(
            symbol,
            "ticker",
            f"{symbol}: {source_label} ticker fetch failed. Using fallback price.",
        )
        return {
            "price": float(fallback_price),
            "price_source": PRICE_SOURCE_DAILY_CLOSE_FALLBACK,
        }


def get_current_market_price(exchange, symbol, fallback_price):
    return get_current_market_price_info(exchange, symbol, fallback_price)["price"]


def get_key_levels(symbol, current_market_price):
    if TEST_MODE:
        return {
            "support": [current_market_price * 0.999],
            "resistance": [current_market_price * 1.001],
        }

    return KEY_LEVELS.get(symbol, {})


def format_level(level):
    return f"{level:.8g}"


def normalize_trade_symbol_input(command_symbol):
    clean_symbol = command_symbol.strip().upper().replace("@", " ").split()[0]
    if not clean_symbol:
        return None

    if clean_symbol.startswith(("/LEVELS", "/RESEARCH", "/WATCH", "/UNWATCH")):
        return None

    clean_symbol = clean_symbol.replace("-", "/")
    if "/" in clean_symbol:
        base, _, quote = clean_symbol.partition("/")
        base = SYMBOL_ALIASES.get(base, base)
        clean_symbol = f"{base}/{quote or 'USD'}"
    else:
        clean_symbol = SYMBOL_ALIASES.get(clean_symbol, clean_symbol)

    if "/" not in clean_symbol:
        clean_symbol = f"{clean_symbol}/USD"

    return clean_symbol


def normalize_symbol(command_symbol):
    clean_symbol = normalize_trade_symbol_input(command_symbol)
    if not clean_symbol:
        return None

    for watch_symbol in WATCHLIST:
        if clean_symbol == watch_symbol or clean_symbol == watch_symbol.replace("/", ""):
            return watch_symbol

    return None


def validate_tradeable_symbol(exchange, user_input):
    symbol = normalize_trade_symbol_input(user_input)
    if not symbol:
        return None

    try:
        if resolve_data_source(symbol) == "kraken":
            kraken = kraken_exchange()
            if kraken is None:
                return None
            markets = kraken.load_markets()
            kraken_symbol = kraken_ohlcv_symbol(symbol)
            market_symbols = {str(market_symbol).upper() for market_symbol in markets}
            return kraken_symbol if kraken_symbol.upper() in market_symbols else None

        markets = exchange.load_markets()
        market_symbols = {str(market_symbol).upper() for market_symbol in markets}
        return symbol if symbol.upper() in market_symbols else None
    except Exception as error:
        log_warn(f"Could not validate watchlist symbol {symbol}: {error}")
        return None


def build_scan_symbols():
    symbols = []
    seen = set()

    def add_symbol(symbol):
        normalized_symbol = normalize_trade_symbol_input(str(symbol or ""))
        if (
            not normalized_symbol
            or normalized_symbol in seen
            or normalized_symbol in UNSUPPORTED_SYMBOLS_THIS_SESSION
        ):
            return False
        symbols.append(normalized_symbol)
        seen.add(normalized_symbol)
        return True

    for symbol in WATCHLIST:
        add_symbol(symbol)

    skipped_user_symbols = 0
    for user_symbols in load_user_watchlists().values():
        if not isinstance(user_symbols, list):
            continue
        for symbol in user_symbols:
            normalized_symbol = normalize_trade_symbol_input(str(symbol or ""))
            if (
                not normalized_symbol
                or normalized_symbol in seen
                or normalized_symbol in UNSUPPORTED_SYMBOLS_THIS_SESSION
            ):
                continue
            if len(symbols) >= MAX_TOTAL_SCAN_SYMBOLS:
                skipped_user_symbols += 1
                continue
            add_symbol(normalized_symbol)

    if skipped_user_symbols:
        log_warn(
            f"Skipped {skipped_user_symbols} user watchlist symbol(s): "
            f"scan symbol cap is {MAX_TOTAL_SCAN_SYMBOLS}."
        )

    return symbols


def users_watching_symbol(symbol):
    normalized_symbol = normalize_trade_symbol_input(symbol)
    if not normalized_symbol:
        return []

    watching_users = []
    for user_id, user_symbols in load_user_watchlists().items():
        if not isinstance(user_symbols, list):
            continue
        normalized_user_symbols = {
            normalize_trade_symbol_input(user_symbol)
            for user_symbol in user_symbols
        }
        if normalized_symbol in normalized_user_symbols:
            watching_users.append(str(user_id))
    return watching_users


def personal_watchlist_delivery_key(user_id, symbol, candle_id, alerts):
    alert_types = "+".join(sorted(alert.get("type", "") for alert in alerts if alert.get("type")))
    return f"{user_id}|{symbol}|{candle_id}|{alert_types}"


def deliver_personal_watchlist_alerts(
    state,
    telegram_token,
    symbol,
    candle,
    alert_group,
    ema_21,
    ema_55,
    current_rsi,
    volume_avg,
    alert_candles=None,
    supports=None,
    resistances=None,
):
    delivery_state = state.setdefault("__personal_watchlist_deliveries", {})
    for user_id in users_watching_symbol(symbol):
        delivery_key = personal_watchlist_delivery_key(user_id, symbol, str(candle[0]), alert_group)
        if delivery_key in delivery_state:
            continue
        try:
            send_alert_group_to_chat(
                telegram_token,
                user_id,
                symbol,
                candle,
                alert_group,
                ema_21,
                ema_55,
                current_rsi,
                volume_avg,
                alert_candles=alert_candles,
                supports=supports,
                resistances=resistances,
            )
            delivery_state[delivery_key] = iso_utc_now()
            save_state(state)
            log_info(f"Sent personal watchlist alert to {user_id}: {symbol}")
        except Exception as error:
            log_warn(f"Could not send personal watchlist alert to {user_id} for {symbol}: {error}")


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


def price_display_text(price, price_source=None):
    price_text = format_zone_price(price)
    if price_source == PRICE_SOURCE_DAILY_CLOSE_FALLBACK:
        return f"{price_text} (daily close - live price unavailable)"
    return price_text


def chart_data_status_label(price_source=None, last_updated_label=None):
    details = []
    if last_updated_label:
        details.append(last_updated_label)
    if price_source == PRICE_SOURCE_DAILY_CLOSE_FALLBACK:
        details.append("daily close - live price unavailable")
    return " • ".join(details)


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


def dedupe_price_levels(levels, reference_price):
    threshold = abs(reference_price) * (SR_LEVEL_DEDUPE_PCT / 100)
    deduped = []
    for level in sorted(level for level in levels if level > 0):
        if all(abs(level - existing) > threshold for existing in deduped):
            deduped.append(level)
    return deduped


def daily_support_resistance_levels(candles, current_price):
    support = find_swing_levels(candles, "low", lookback=SR_SWING_LOOKBACK)
    resistance = find_swing_levels(candles, "high", lookback=SR_SWING_LOOKBACK)
    support = [
        level
        for level in dedupe_price_levels(support, current_price)
        if level < current_price
    ]
    resistance = [
        level
        for level in dedupe_price_levels(resistance, current_price)
        if level > current_price
    ]
    support = sorted(support, key=lambda level: current_price - level)[:SR_MAX_LEVELS_PER_SIDE]
    resistance = sorted(resistance, key=lambda level: level - current_price)[:SR_MAX_LEVELS_PER_SIDE]
    return {
        "support": support,
        "resistance": resistance,
    }


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


def grade_patience(score):
    if score >= 80:
        return "A", "Excellent accumulation"
    if score >= 65:
        return "B", "Good accumulation"
    if score >= 50:
        return "C", "Neutral"
    if score >= 35:
        return "D", "Weak accumulation"
    return "F", "Avoid"


def score_patience_setup(
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

    grade, label = grade_patience(score)
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


def validation_finding(message, severity="hard"):
    return {"severity": severity, "message": message}


def is_real_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def is_valid_timestamp(value):
    if not value:
        return False
    if isinstance(value, (int, float)):
        return value > 0
    text = str(value).strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.timestamp() > 0


def validate_required_fields(data, field_names):
    findings = []
    for field_name in field_names:
        if data.get(field_name) is None:
            findings.append(validation_finding(f"{field_name} is missing"))
    return findings


def validate_market_snapshot_data(data):
    findings = validate_required_fields(
        data,
        (
            "current_price",
            "rsi",
            "ema_21",
            "ema_55",
            "volume_average",
            "volume_multiple",
            "range_low",
            "range_high",
            "range_position",
            "market_score",
            "last_updated",
            "accumulation",
        ),
    )

    current_price = data.get("current_price")
    if not is_real_number(current_price) or current_price <= 0:
        findings.append(validation_finding("current_price must be greater than 0"))

    current_rsi = data.get("rsi")
    if not is_real_number(current_rsi) or not 0 <= current_rsi <= 100:
        findings.append(validation_finding("rsi must be between 0 and 100"))

    for field_name in ("ema_21", "ema_55"):
        value = data.get(field_name)
        if not is_real_number(value) or value <= 0:
            findings.append(validation_finding(f"{field_name} must be greater than 0"))

    volume_average = data.get("volume_average")
    if not is_real_number(volume_average) or volume_average < 0:
        findings.append(validation_finding("volume_average must be 0 or greater"))

    volume_multiple = data.get("volume_multiple")
    if not is_real_number(volume_multiple) or volume_multiple < 0:
        findings.append(validation_finding("volume_multiple must be 0 or greater"))

    range_low = data.get("range_low")
    range_high = data.get("range_high")
    if not is_real_number(range_low) or not is_real_number(range_high):
        findings.append(validation_finding("range_low and range_high must be numeric"))
    elif range_low > range_high:
        findings.append(validation_finding("range_low must be less than or equal to range_high"))

    range_position = data.get("range_position")
    if not is_real_number(range_position) or not 0 <= range_position <= 1:
        findings.append(validation_finding("range_position must be a 0-1 fraction"))

    market_score = data.get("market_score")
    if not is_real_number(market_score) or not 0 <= market_score <= 100:
        findings.append(validation_finding("market_score must be between 0 and 100"))

    if not is_valid_timestamp(data.get("last_updated")):
        findings.append(validation_finding("last_updated must be a real timestamp"))

    accumulation = data.get("accumulation") or {}
    findings.extend(validate_patience_grade_data(accumulation))

    supports = data.get("support_zones") or []
    resistances = data.get("resistance_zones") or []
    if is_real_number(current_price) and supports and resistances:
        nearest_support = zone_midpoint(supports[0])
        nearest_resistance = zone_midpoint(resistances[0])
        if is_real_number(nearest_support) and is_real_number(nearest_resistance):
            low = min(nearest_support, nearest_resistance)
            high = max(nearest_support, nearest_resistance)
            if not low < current_price < high:
                findings.append(
                    validation_finding(
                        "current_price is outside nearest support/resistance midpoints",
                        severity="warning",
                    )
                )

    return findings


def validate_patience_grade_data(accumulation):
    findings = validate_required_fields(accumulation, ("score", "grade", "label"))
    score = accumulation.get("score")
    if not is_real_number(score) or not 0 <= score <= 100:
        findings.append(validation_finding("patience score must be between 0 and 100"))
        return findings

    expected_grade, expected_label = grade_patience(score)
    if accumulation.get("grade") != expected_grade or accumulation.get("label") != expected_label:
        findings.append(
            validation_finding(
                f"patience grade mismatch: score {score} maps to {expected_grade}/{expected_label}, "
                f"got {accumulation.get('grade')}/{accumulation.get('label')}"
            )
        )
    return findings


def validate_chart_data(data):
    findings = validate_required_fields(
        data,
        ("candles", "current_price", "last_updated", "supports", "resistances", "ema21", "ema55"),
    )
    current_price = data.get("current_price")
    if not is_real_number(current_price) or current_price <= 0:
        findings.append(validation_finding("chart current_price must be greater than 0"))
    if not is_valid_timestamp(data.get("last_updated")):
        findings.append(validation_finding("chart last_updated must be a real timestamp"))
    if not data.get("candles"):
        findings.append(validation_finding("chart candles are missing"))
    for field_name in ("ema21", "ema55"):
        values = data.get(field_name) or []
        if not values or any((not is_real_number(value) or value <= 0) for value in values):
            findings.append(validation_finding(f"chart {field_name} must contain positive values"))
    return findings


def validate_whynot_scorecard_data(data):
    findings = validate_required_fields(
        data,
        (
            "symbol",
            "candle",
            "alerts",
            "scorecard",
            "aligned_count",
            "ema_21",
            "ema_55",
            "rsi",
            "atr_14",
            "volume_average",
            "volume_multiple",
            "range_low",
            "range_high",
            "range_location",
            "range_position",
        ),
    )
    candle = data.get("candle") or []
    current_price = candle[4] if len(candle) > 4 else None

    if not is_real_number(current_price) or current_price <= 0:
        findings.append(validation_finding("current price must be greater than 0"))

    current_rsi = data.get("rsi")
    if not is_real_number(current_rsi) or not 0 <= current_rsi <= 100:
        findings.append(validation_finding("rsi must be between 0 and 100"))

    for field_name in ("ema_21", "ema_55"):
        value = data.get(field_name)
        if not is_real_number(value) or value <= 0:
            findings.append(validation_finding(f"{field_name} must be greater than 0"))

    volume_average = data.get("volume_average")
    if not is_real_number(volume_average) or volume_average < 0:
        findings.append(validation_finding("volume_average must be 0 or greater"))

    volume_multiple = data.get("volume_multiple")
    if not is_real_number(volume_multiple) or volume_multiple < 0:
        findings.append(validation_finding("volume_multiple must be 0 or greater"))

    range_low = data.get("range_low")
    range_high = data.get("range_high")
    if not is_real_number(range_low) or not is_real_number(range_high):
        findings.append(validation_finding("range_low and range_high must be numeric"))
    elif range_low > range_high:
        findings.append(validation_finding("range_low must be less than or equal to range_high"))

    range_position = data.get("range_position")
    if not is_real_number(range_position) or not 0 <= range_position <= 1:
        findings.append(validation_finding("range_position must be a 0-1 fraction"))

    expected_aligned = len(strongest_directional_lightweight_group(data.get("alerts") or []))
    if data.get("aligned_count") != expected_aligned:
        findings.append(
            validation_finding(
                f"aligned_count mismatch: expected {expected_aligned}, got {data.get('aligned_count')}"
            )
        )

    for item in data.get("scorecard") or []:
        for field_name in ("type", "state", "reason"):
            if item.get(field_name) is None:
                findings.append(validation_finding(f"whynot scorecard item missing {field_name}"))

    return findings


def enforce_validation(symbol, card_type, findings):
    hard_failures = [finding for finding in findings if finding.get("severity") != "warning"]
    for finding in findings:
        log_warn(f"Validation {finding.get('severity', 'hard')} for {card_type} {symbol}: {finding.get('message')}")
    if hard_failures:
        raise RuntimeError(f"{card_type} validation failed")


def get_best_use_cases(patience_grade, support_distance_label, range_position, trend_bias, market_structure):
    if range_position == "Near Resistance":
        return ["✓ Trim Position", "✓ Wait For Pullback"]
    if patience_grade in {"A", "B"} and support_distance_label in {"At Support", "Near Support"}:
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


def breakout_confirmation_quality_met(candle, location_filter, candles):
    if len(candles) <= 14:
        return False
    _timestamp, open_price, _high, _low, close, _volume = candle
    body_size = abs(close - open_price)
    return (
        location_filter.get("range_position") == "Upper Range"
        and body_size >= BREAKOUT_BODY_ATR_MULT * atr(candles, 14)
    )


def volume_alert_takeaway(alert, skill_level=None):
    if skill_level == "beginner":
        if alert.get("direction") == "bullish":
            return "Unusual buying volume showed up. Wait to see if price can break and hold a key level."
        if alert.get("direction") == "bearish":
            return "Unusual selling volume showed up. Wait to see if price loses and stays below support."
        return "Unusual volume showed up. Wait for price to pick a direction before reacting."

    if alert.get("direction") == "bullish":
        return "High volume detected. Watch for breakout confirmation."
    if alert.get("direction") == "bearish":
        return "High selling volume detected. Watch for breakdown confirmation."
    return (
        "High volume detected. No trade confirmation yet. "
        "Watch for level break and follow-through."
    )


def secondary_timeframe_context_from_alerts(alerts):
    for alert in alerts or []:
        context = alert.get("secondary_timeframe_context")
        if context:
            return context
    return None


def secondary_timeframe_bias(context):
    if not context:
        return ""
    close = context.get("latest_close")
    ema_21 = context.get("ema_21")
    ema_55 = context.get("ema_55")
    rsi_14 = context.get("rsi_14")
    if close is None or ema_21 is None or ema_55 is None or rsi_14 is None:
        return ""
    if close > ema_21 and ema_21 >= ema_55 and rsi_14 >= 50:
        return "bullish"
    if close < ema_21 and ema_21 <= ema_55 and rsi_14 <= 50:
        return "bearish"
    return "mixed"


def secondary_timeframe_summary(context):
    if not context:
        return ""
    parts = []
    for timeframe in (MIDDLE_TIMEFRAME,):
        timeframe_context = context.get(timeframe)
        bias = secondary_timeframe_bias(timeframe_context)
        if not bias:
            continue
        rsi_14 = timeframe_context.get("rsi_14")
        if rsi_14 is None:
            parts.append(f"{timeframe} {bias}")
        else:
            parts.append(f"{timeframe} {bias} (RSI {rsi_14:.0f})")
    if not parts:
        return ""
    return ", ".join(parts)


def secondary_timeframe_text(alert):
    summary = secondary_timeframe_summary(alert.get("secondary_timeframe_context"))
    if not summary:
        return ""
    return f"<b>6h Context:</b> {summary}\n"


def secondary_timeframe_footer_item(alerts):
    summary = secondary_timeframe_summary(secondary_timeframe_context_from_alerts(alerts))
    if not summary:
        return ""
    return f"3. 6h context: {summary}"


def build_alert(symbol, candle, alert, ema_21, ema_55, current_rsi, volume_avg, skill_level=None):
    timestamp, open_price, high, low, close, volume = candle
    test_mode_text = "🧪 <b>TEST MODE</b>\n" if TEST_MODE else ""
    time_text = alert_time_text(timestamp)
    link_text = official_coin_link_text(symbol)
    secondary_text = secondary_timeframe_text(alert)
    if alert.get("type", "").endswith(":weak_break"):
        trade_plan = alert["trade_plan"]
        location = alert.get("location_filter", {})
        return (
            f"⚠️ <b>{symbol} Weak Break / Watch Only</b>\n\n"
            f"{test_mode_text}"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Timeframe:</b> Daily\n"
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
            f"{secondary_text}"
            f"<b>Next key level:</b> {format_level(location.get('next_target', close))}\n\n"
            f"<b>Reason:</b> Break detected, but momentum/volume did not confirm.\n"
            f"<b>Action:</b> Watch only / No trade confirmation"
            f"{link_text}"
        )

    if alert.get("type", "").endswith(":failed_follow_through"):
        trade_plan = alert["trade_plan"]
        location = alert.get("location_filter", {})
        return (
            f"⚠️ <b>{symbol} Failed Follow-Through</b>\n\n"
            f"{test_mode_text}"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Timeframe:</b> Daily\n"
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
            f"{secondary_text}"
            f"<b>Next key level:</b> {format_level(location.get('next_target', close))}\n\n"
            f"<b>Reason:</b> Price stalled around the broken level with weak volume.\n"
            f"<b>Action:</b> Watch only / No trade confirmation"
            f"{link_text}"
        )

    if alert.get("type", "").endswith(":late_move"):
        location = alert["location_filter"]
        return (
            f"⚠️ <b>{symbol} Late Move / Exhaustion Risk</b>\n\n"
            f"{test_mode_text}"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Timeframe:</b> Daily\n"
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
            f"{secondary_text}"
            f"Avoid chasing. Watch for reclaim, rejection, or reversal."
            f"{link_text}"
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
            f"✅ <b>{symbol} Daily Break Confirmed</b>\n\n"
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
            f"{secondary_text}"
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
            f"{link_text}"
        )

    if alert.get("type") == "volume_spike":
        body_percent = candle_body_percent(open_price, close)
        participation_text = volume_alert_takeaway(alert, skill_level=skill_level)

        return (
            f"{alert['emoji']} <b>{symbol} {alert['label']}</b>\n"
            f"{test_mode_text}"
            f"<b>Timeframe:</b> Daily  |  {time_text.strip()}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>Price:</b> {format_level(close)}  "
            f"(<b>Body:</b> {body_percent:.2f}%)\n"
            f"<b>Volume:</b> {alert['volume_multiple']:.2f}x average\n\n"
            f"<b>RSI:</b> {current_rsi:.2f} — {get_rsi_status(current_rsi)}\n"
            f"<b>EMA21:</b> {format_level(ema_21)}  "
            f"<b>EMA55:</b> {format_level(ema_55)}\n"
            f"{secondary_text}"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"{participation_text}"
            f"{link_text}"
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
        f"⏱️ <b>Timeframe:</b> Daily\n"
        f"🕯️ {time_text}"
        f"{level_text}"
        f"{range_text}"
        f"{warning_text}"
        f"💵 <b>Close:</b> {close:.6g}\n"
        f"📈 <b>EMA 21:</b> {ema_21:.6g}\n"
        f"📉 <b>EMA 55:</b> {ema_55:.6g}\n"
        f"📊 <b>RSI 14:</b> {current_rsi:.2f}\n"
        f"📊 <b>RSI Status:</b> {get_rsi_status(current_rsi)}\n"
        f"{secondary_text}"
        f"🔊 <b>Volume:</b> {volume:.4f}\n"
        f"📦 <b>20-candle avg volume:</b> {volume_avg:.4f}"
        f"{link_text}"
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


LEVEL_BREAK_ALERT_SUFFIXES = (
    ":early_warning",
    ":confirmation",
    ":weak_break",
    ":failed_follow_through",
    ":late_move",
)


def is_level_break_alert(alert):
    alert_type = alert.get("type", "")
    return ("breakout" in alert_type or "breakdown" in alert_type) and alert_type.endswith(
        LEVEL_BREAK_ALERT_SUFFIXES
    )


def should_send_level_break_alert(alert):
    if not is_level_break_alert(alert):
        return True
    return alert.get("type", "").endswith(":confirmation")


def is_bullish_scan_alert(alert):
    alert_type = alert.get("type", "")
    if alert_type in {"rsi_cross_above_70", "ema_cross_above"}:
        return True
    if alert_type == "volume_spike":
        return alert.get("direction") == "bullish"
    if alert_type.endswith(":confirmation"):
        trade_plan = alert.get("trade_plan") or {}
        return trade_plan.get("direction") == "LONG"
    return False


def alert_dedupe_key(alert, reference_price):
    alert_type = alert.get("type", "")
    try:
        parts = alert_type.split(":")
        if len(parts) == 4 and parts[1] in {"breakout", "breakdown"}:
            try:
                level = float(parts[2])
            except (ValueError, TypeError):
                return alert_type

            band = abs(float(reference_price)) * (ALERT_DEDUPE_LEVEL_PCT / 100)
            if band <= 0:
                return alert_type

            bucket = round(level / band)
            return ":".join([parts[0], parts[1], str(bucket), parts[3]])
    except Exception:
        return alert_type

    return alert_type


def is_ema_cross_alert(alert):
    return alert.get("type") in {"ema_cross_above", "ema_cross_below"}


LIGHTWEIGHT_ALERT_TYPES = {
    "volume_spike",
    "ema_cross_above",
    "ema_cross_below",
    "rsi_cross_above_70",
    "rsi_cross_below_30",
}
ALERT_SIGNAL_SCOPE = "Daily signal - snapshot in time, not a trend call"
STABLECOIN_BASE_SYMBOLS = {"DAI", "USDT", "USDC", "BUSD", "TUSD", "USDP", "GUSD", "FRAX"}


def is_lightweight_alert(alert):
    return alert.get("type") in LIGHTWEIGHT_ALERT_TYPES


def is_stablecoin_symbol(symbol):
    return symbol_base(symbol) in STABLECOIN_BASE_SYMBOLS


def lightweight_alert_direction(alert):
    alert_type = alert.get("type")
    if alert_type in {"rsi_cross_above_70", "ema_cross_above"}:
        return "bullish"
    if alert_type in {"rsi_cross_below_30", "ema_cross_below"}:
        return "bearish"
    if alert_type == "volume_spike":
        direction = alert.get("direction")
        if direction in {"bullish", "bearish"}:
            return direction
    return None


def strongest_directional_lightweight_group(alerts):
    by_direction = {}
    for alert in alerts:
        if not is_lightweight_alert(alert):
            continue
        direction = lightweight_alert_direction(alert)
        if not direction:
            continue
        by_direction.setdefault(direction, {})[alert.get("type")] = alert

    qualifying_groups = [
        list(by_type.values())
        for by_type in by_direction.values()
        if len(by_type) >= 2
    ]
    if not qualifying_groups:
        return []

    return max(qualifying_groups, key=len)


def use_full_alert_chart(alerts):
    if len(alerts) >= 2:
        return True
    return any(not is_lightweight_alert(alert) for alert in alerts)


def scan_alert_cooldown_tier(alerts):
    return "tier2" if use_full_alert_chart(alerts) else "tier1"


def scan_alert_cooldown_seconds(tier):
    if tier == "tier2":
        return SCAN_TIER2_ALERT_COOLDOWN_SECONDS
    return SCAN_ALERT_COOLDOWN_SECONDS


def scan_alert_cooldowns(state):
    return state.setdefault("__scan_alert_cooldowns", {})


def should_send_scan_alert_group(state, symbol, alerts, now=None):
    tier = scan_alert_cooldown_tier(alerts)
    cooldown_seconds = scan_alert_cooldown_seconds(tier)
    symbol_cooldowns = scan_alert_cooldowns(state).setdefault(symbol, {})
    last_sent = symbol_cooldowns.get(tier, 0)
    now = int(time.time()) if now is None else int(now)
    if last_sent and now - last_sent < cooldown_seconds:
        return False, tier, cooldown_seconds - (now - last_sent)
    return True, tier, 0


def mark_scan_alert_group_sent(state, symbol, alerts, now=None):
    tier = scan_alert_cooldown_tier(alerts)
    symbol_cooldowns = scan_alert_cooldowns(state).setdefault(symbol, {})
    symbol_cooldowns[tier] = int(time.time()) if now is None else int(now)
    return tier


def scan_alert_history(state):
    return state.setdefault("__scan_alert_history", {})


def trim_scan_alert_history(state, symbol, now=None):
    now = int(time.time()) if now is None else int(now)
    history = scan_alert_history(state).setdefault(symbol, [])
    fresh_history = [
        entry
        for entry in history
        if now - int(entry.get("timestamp", 0)) <= ROLLING_CONFLUENCE_WINDOW_SECONDS
    ]
    scan_alert_history(state)[symbol] = fresh_history
    return fresh_history


def record_scan_alert_history(state, symbol, alerts, now=None):
    now = int(time.time()) if now is None else int(now)
    history = trim_scan_alert_history(state, symbol, now)
    for alert in alerts:
        if not is_lightweight_alert(alert):
            continue
        history.append(
            {
                "type": alert.get("type"),
                "label": alert.get("label", "Market Alert"),
                "emoji": alert.get("emoji", ""),
                "direction": alert.get("direction", ""),
                "volume_multiple": alert.get("volume_multiple"),
                "timestamp": now,
            }
        )
    scan_alert_history(state)[symbol] = history
    return history


def rolling_confluence_alerts(state, symbol, pending_alerts, now=None):
    if not pending_alerts or any(not is_lightweight_alert(alert) for alert in pending_alerts):
        return pending_alerts

    now = int(time.time()) if now is None else int(now)
    history = trim_scan_alert_history(state, symbol, now)
    by_type = {}
    for entry in history:
        alert_type = entry.get("type")
        if alert_type:
            by_type[alert_type] = {
                "type": alert_type,
                "label": entry.get("label", "Market Alert"),
                "emoji": entry.get("emoji", ""),
                "direction": entry.get("direction", ""),
                "volume_multiple": entry.get("volume_multiple"),
            }
    for alert in pending_alerts:
        by_type[alert.get("type")] = alert

    directional_group = strongest_directional_lightweight_group(by_type.values())
    if len(directional_group) < 2:
        return pending_alerts
    return directional_group


def has_lightweight_confluence(alerts):
    return len(strongest_directional_lightweight_group(alerts)) >= 2


def alert_signal_summary(alert):
    alert_type = alert.get("type")
    label = alert.get("label", "Market Alert")
    if alert_type == "volume_spike" and alert.get("volume_multiple") is not None:
        return f"{label} ({alert['volume_multiple']:.2f}x)"
    return label


def severity_label_for_alerts(alerts):
    count = len({alert.get("type") for alert in alerts if alert.get("type")})
    if count <= 2:
        return f"Developing · {count} signals"
    if count == 3:
        return "Building · 3 signals"
    return f"Strong confluence · {count} signals"


def alert_card_data(symbol, candle, alert, ema_21, ema_55, current_rsi, volume_avg, skill_level=None):
    timestamp, open_price, high, low, close, volume = candle
    stats = [
        ("PRICE", format_level(close)),
        ("RSI", f"{current_rsi:.2f}"),
        ("EMA 21 / 55", f"{format_level(ema_21)} / {format_level(ema_55)}"),
    ]
    if alert.get("type") == "volume_spike":
        volume_multiple = alert.get("volume_multiple")
        if volume_multiple is None:
            volume_multiple = volume / volume_avg if volume_avg > 0 else 0
        stats.insert(1, ("VOLUME", f"{volume_multiple:.2f}x avg"))
    elif volume_avg > 0:
        stats.insert(1, ("VOLUME", f"{volume / volume_avg:.2f}x avg"))

    return {
        "symbol": symbol,
        "label": alert.get("label", "Market Alert"),
        "emoji": alert.get("emoji", ""),
        "direction": alert.get("direction", alert.get("type", "")),
        "timeframe": "Daily",
        "timestamp": eastern_time_from_timestamp(timestamp),
        "stats": stats[:4],
        "takeaway": volume_alert_takeaway(alert, skill_level=skill_level)
        if alert.get("type") == "volume_spike"
        else "Signal detected. Wait for confirmation and manage risk.",
        "official_link": official_coin_link(symbol),
    }


def build_alert_snapshot_content(symbol, candle, alerts, ema_21, ema_55, current_rsi, volume_avg):
    timestamp, open_price, high, low, close, volume = candle
    body_percent = candle_body_percent(open_price, close)
    primary_alert = alerts[0]
    signal_lines = [alert_signal_summary(alert) for alert in alerts]
    title_label = "CONFLUENCE ALERT" if len(alerts) >= 2 else primary_alert.get("label", "MARKET ALERT").upper()
    secondary_footer = secondary_timeframe_footer_item(alerts)
    volume_multiple = None
    for alert in alerts:
        if alert.get("type") == "volume_spike":
            volume_multiple = alert.get("volume_multiple")
            break
    if volume_multiple is None:
        volume_multiple = volume / volume_avg if volume_avg > 0 else 0

    return {
        "title": f"{symbol.replace('/', ' / ')} {title_label}",
        "card_specs": [
            ("SIGNALS", "\n+ ".join(signal_lines[:3])),
            ("PRICE", f"{format_level(close)}\nBody {body_percent:.2f}%"),
            ("VOLUME", f"{volume_multiple:.2f}x average\nCurrent candle"),
            ("RSI", f"{current_rsi:.2f}\n{get_rsi_status(current_rsi)}"),
            ("EMA\nCONTEXT", f"21 {format_level(ema_21)}\n55 {format_level(ema_55)}"),
        ],
        "footer_items": [
            f"1. {' + '.join(signal_lines)}",
            f"2. Price {format_level(close)} \u2192 watch confirmation",
            secondary_footer or f"3. Volume {volume_multiple:.2f}x average \u2192 compare follow-through",
        ],
    }


def build_volume_alert_snapshot_content(symbol, candle, alert, ema_21, ema_55, current_rsi):
    return build_alert_snapshot_content(symbol, candle, [alert], ema_21, ema_55, current_rsi, volume_avg=0)


def render_alert_snapshot_chart(symbol, candles, candle, alerts, ema_21, ema_55, current_rsi, volume_avg, supports=None, resistances=None):
    if generate_levels_chart is None:
        raise RuntimeError("Snapshot chart generator unavailable")
    if not candles:
        raise RuntimeError("No alert candles available")
    if not alerts:
        raise RuntimeError("No alerts available")

    content = build_alert_snapshot_content(symbol, candle, alerts, ema_21, ema_55, current_rsi, volume_avg)
    chart_candles = candle_dicts(candles)
    ema21_series = [ema_21] * len(chart_candles)
    ema55_series = [ema_55] * len(chart_candles)
    return generate_levels_chart(
        symbol,
        chart_candles,
        candle[4],
        supports or [],
        resistances or [],
        ema21=ema21_series,
        ema55=ema55_series,
        card_specs=content["card_specs"],
        footer_items=content["footer_items"],
        title=content["title"],
        output_prefix=f"{symbol.replace('/', '_')}_alert_snapshot_",
        signal_scope=ALERT_SIGNAL_SCOPE,
    )


def render_volume_alert_snapshot_chart(symbol, candles, candle, alert, ema_21, ema_55, current_rsi, supports=None, resistances=None):
    return render_alert_snapshot_chart(
        symbol,
        candles,
        candle,
        [alert],
        ema_21,
        ema_55,
        current_rsi,
        volume_avg=0,
        supports=supports,
        resistances=resistances,
    )


def render_lightweight_alert_card(symbol, candle, alert, ema_21, ema_55, current_rsi, volume_avg, skill_level=None):
    if render_alert_card is None:
        raise RuntimeError("Alert card renderer unavailable")
    return render_alert_card(
        alert_card_data(symbol, candle, alert, ema_21, ema_55, current_rsi, volume_avg, skill_level=skill_level),
        logo_path=POINKLE_RESEARCH_EMBLEM_PATH,
    )


def send_alert_to_chat(
    telegram_token,
    chat_id,
    symbol,
    candle,
    alert,
    ema_21,
    ema_55,
    current_rsi,
    volume_avg,
    alert_candles=None,
    supports=None,
    resistances=None,
):
    message = build_alert(symbol, candle, alert, ema_21, ema_55, current_rsi, volume_avg)
    if is_lightweight_alert(alert):
        try:
            card_path = render_lightweight_alert_card(
                symbol,
                candle,
                alert,
                ema_21,
                ema_55,
                current_rsi,
                volume_avg,
            )
            caption = f"{alert.get('emoji', '')} <b>{symbol} {alert['label']}</b>".strip()
            if send_telegram_photo(telegram_token, chat_id, card_path, caption=caption):
                return True
            raise RuntimeError("Alert card send failed")
        except Exception as error:
            log_warn(f"Alert card rendering failed for {symbol}: {error}")

    send_telegram_message(telegram_token, chat_id, message)
    return False


def build_combined_alert_message(symbol, candle, alerts, ema_21, ema_55, current_rsi, volume_avg):
    return "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(
        build_alert(symbol, candle, alert, ema_21, ema_55, current_rsi, volume_avg)
        for alert in alerts
    )


def send_alert_group_to_chat(
    telegram_token,
    chat_id,
    symbol,
    candle,
    alerts,
    ema_21,
    ema_55,
    current_rsi,
    volume_avg,
    alert_candles=None,
    supports=None,
    resistances=None,
):
    if not alerts:
        return False
    if len(alerts) == 1 and not use_full_alert_chart(alerts):
        return send_alert_to_chat(
            telegram_token,
            chat_id,
            symbol,
            candle,
            alerts[0],
            ema_21,
            ema_55,
            current_rsi,
            volume_avg,
            alert_candles=alert_candles,
            supports=supports,
            resistances=resistances,
        )

    severity_label = severity_label_for_alerts(alerts) if len(alerts) >= 2 else ""
    fallback_message = build_combined_alert_message(symbol, candle, alerts, ema_21, ema_55, current_rsi, volume_avg)
    if severity_label:
        fallback_message = f"{severity_label}\n{fallback_message}"
    try:
        chart_path = render_alert_snapshot_chart(
            symbol,
            alert_candles,
            candle,
            alerts,
            ema_21,
            ema_55,
            current_rsi,
            volume_avg,
            supports=supports,
            resistances=resistances,
        )
        signal_label = " + ".join(alert_signal_summary(alert) for alert in alerts)
        caption = f"<b>{symbol} Confluence Alert</b> — {signal_label}"
        if severity_label:
            caption = f"{severity_label}\n{caption}"
        link = official_coin_link(symbol)
        if link:
            caption = f"{caption}\nLearn more: {link}"
        if send_telegram_photo(telegram_token, chat_id, chart_path, caption=caption):
            return True
        raise RuntimeError("Alert snapshot send failed")
    except Exception as error:
        log_warn(f"Alert snapshot rendering failed for {symbol}: {error}")

    send_telegram_message(telegram_token, chat_id, fallback_message)
    return False


def has_volume_alert_context(alerts, active_trade_status=None):
    if active_trade_status in {"Retest Holding", "Retest Failed"}:
        return True

    return any(
        is_break_attempt_alert(alert) or is_ema_cross_alert(alert)
        for alert in alerts
        if alert.get("type") != "volume_spike"
    )


def should_send_telegram_alert(
    alert,
    alerts,
    active_trade_status=None,
    ema_21=None,
    ema_55=None,
    range_location=None,
    current_price=None,
    range_low=None,
    range_high=None,
):
    if alert.get("type") == "rsi_cross_above_70":
        return False

    if is_bullish_scan_alert(alert) and ema_21 is not None and ema_55 is not None and ema_21 < ema_55:
        if not is_deep_in_support_zone(current_price, range_low, range_high):
            return False

    return True


def is_deep_in_support_zone(current_price, range_low, range_high):
    if current_price is None or range_low is None or range_high is None:
        return False
    range_size = range_high - range_low
    if range_size <= 0:
        return False
    return current_price <= range_low + (range_size * SUPPORT_ZONE_DEEP_FRACTION)


def log_suppressed_lightweight_alert(symbol, candle, alerts, reason):
    labels = ", ".join(alert.get("label", "Market Alert") for alert in alerts)
    types = ", ".join(alert.get("type", "unknown") for alert in alerts)
    print(
        "Lightweight signal logged - "
        f"{symbol} {eastern_time_from_timestamp(candle[0])} - "
        f"{labels} ({types}) - {reason}"
    )


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


def candle_dicts(candles):
    return [
        {
            "time": candle[0],
            "open": candle[1],
            "high": candle[2],
            "low": candle[3],
            "close": candle[4],
            "volume": candle[5],
        }
        for candle in candles
    ]


def zone_midpoints(zones):
    return [zone_midpoint(zone) for zone in zones]


def store_levels_chart_data(
    symbol,
    closed_candles,
    current_price,
    ema_21,
    ema_55,
    buy_zones,
    resistance_zones,
    price_source=None,
    last_updated=None,
    last_updated_label=None,
):
    chart_data = {
        "candles": candle_dicts(closed_candles),
        "current_price": current_price,
        "price_source": price_source,
        "last_updated": last_updated,
        "last_updated_label": last_updated_label,
        "supports": zone_midpoints(buy_zones),
        "resistances": zone_midpoints(resistance_zones),
        "ema21": [ema_21] * len(closed_candles),
        "ema55": [ema_55] * len(closed_candles),
    }
    enforce_validation(symbol, "snapshot chart", validate_chart_data(chart_data))
    LAST_LEVELS_CHART_DATA[symbol] = chart_data


def build_chart_data(
    closed_candles,
    current_price,
    ema_21,
    ema_55,
    buy_zones,
    resistance_zones,
    price_source=None,
    last_updated=None,
    last_updated_label=None,
):
    return {
        "candles": candle_dicts(closed_candles),
        "current_price": current_price,
        "price_source": price_source,
        "last_updated": last_updated,
        "last_updated_label": last_updated_label,
        "supports": zone_midpoints(buy_zones),
        "resistances": zone_midpoints(resistance_zones),
        "ema21": [ema_21] * len(closed_candles),
        "ema55": [ema_55] * len(closed_candles),
    }


def render_research_snapshot_chart(symbol, chart_data):
    if generate_levels_chart is None:
        raise RuntimeError("Chart generator unavailable")
    if not chart_data:
        raise RuntimeError("No research chart data available")
    return generate_levels_chart(
        symbol,
        chart_data["candles"],
        chart_data["current_price"],
        chart_data["supports"],
        chart_data["resistances"],
        ema21=chart_data["ema21"],
        ema55=chart_data["ema55"],
        title=f"{symbol.replace('/', ' / ')} RESEARCH SNAPSHOT",
        output_prefix=f"{symbol.replace('/', '_')}_prb_snapshot_",
        signal_scope=chart_data_status_label(
            chart_data.get("price_source"),
            chart_data.get("last_updated_label"),
        ),
    )


SNAPSHOT_LOOK_ORDER_BUTTONS = (
    ("1 Trend", "trend"),
    ("2 Key Levels", "key_level"),
    ("3 Liquidity", "liquidity"),
    ("4 Confirmation", "confirmation"),
    ("5 Plan", "trade_plan"),
)
SNAPSHOT_LOOK_ORDER_CALLBACK_PREFIX = "look_order"
WATCHLIST_COIN_CALLBACK_PREFIX = "wcoin"
WATCHLIST_ACTION_CALLBACK_PREFIX = "wact"
WATCHLIST_ACTIONS = {
    "snapshot": "Snapshot",
    "research": "Research",
    "whynot": "Why not?",
}


def snapshot_look_order_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": label,
                    "callback_data": f"{SNAPSHOT_LOOK_ORDER_CALLBACK_PREFIX}:{concept_key}",
                }
            ]
            for label, concept_key in SNAPSHOT_LOOK_ORDER_BUTTONS
        ]
    }


def watchlist_coin_keyboard(symbols):
    return {
        "inline_keyboard": [
            [
                {
                    "text": base_symbol(symbol),
                    "callback_data": f"{WATCHLIST_COIN_CALLBACK_PREFIX}:{symbol}",
                }
            ]
            for symbol in symbols
        ]
    }


def watchlist_direct_action_keyboard(symbols, action):
    return {
        "inline_keyboard": [
            [
                {
                    "text": base_symbol(symbol),
                    "callback_data": f"{WATCHLIST_ACTION_CALLBACK_PREFIX}:{action}:{symbol}",
                }
            ]
            for symbol in symbols
        ]
    }


def watchlist_action_keyboard(symbol):
    return {
        "inline_keyboard": [
            [
                {
                    "text": label,
                    "callback_data": f"{WATCHLIST_ACTION_CALLBACK_PREFIX}:{action}:{symbol}",
                }
                for action, label in WATCHLIST_ACTIONS.items()
            ]
        ]
    }


def send_levels_chart(telegram_token, chat_id, symbol, caption, reply_markup=None):
    try:
        if generate_levels_chart is None:
            raise RuntimeError("Chart generator unavailable")

        chart_data = LAST_LEVELS_CHART_DATA.get(symbol)
        if not chart_data:
            raise RuntimeError("No chart data available")

        chart_path = generate_levels_chart(
            symbol,
            chart_data["candles"],
            chart_data["current_price"],
            chart_data["supports"],
            chart_data["resistances"],
            ema21=chart_data["ema21"],
            ema55=chart_data["ema55"],
            signal_scope=chart_data_status_label(
                chart_data.get("price_source"),
                chart_data.get("last_updated_label"),
            ),
        )
        send_telegram_photo(
            telegram_token,
            chat_id,
            chart_path,
            caption=caption,
            reply_markup=reply_markup,
        )
        return True
    except Exception:
        log_warn(f"Snapshot generation failed for {symbol.split('/')[0]}.")
        return False


POINKLE_EDUCATIONAL_FOOTER = (
    "━━━━━━━━━━━━━━━━━━\n\n"
    "⚠️ Not Financial Advice\n\n"
    "🐷 Poinkle did the research.\n\n"
    "🎓 The decision is yours.\n\n"
    "━━━━━━━━━━━━━━━━━━"
)


def poinkle_educational_footer():
    return POINKLE_EDUCATIONAL_FOOTER


def build_levels_snapshot_caption(
    symbol,
    current_price,
    current_location,
    trend_bias,
    overall_confidence,
    accumulation,
    current_rsi,
    skill_level=None,
    price_source=None,
    last_updated_label=None,
):
    display_symbol = symbol.replace("/", " / ")
    trend_text = trend_bias
    rsi_text = f"{current_rsi:.2f}"
    freshness_text = f"\n{last_updated_label}" if last_updated_label else ""
    if skill_level == "beginner":
        if trend_bias == "Bullish":
            trend_text = f"{trend_bias} (price is leaning above key moving averages)"
        elif trend_bias == "Bearish":
            trend_text = f"{trend_bias} (price is leaning below key moving averages)"
        else:
            trend_text = f"{trend_bias} (price is not clearly leaning either way yet)"

        rsi_status = get_rsi_status(current_rsi)
        rsi_text = f"{current_rsi:.2f} ({rsi_status.lower()} momentum)"

    return (
        f"📍 POINKLE SNAPSHOT — {display_symbol}\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"💰 PRICE\n"
        f"{price_display_text(current_price, price_source)}{freshness_text}\n\n"
        f"📈 TREND\n"
        f"{trend_text}\n\n"
        f"🎯 FOCUS\n"
        f"{current_location}\n\n"
        f"⭐ MARKET SCORE\n"
        f"{overall_confidence} / 100\n\n"
        f"🧠 SETUP GRADE\n"
        f"{accumulation['grade']} — {accumulation['label']}\n\n"
        f"📊 RSI\n"
        f"{rsi_text}\n\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"👀 LOOK ORDER\n\n"
        f"① Trend\n"
        f"Where is price going?\n\n"
        f"② Key Levels\n"
        f"Where are the highest-probability reaction zones?\n\n"
        f"③ Liquidity\n"
        f"Where are stops likely to be swept?\n\n"
        f"④ Confirmation\n"
        f"Did price provide confirmation?\n\n"
        f"⑤ Decision\n"
        f"What is the highest-quality plan?\n\n"
        f"{poinkle_educational_footer()}"
    )


def build_levels_command_message(exchange, symbol, skill_level=None):
    closed_candles = fetch_closed_ohlcv(exchange, symbol, TIMEFRAME, CANDLE_LIMIT)
    if len(closed_candles) < 80:
        raise RuntimeError(f"Not enough candle history for {symbol}")

    one_hour_candles = fetch_closed_ohlcv(
        exchange,
        symbol,
        "1h",
        300,
        fallback=closed_candles[-100:],
    )
    four_hour_candles = resample_candles(one_hour_candles, 4)
    daily_candles = fetch_closed_ohlcv(
        exchange,
        symbol,
        "1d",
        180,
        fallback=closed_candles[-100:],
    )
    weekly_candles = resample_candles(daily_candles, 7)
    latest_closed = closed_candles[-1]
    price_info = get_current_market_price_info(exchange, symbol, latest_closed[4])
    current_price = price_info["price"]
    price_source = price_info["price_source"]
    last_updated = iso_utc_now()
    last_updated_label = data_as_of_label()
    daily_closes = [candle[4] for candle in daily_candles]
    if len(daily_closes) >= 55:
        analysis_candles = daily_candles
        analysis_closes = daily_closes
        ema_timeframe = "Daily"
    else:
        analysis_candles = closed_candles
        analysis_closes = [candle[4] for candle in closed_candles]
        ema_timeframe = "Daily fallback"

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
    accumulation = score_patience_setup(
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
    _range_location, range_fraction = get_range_location(current_price, range_low, range_high)
    enforce_validation(
        symbol,
        "snapshot",
        validate_market_snapshot_data(
            {
                "current_price": current_price,
                "rsi": current_rsi,
                "ema_21": ema_21,
                "ema_55": ema_55,
                "volume_average": volume_average,
                "volume_multiple": volume_multiple,
                "range_low": range_low,
                "range_high": range_high,
                "range_position": range_fraction,
                "market_score": overall_confidence,
                "last_updated": last_updated,
                "accumulation": accumulation,
                "support_zones": buy_zones,
                "resistance_zones": resistance_zones,
            }
        ),
    )
    store_levels_chart_data(
        symbol,
        closed_candles,
        current_price,
        ema_21,
        ema_55,
        buy_zones,
        resistance_zones,
        price_source=price_source,
        last_updated=last_updated,
        last_updated_label=last_updated_label,
    )

    return build_levels_snapshot_caption(
        symbol,
        current_price,
        current_location,
        trend_bias,
        overall_confidence,
        accumulation,
        current_rsi,
        skill_level=skill_level,
        price_source=price_source,
        last_updated_label=last_updated_label,
    )


def build_levels_scan_snapshot(exchange, symbol):
    closed_candles = fetch_closed_ohlcv(exchange, symbol, TIMEFRAME, CANDLE_LIMIT)
    if len(closed_candles) < 80:
        raise RuntimeError(f"Not enough candle history for {symbol}")

    one_hour_candles = fetch_closed_ohlcv(
        exchange,
        symbol,
        "1h",
        300,
        fallback=closed_candles[-100:],
    )
    four_hour_candles = resample_candles(one_hour_candles, 4)
    daily_candles = fetch_closed_ohlcv(
        exchange,
        symbol,
        "1d",
        180,
        fallback=closed_candles[-100:],
    )
    weekly_candles = resample_candles(daily_candles, 7)
    latest_closed = closed_candles[-1]
    price_info = get_current_market_price_info(exchange, symbol, latest_closed[4])
    current_price = price_info["price"]
    price_source = price_info["price_source"]
    last_updated = iso_utc_now()
    last_updated_label = data_as_of_label()
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
    accumulation = score_patience_setup(
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
    _range_location, range_fraction = get_range_location(current_price, range_low, range_high)
    validation_data = {
        "current_price": current_price,
        "rsi": current_rsi,
        "ema_21": ema_21,
        "ema_55": ema_55,
        "volume_average": volume_average,
        "volume_multiple": volume_multiple,
        "range_low": range_low,
        "range_high": range_high,
        "range_position": range_fraction,
        "market_score": market_score,
        "last_updated": last_updated,
        "accumulation": accumulation,
        "support_zones": buy_zones,
        "resistance_zones": resistance_zones,
    }
    enforce_validation(symbol, "research snapshot", validate_market_snapshot_data(validation_data))

    return {
        "symbol": symbol,
        "current_price": current_price,
        "price_source": price_source,
        "last_updated": last_updated,
        "last_updated_label": last_updated_label,
        "ema_21": ema_21,
        "ema_55": ema_55,
        "rsi": current_rsi,
        "support_zones": buy_zones,
        "resistance_zones": resistance_zones,
        "market_score": market_score,
        "bias": trend_bias,
        "patience_grade": accumulation["grade"],
        "patience_label": accumulation["label"],
        "strategy": strategy,
        "location": current_location,
        "support_distance_label": support_distance_label,
        "distance_to_support": distance_to_support,
        "distance_to_resistance": distance_to_resistance,
        "market_structure": market_structure,
        "market_structure_label": market_structure_label,
        "chart_data": build_chart_data(
            closed_candles,
            current_price,
            ema_21,
            ema_55,
            buy_zones,
            resistance_zones,
            price_source=price_source,
            last_updated=last_updated,
            last_updated_label=last_updated_label,
        ),
    }


def prb_number(symbol, watchlist=None):
    watchlist = watchlist or WATCHLIST
    try:
        return f"PRB-{watchlist.index(symbol) + 1:04d}"
    except ValueError:
        return "PRB-0000"


def prb_created_date(now=None):
    now = now or datetime.now(EASTERN_TIME)
    return f"{now.strftime('%B')} {now.day}, {now.year}"


def research_confidence_text(snapshot):
    score = snapshot.get("market_score")
    if score is None:
        return "Pending Evidence"
    return f"{score / 10:.1f} / 10 (Market Snapshot)"


POINKLE_RESEARCH_EMBLEM_PATH = PROJECT_DIR / "assets" / "poinkle_prb_logo.png"
INNER_CIRCLE_LOGO_PATH = PROJECT_DIR / "assets" / "inner_circle_logo.png"


def mike_logo_path():
    if INNER_CIRCLE_LOGO_PATH.exists():
        return INNER_CIRCLE_LOGO_PATH
    return POINKLE_RESEARCH_EMBLEM_PATH


REFERENCE_RESEARCH_BRIEFS = {
    "AAVE/USD": {
        "title": "AAVE Long-Term Investment Thesis",
        "status": "Active Research",
        "overall_rating": "7.4 / 10",
        "long_term_thesis": (
            "Constructive, but not because of one headline. The strongest long-term thesis is the combination of "
            "macro liquidity, Bitcoin market cycles, DeFi adoption, institutional access, and regulatory clarity."
        ),
        "short_term_thesis": (
            "AAVE still needs confirmation from price structure and broader market rotation. Kraken-related interest "
            "is worth tracking, but it should be treated as one catalyst inside a larger DeFi cycle."
        ),
        "what_we_know": [
            "Kraken/Fed-related news created a credible catalyst to study, but Kraken alone is not enough.",
            "AAVE outperformed during a window that also included Bitcoin strength, ETF inflows, ETH strength, and capital rotation into DeFi.",
            "The thesis gets stronger when BTC cycles, ETH strength, DeFi TVL, stablecoin liquidity, and AAVE-specific adoption line up together.",
            "The April 17 lower high remains a key validation point because it helps separate headline momentum from durable trend strength.",
        ],
        "historical_pattern": [
            "Track BTC -> ETH -> AAVE -> BTC Dominance -> TOTAL3 -> DeFi TVL to understand where liquidity originated and how it rotated.",
            "Compare AAVE against prior infrastructure catalysts: Coinbase IPO, BlackRock ETF filing, Ethereum Merge, spot ETF approvals, and earlier DeFi cycles.",
            "The key pattern question is whether AAVE responds best to Bitcoin rallies, falling BTC dominance, rising TVL, ETF inflows, or direct protocol catalysts.",
        ],
        "bull_case": [
            "Kraken becomes meaningful infrastructure rather than a one-off headline.",
            "Institutional DeFi usage grows and pushes attention toward established lending protocols.",
            "DeFi TVL expands while Bitcoin remains constructive and liquidity conditions improve.",
            "Regulatory clarity improves enough for larger capital pools to take DeFi seriously.",
        ],
        "bear_case": [
            "Kraken integration proves limited or fails to drive measurable usage.",
            "Bitcoin weakens before capital can rotate into ETH, DeFi, and AAVE.",
            "DeFi TVL stalls, protocol revenue weakens, or competitors capture the narrative.",
            "Regulation becomes restrictive and reduces institutional appetite for DeFi exposure.",
        ],
        "unknowns": [
            "Depth and durability of Kraken integration.",
            "Whether institutional DeFi demand becomes real usage or stays narrative-driven.",
            "Future protocol revenue growth, wallet growth, whale behavior, exchange flows, and governance direction.",
            "Regulatory path for lending protocols and DeFi infrastructure.",
        ],
        "strengthen": [
            "AAVE reclaims key market structure while BTC and ETH remain supportive.",
            "DeFi TVL and stablecoin liquidity rise together.",
            "Protocol revenue, wallet growth, and governance activity improve.",
            "Kraken/AAVE developments show measurable adoption, not just announcement value.",
        ],
        "weaken": [
            "AAVE breaks support while BTC, ETH, or TOTAL3 also weaken.",
            "BTC dominance rises in a way that prevents alt and DeFi rotation.",
            "DeFi TVL contracts or protocol usage fails to confirm the narrative.",
            "Regulatory pressure or competitor strength damages the long-term adoption case.",
        ],
        "scorecard": {
            "Fundamentals": "8.5/10",
            "Technical Structure": "7.0/10",
            "Historical Pattern": "8.0/10",
            "Macro Environment": "7.5/10",
            "Institutional Adoption": "8.0/10",
            "Risk": "5.5/10",
        },
        "conclusion": (
            "The long-term AAVE thesis is strongest when treated as a liquidity-cycle and DeFi-adoption thesis, not a single-headline trade. "
            "Kraken may matter, but the durable case depends on Bitcoin cycles, ETH strength, DeFi TVL, stablecoin liquidity, regulatory clarity, and measurable protocol usage."
        ),
    }
}


def prb_separator():
    return "━━━━━━━━━━━━━━━━━━"


def prb_brand_header():
    return f"🐷 POINKLE RESEARCH BRIEF\n{prb_separator()}"


def collect_market_data(exchange, symbol):
    market_data = build_levels_scan_snapshot(exchange, symbol)
    if market_data.get("chart_data"):
        LAST_RESEARCH_CHART_DATA[symbol] = market_data["chart_data"]
    return market_data


def collect_future_news(symbol):
    # Future live research source: connect news/catalyst collection here.
    return {
        "timeline": "Pending Evidence",
        "historical_comparison": "Pending Evidence",
    }


def coingecko_api_key():
    return str(os.getenv("COINGECKO_API_KEY") or "").strip()


def coingecko_coin_id_for_symbol(symbol):
    base = str(symbol or "").strip().upper().split("/", 1)[0]
    return COINGECKO_COIN_IDS.get(base)


def coingecko_metadata_cache_key(coin_id):
    return f"coin:{coin_id}"


def first_non_empty_url(values):
    for value in values or []:
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""


def first_non_empty_urls(values, limit=3):
    urls = []
    for value in values or []:
        clean = str(value or "").strip()
        if clean and clean not in urls:
            urls.append(clean)
        if len(urls) >= limit:
            break
    return urls


def coingecko_whitepaper_url(links):
    whitepaper = (links or {}).get("whitepaper")
    if isinstance(whitepaper, dict):
        return first_non_empty_url([whitepaper.get("link"), whitepaper.get("url")])
    if isinstance(whitepaper, list):
        return first_non_empty_url(whitepaper)
    return first_non_empty_url([whitepaper])


def cached_coingecko_coin_metadata(coin_id):
    cache_key = coingecko_metadata_cache_key(coin_id)
    cached = COINGECKO_COIN_METADATA_CACHE.get(cache_key)
    if not cached:
        return None
    fetched_at, data = cached
    if time.time() - fetched_at > COINGECKO_COIN_METADATA_TTL_SECONDS:
        COINGECKO_COIN_METADATA_CACHE.pop(cache_key, None)
        return None
    return data


def store_coingecko_coin_metadata(coin_id, data):
    COINGECKO_COIN_METADATA_CACHE[coingecko_metadata_cache_key(coin_id)] = (time.time(), data)


def clean_coingecko_description(description, max_length=280):
    text = html.unescape(str(description or ""))
    clean = []
    in_tag = False
    for character in text:
        if character == "<":
            in_tag = True
            continue
        if character == ">":
            in_tag = False
            continue
        if not in_tag:
            clean.append(character)
    text = " ".join("".join(clean).split())
    if len(text) <= max_length:
        return text
    clipped = text[:max_length].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{clipped}..."


def numeric_market_value(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_compact_number(value):
    value = numeric_market_value(value)
    if value is None:
        return "Pending Evidence"
    abs_value = abs(value)
    for suffix, divisor in (("T", 1_000_000_000_000), ("B", 1_000_000_000), ("M", 1_000_000)):
        if abs_value >= divisor:
            return f"{value / divisor:.2f}{suffix}"
    if abs_value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def format_market_cap_value(value):
    formatted = format_compact_number(value)
    if formatted == "Pending Evidence":
        return formatted
    return f"${formatted}"


def format_whole_percent(value):
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return ""


def fdv_market_cap_read(market_cap, fully_diluted_valuation):
    market_cap = numeric_market_value(market_cap)
    fully_diluted_valuation = numeric_market_value(fully_diluted_valuation)
    if not market_cap or not fully_diluted_valuation:
        return ""

    ratio = fully_diluted_valuation / market_cap
    if abs(ratio - 1) <= 0.05:
        return (
            "FDV is roughly equal to market cap - nearly all tokens are already "
            "in circulation, so there is little future dilution from unlocks."
        )
    if ratio > 1.2:
        return (
            f"FDV is {ratio:.1f}x market cap - a large share of tokens are not "
            "yet circulating. Future unlocks would increase supply."
        )
    return ""


def circulating_supply_read(circulating_supply, max_supply):
    circulating_supply = numeric_market_value(circulating_supply)
    max_supply = numeric_market_value(max_supply)
    if max_supply is None:
        return "No fixed max supply - this token has no hard cap."
    if not circulating_supply or max_supply <= 0:
        return ""

    circulating_percent = (circulating_supply / max_supply) * 100
    if circulating_percent >= 95:
        return "Circulating supply is at/near max - fully distributed."
    return f"{format_whole_percent(circulating_percent)} of max supply is circulating."


def coingecko_fundamentals_teaching_line(fundamentals_data):
    reads = [
        fdv_market_cap_read(
            fundamentals_data.get("market_cap"),
            fundamentals_data.get("fully_diluted_valuation"),
        ),
        circulating_supply_read(
            fundamentals_data.get("circulating_supply"),
            fundamentals_data.get("max_supply"),
        ),
    ]
    return " ".join(read for read in reads if read)


def extract_coingecko_coin_metadata(payload):
    market_data = payload.get("market_data") or {}
    description = payload.get("description") or {}
    links = payload.get("links") or {}
    image = payload.get("image") or {}
    return {
        "fundamentals": "CoinGecko metadata connected",
        "source": "CoinGecko",
        "coin_id": payload.get("id"),
        "name": payload.get("name"),
        "symbol": str(payload.get("symbol") or "").upper(),
        "image_url": image.get("small") or image.get("thumb") or image.get("large"),
        "homepage_url": first_non_empty_url(links.get("homepage")),
        "whitepaper_url": coingecko_whitepaper_url(links),
        "explorer_urls": first_non_empty_urls(links.get("blockchain_site"), limit=3),
        "circulating_supply": market_data.get("circulating_supply"),
        "total_supply": market_data.get("total_supply"),
        "max_supply": market_data.get("max_supply"),
        "market_cap": (market_data.get("market_cap") or {}).get("usd"),
        "fully_diluted_valuation": (
            market_data.get("fully_diluted_valuation") or {}
        ).get("usd"),
        "description": clean_coingecko_description(description.get("en")),
    }


def fetch_coingecko_coin_metadata(symbol):
    coin_id = coingecko_coin_id_for_symbol(symbol)
    if not coin_id:
        return None

    cached = cached_coingecko_coin_metadata(coin_id)
    if cached is not None:
        return cached

    api_key = coingecko_api_key()
    if not api_key:
        throttled_log_warn(
            symbol,
            "coingecko:missing-key",
            f"{symbol}: CoinGecko metadata unavailable; missing COINGECKO_API_KEY.",
        )
        return None

    if requests is None:
        throttled_log_warn(
            symbol,
            "coingecko:requests-unavailable",
            f"{symbol}: CoinGecko metadata unavailable; requests is not installed.",
        )
        return None

    try:
        response = telegram_http_session().get(
            f"{COINGECKO_DEMO_API_BASE_URL}/coins/{coin_id}",
            headers={"x-cg-demo-api-key": api_key},
            params={
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = extract_coingecko_coin_metadata(response.json())
        store_coingecko_coin_metadata(coin_id, data)
        return data
    except Exception as error:
        throttled_log_warn(
            symbol,
            "coingecko:metadata",
            f"{symbol}: CoinGecko metadata unavailable. Research will use pending fundamentals. {error}",
        )
        return None


def pending_fundamentals():
    return {
        "fundamentals": "Pending Evidence",
        "on_chain": "Pending Evidence",
        "macro": "Pending Evidence",
        "institutional_adoption": "Pending Evidence",
        "historical_pattern": "Pending Evidence",
    }


def collect_future_fundamentals(symbol):
    fundamentals = pending_fundamentals()
    coingecko_metadata = fetch_coingecko_coin_metadata(symbol)
    if coingecko_metadata:
        fundamentals.update(coingecko_metadata)
    return fundamentals


def collect_reference_research(symbol):
    return REFERENCE_RESEARCH_BRIEFS.get(symbol)


def build_research_brief(exchange, symbol):
    market_data = collect_market_data(exchange, symbol)
    reference_research = collect_reference_research(symbol)
    news_data = collect_future_news(symbol)
    fundamentals_data = collect_future_fundamentals(symbol)
    return render_prb(market_data, news_data, fundamentals_data, reference_research=reference_research)


def render_prb(snapshot, news_data=None, fundamentals_data=None, updated=None, reference_research=None):
    news_data = news_data or {}
    fundamentals_data = fundamentals_data or {}
    reference_research = reference_research or {}
    symbol = snapshot["symbol"]
    ticker = symbol.split("/")[0]
    current_price = snapshot.get("current_price", 0)
    price_source = snapshot.get("price_source")
    last_updated_label = snapshot.get("last_updated_label")
    support_zones = snapshot.get("support_zones", [])
    resistance_zones = snapshot.get("resistance_zones", [])
    patience_grade = snapshot.get("patience_grade", "N/A")
    patience_label = snapshot.get("patience_label", "Pending Evidence")
    bias = snapshot.get("bias", "Pending Evidence")
    location = snapshot.get("location", "Pending Evidence")
    market_structure_label = snapshot.get("market_structure_label", "Pending Evidence")
    rsi_value = snapshot.get("rsi", 0)
    strategy = snapshot.get("strategy", "watch")
    support_text = format_zone(support_zones[0]) if support_zones else "Pending Evidence"
    resistance_text = format_zone(resistance_zones[0]) if resistance_zones else "Pending Evidence"
    market_cap_text = format_market_cap_value(fundamentals_data.get("market_cap"))
    fdv_text = format_market_cap_value(fundamentals_data.get("fully_diluted_valuation"))
    circulating_supply_text = format_compact_number(fundamentals_data.get("circulating_supply"))
    total_supply_text = format_compact_number(fundamentals_data.get("total_supply"))
    max_supply_text = format_compact_number(fundamentals_data.get("max_supply"))
    description_text = fundamentals_data.get("description") or "Pending Evidence"
    fundamentals_connected = fundamentals_data.get("source") == "CoinGecko"
    fundamentals_line = (
        f"Market cap {market_cap_text}; FDV {fdv_text}; "
        f"circulating supply {circulating_supply_text}"
        if fundamentals_connected
        else "Full Research Pending"
    )
    supply_line = (
        f"Circulating {circulating_supply_text}; total {total_supply_text}; max {max_supply_text}"
        if fundamentals_connected
        else "Pending Evidence"
    )
    fundamentals_teaching_line = (
        coingecko_fundamentals_teaching_line(fundamentals_data)
        if fundamentals_connected
        else ""
    )
    fundamentals_detail_lines = (
        f"• Fundamentals: {fundamentals_line}\n"
        f"• Supply: {supply_line}\n"
        f"{f'• What this means: {fundamentals_teaching_line}\n' if fundamentals_teaching_line else ''}"
        f"• Description: {description_text}\n"
        f"• Data provided by CoinGecko\n"
        if fundamentals_connected
        else ""
    )
    updated = updated or prb_created_date()
    separator = prb_separator()
    data_freshness_line = f"• Data: {last_updated_label}\n" if last_updated_label else ""

    if reference_research:
        return render_reference_prb(snapshot, reference_research, separator)

    title = f"{ticker} Market-Structure Research Brief"
    status = "Market-Structure Brief — Full Research Pending"
    overall_rating = research_confidence_text(snapshot)
    long_term_thesis = "Full long-term thesis pending. Current evidence is limited to Poinkle market structure, trend, RSI, support, and resistance context."
    short_term_thesis = f"Price is currently showing {bias.lower()} bias, {location.lower()}, and {market_structure_label.lower()} conditions."

    return (
        f"{prb_brand_header()}\n\n"
        f"PRB: {prb_number(symbol)}\n"
        f"Title: {title}\n"
        f"Status: {status}\n"
        f"Overall Rating: {overall_rating}\n"
        f"Long-Term Thesis: {long_term_thesis}\n"
        f"Short-Term Thesis: {short_term_thesis}\n"
        f"\n{separator}\n\n"
        f"✅ WHAT WE KNOW\n\n"
        f"• This is not a full fundamental research brief yet.\n"
        f"• Current Price: {price_display_text(current_price, price_source)}\n"
        f"{data_freshness_line}"
        f"• Trend: {bias}\n"
        f"• RSI: {current_rsi_text(rsi_value)}\n"
        f"• Market Structure: {market_structure_label}\n"
        f"• Nearest Support: {support_text}\n"
        f"• Nearest Resistance: {resistance_text}\n"
        f"{fundamentals_detail_lines}"
        f"• Best Use Case: {strategy_text_for_research(strategy)}\n\n"
        f"📈 HISTORICAL PATTERN\n\n"
        f"Full historical research pending. Use this brief as a market-structure read until saved or live research is connected.\n\n"
        f"{separator}\n\n"
        f"🐂 BULL CASE\n\n"
        f"{ticker} improves if trend strengthens, accumulation holds, resistance is reclaimed, liquidity expands, and fundamental evidence confirms the thesis.\n\n"
        f"🐻 BEAR CASE\n\n"
        f"{ticker} weakens if support fails, market structure deteriorates, liquidity contracts, or fundamental evidence contradicts the thesis.\n\n"
        f"❓ BIGGEST UNKNOWNS\n\n"
        f"Protocol fundamentals, adoption, token supply dynamics, sector leadership, regulation, macro liquidity, and future catalyst quality.\n\n"
        f"{separator}\n\n"
        f"🔍 WHAT WOULD STRENGTHEN THIS THESIS?\n\n"
        f"• Reclaim resistance with improving trend and volume.\n"
        f"• Hold support during broader market weakness.\n"
        f"• Add saved research evidence or future live fundamentals confirming adoption.\n\n"
        f"⚠️ WHAT WOULD WEAKEN THIS THESIS?\n\n"
        f"• Lose nearby support.\n"
        f"• RSI and trend continue weakening.\n"
        f"• Future research finds weak fundamentals or poor catalyst quality.\n\n"
        f"{separator}\n\n"
        f"📊 POINKLE SCORECARD\n\n"
        f"Fundamentals: {fundamentals_line}\n"
        f"Technical Structure: {snapshot.get('market_score', 0) / 10:.1f}/10\n"
        f"Historical Pattern: Full Research Pending\n"
        f"Macro Environment: Full Research Pending\n"
        f"Institutional Adoption: Full Research Pending\n"
        f"SETUP GRADE: {patience_grade} — {patience_label}\n\n"
        f"{separator}\n\n"
        f"📌 RESEARCH CONCLUSION\n\n"
        f"This is a market-structure brief, not a complete investment thesis. "
        f"The next upgrade should connect saved research, news, fundamentals, on-chain data, and macro context before making a stronger long-term call.\n\n"
        f"{research_footer(separator)}"
    )


def render_reference_prb(snapshot, research, separator):
    symbol = snapshot["symbol"]
    return (
        f"{prb_brand_header()}\n\n"
        f"PRB: {prb_number(symbol)}\n"
        f"Title: {research['title']}\n"
        f"Status: {research['status']}\n"
        f"Overall Rating: {research['overall_rating']}\n"
        f"Long-Term Thesis: {research['long_term_thesis']}\n"
        f"Short-Term Thesis: {research['short_term_thesis']}\n"
        f"\n{separator}\n\n"
        f"✅ WHAT WE KNOW\n\n"
        f"{format_research_bullets(research['what_we_know'])}\n\n"
        f"{separator}\n\n"
        f"📈 HISTORICAL PATTERN\n\n"
        f"{format_research_bullets(research['historical_pattern'])}\n\n"
        f"🐂 BULL CASE\n\n"
        f"{format_research_bullets(research['bull_case'])}\n\n"
        f"🐻 BEAR CASE\n\n"
        f"{format_research_bullets(research['bear_case'])}\n\n"
        f"❓ BIGGEST UNKNOWNS\n\n"
        f"{format_research_bullets(research['unknowns'])}\n\n"
        f"{separator}\n\n"
        f"🔍 WHAT WOULD STRENGTHEN THIS THESIS?\n\n"
        f"{format_research_bullets(research['strengthen'])}\n\n"
        f"⚠️ WHAT WOULD WEAKEN THIS THESIS?\n\n"
        f"{format_research_bullets(research['weaken'])}\n\n"
        f"{separator}\n\n"
        f"📊 POINKLE SCORECARD\n\n"
        f"{format_scorecard(research['scorecard'])}\n\n"
        f"{separator}\n\n"
        f"📌 RESEARCH CONCLUSION\n\n"
        f"{research['conclusion']}\n\n"
        f"{research_footer(separator)}"
    )


def format_research_bullets(items):
    return "\n".join(f"• {item}" for item in items)


def format_scorecard(scorecard):
    return "\n".join(f"{label}: {score}" for label, score in scorecard.items())


def research_footer(separator):
    return poinkle_educational_footer()


def current_rsi_text(current_rsi):
    return f"{current_rsi:.2f}" if isinstance(current_rsi, (int, float)) else "Pending Evidence"


def strategy_text_for_research(strategy):
    if isinstance(strategy, (list, tuple)):
        return ", ".join(strategy_text_for_research(item) for item in strategy)

    labels = {
        "dca": "DCA",
        "hold": "Long-Term Hold",
        "breakout": "Breakout Trade",
        "trim": "Trim Position",
        "wait": "Wait For Pullback",
        "watch": "Watch Only",
    }
    return labels.get(strategy, str(strategy).replace("_", " ").title())


def build_research_command_message(exchange, symbol):
    return build_research_brief(exchange, symbol)


def research_branding_image_exists():
    return POINKLE_RESEARCH_EMBLEM_PATH.exists()


def send_research_branding_image(telegram_token, chat_id):
    if not research_branding_image_exists():
        return False
    return send_telegram_photo(telegram_token, chat_id, POINKLE_RESEARCH_EMBLEM_PATH)


def send_research_cards(telegram_token, chat_id, prb_text, symbol=None, chart_data=None):
    try:
        if render_prb_cards is None:
            raise RuntimeError("PRB card renderer unavailable")

        chart_path = None
        if symbol and chart_data:
            try:
                chart_path = render_research_snapshot_chart(symbol, chart_data)
            except Exception as error:
                log_warn(f"PRB chart rendering failed for {symbol}: {error}")

        card_paths = render_prb_cards(
            prb_text,
            logo_path=POINKLE_RESEARCH_EMBLEM_PATH,
            chart_path=chart_path,
        )
        if not card_paths:
            raise RuntimeError("No PRB cards rendered")

        if send_telegram_media_group(telegram_token, chat_id, card_paths):
            return True

        log_warn("PRB media group send failed; falling back to individual cards.")
        for card_path in card_paths:
            if not send_telegram_photo(telegram_token, chat_id, card_path):
                raise RuntimeError("PRB card send failed")
        return True
    except Exception as error:
        log_warn(f"PRB card rendering failed: {error}")
        return False


SNAPSHOT_COMMANDS = ("/snapshot", "/snap", "/levels")
RESEARCH_COMMANDS = ("/research",)
WHYNOT_COMMANDS = ("/whynot", "/why")
REFERENCE_COMMANDS = ("/guide", "/reference")
EXPLAIN_COMMANDS = ("/explain", "/learn")


def snapshot_command_name(message_text):
    return message_text.strip().split()[0].lower().split("@", 1)[0] if message_text.strip() else ""


def is_snapshot_command(message_text):
    return snapshot_command_name(message_text) in SNAPSHOT_COMMANDS


def is_research_command(message_text):
    return snapshot_command_name(message_text) in RESEARCH_COMMANDS


def is_whynot_command(message_text):
    return snapshot_command_name(message_text) in WHYNOT_COMMANDS


def is_reference_command(message_text):
    return snapshot_command_name(message_text) in REFERENCE_COMMANDS


def is_explain_command(message_text):
    return snapshot_command_name(message_text) in EXPLAIN_COMMANDS


def format_supported_coins_for_help(symbols, per_line=8):
    coins = [symbol.replace("/USD", "") for symbol in symbols]
    lines = [
        ", ".join(coins[index : index + per_line])
        for index in range(0, len(coins), per_line)
    ]
    return "\n".join(lines)


def command_example_asset(index=0):
    if not WATCHLIST:
        return "SYMBOL"
    symbol = WATCHLIST[min(index, len(WATCHLIST) - 1)]
    return symbol.split("/")[0]


def poinkle_onboarding_text(kind):
    supported_coins = format_supported_coins_for_help(WATCHLIST)
    primary_example = command_example_asset(0)
    secondary_example = command_example_asset(1)
    research_example = command_example_asset(2)
    intro = (
        "Welcome to Poinkle Alpha.\n\n"
        "Poinkle helps teach you what to look at next.\n\n"
        "Start with:\n\n"
        f"📸 /snapshot {primary_example}\n"
        f"⚡ /snap {secondary_example}\n"
        f"📚 /research {research_example}\n"
        f"📈 /levels {primary_example} (legacy)\n"
        "❓ /help\n\n"
        "Layer 1 teaches:\n\n"
        "• Trend\n"
        "• Key Levels\n"
        "• Liquidity\n"
        "• Confirmation\n"
        "• Decision\n\n"
    )
    if kind == "help":
        return (
            "🐷 POINKLE HELP\n\n"
            "I help you learn what to look at in the market — patiently.\n\n"
            "TRY THESE:\n"
            f"📸 /snapshot {primary_example} — visual chart + breakdown\n"
            f"📚 /research {research_example} — deeper dive on a coin\n"
            "📖 /explain RSI — what any term means, in plain English\n"
            "   /learn works too.\n\n"
            "MORE:\n"
            "/alerts — set a personal price alert\n"
            "/myalerts — view your alerts\n"
            "/mike — Mike's curated watchlist\n"
            "/coins — every coin I track\n"
            "/guide — full command reference\n\n"
            "Not sure what a word means? Just type /explain and the word.\n\n"
            "Educational only. Not financial advice. 🐷"
        )

    return (
        "POINKLE START\n\n"
        f"{intro}"
        "🪙 Supported Coins\n\n"
        f"{supported_coins}\n\n"
        "Educational market structure only.\n"
        "Not financial advice."
    )


def build_welcome_message():
    return (
        "🐷 <b>Welcome to Poinkle.</b>\n\n"
        "I'm the Poinkle bot — think of me as your first classroom in the market.\n\n"
        "Here's what I do: I watch the charts patiently and send you clean, simple snapshots "
        "when something real is happening — not noise, not hype, just signal. Every card is "
        "built to teach, not just alert. The more you see them, the more the market starts "
        "to make sense.\n\n"
        "A few things to know:\n"
        "- This is always free. What you see here is an introduction to what Poinkle is building.\n"
        "- I focus on patience. Good setups develop over time — \"patience compounds\" isn't a slogan, it's the whole idea.\n"
        "- I'm always growing. New features, deeper tools, and more ways to learn are coming.\n\n"
        "Poinkle's mission is simple: connect humanity through knowledge. This is where it starts.\n\n"
        "Glad you're here. Let's learn together. 🐷"
    )


def send_start_welcome(telegram_token, destination_chat_id, welcome_message):
    if not WELCOME_BANNER_PATH.exists():
        log_warn(f"Welcome banner image missing: {WELCOME_BANNER_PATH}")
        send_telegram_message(telegram_token, destination_chat_id, welcome_message)
        return

    if len(welcome_message) <= TELEGRAM_PHOTO_CAPTION_LIMIT:
        if send_telegram_photo(
            telegram_token,
            destination_chat_id,
            str(WELCOME_BANNER_PATH),
            caption=welcome_message,
        ):
            return
        send_telegram_message(telegram_token, destination_chat_id, welcome_message)
        return

    if not send_telegram_photo(telegram_token, destination_chat_id, str(WELCOME_BANNER_PATH)):
        log_warn(f"Welcome banner send failed: {WELCOME_BANNER_PATH}")
    send_telegram_message(telegram_token, destination_chat_id, welcome_message)


def upsert_start_user_profile(user_id, from_user=None):
    user_id = str(user_id or "").strip()
    if not user_id:
        return {}

    from_user = from_user or {}
    profiles = load_user_profiles()
    profile = profiles.setdefault(user_id, {})
    now = iso_utc_now()

    profile.setdefault("first_seen", now)
    profile["last_start"] = now
    profile["onboarded"] = True
    profile["telegram_user_id"] = user_id

    username = from_user.get("username")
    if username:
        profile["username"] = username
    first_name = from_user.get("first_name")
    if first_name:
        profile["first_name"] = first_name
    last_name = from_user.get("last_name")
    if last_name:
        profile["last_name"] = last_name

    save_user_profiles(profiles)
    return profile


def handle_start_command(telegram_token, telegram_chat_id, from_user=None):
    destination_chat_id = telegram_user_id(
        {"id": telegram_chat_id, "type": "private"},
        from_user,
        telegram_chat_id,
    )
    try:
        upsert_start_user_profile(destination_chat_id, from_user=from_user)
    except Exception as error:
        log_warn(f"Could not update /start profile for {telegram_chat_id}: {error}")

    welcome_message = build_welcome_message()
    send_start_welcome(telegram_token, destination_chat_id, welcome_message)
    try:
        maybe_send_skill_onboarding(
            telegram_token,
            {"id": destination_chat_id, "type": "private"},
            {"id": destination_chat_id, **(from_user or {})},
            allow_private=True,
        )
    except Exception as error:
        log_warn(f"Could not send /start skill onboarding for {destination_chat_id}: {error}")


def handle_help_command(telegram_token, telegram_chat_id):
    send_telegram_message(telegram_token, telegram_chat_id, poinkle_onboarding_text("help"))


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


def format_mike_trend(trend):
    trend = str(trend or "").strip().lower()
    if trend in {"bullish", "bearish", "neutral"}:
        return trend
    return "neutral"


def mike_list_symbols():
    return list(MIKES_LIST)


def create_mike_alternate_exchange():
    if ccxt is None:
        raise RuntimeError("Missing ccxt for Mike alternate exchange data")

    exchange_class = getattr(ccxt, MIKE_ALTERNATE_EXCHANGE_ID, None)
    if exchange_class is None:
        raise RuntimeError(f"ccxt exchange unavailable: {MIKE_ALTERNATE_EXCHANGE_ID}")

    return exchange_class({"enableRateLimit": True})


def mike_alternate_exchange():
    global MIKE_ALTERNATE_EXCHANGE
    if MIKE_ALTERNATE_EXCHANGE is None:
        MIKE_ALTERNATE_EXCHANGE = create_mike_alternate_exchange()
    return MIKE_ALTERNATE_EXCHANGE


def fetch_swing_ohlcv(exchange, symbol, timeframe, limit):
    normalized_symbol = normalize_trade_symbol_input(symbol)
    if not normalized_symbol:
        raise ValueError("Missing symbol for swing OHLCV fetch")

    if limit > 300:
        log_warn(f"{normalized_symbol}: requested {limit} candles; clamping swing OHLCV limit to 300.")
        limit = 300

    if resolve_data_source(normalized_symbol) == "kraken":
        fetch_exchange = kraken_exchange()
        if fetch_exchange is None:
            raise RuntimeError("Kraken exchange unavailable")
        fetch_symbol = kraken_ohlcv_symbol(normalized_symbol)
        exchange_label = KRAKEN_EXCHANGE_ID
    elif normalized_symbol in MIKE_ALTERNATE_SYMBOLS:
        fetch_exchange = mike_alternate_exchange()
        fetch_symbol = MIKE_ALTERNATE_SYMBOLS[normalized_symbol]
        exchange_label = MIKE_ALTERNATE_EXCHANGE_ID
    else:
        fetch_exchange = exchange
        fetch_symbol = normalized_symbol
        exchange_label = "coinbase"

    timeframes = getattr(fetch_exchange, "timeframes", {}) or {}
    if timeframe not in timeframes:
        raise ValueError(f"{exchange_label} does not support timeframe {timeframe}")

    return fetch_exchange.fetch_ohlcv(fetch_symbol, timeframe=timeframe, limit=limit)


def resolve_data_source(symbol):
    normalized_symbol = str(symbol or "").strip().upper()
    if normalized_symbol in KRAKEN_FALLBACK_SYMBOLS:
        return "kraken"
    return "coinbase"


def kraken_exchange():
    global KRAKEN_EXCHANGE
    if KRAKEN_EXCHANGE is not None:
        return KRAKEN_EXCHANGE

    if ccxt is None:
        log_warn("Missing ccxt for Kraken fallback exchange data")
        return None

    exchange_class = getattr(ccxt, KRAKEN_EXCHANGE_ID, None)
    if exchange_class is None:
        log_warn(f"ccxt exchange unavailable: {KRAKEN_EXCHANGE_ID}")
        return None

    try:
        KRAKEN_EXCHANGE = exchange_class({"enableRateLimit": True})
    except Exception as error:
        log_warn(f"Could not create Kraken fallback exchange: {error}")
        return None
    return KRAKEN_EXCHANGE


def kraken_ohlcv_symbol(symbol):
    base = str(symbol or "").strip().upper().split("/", 1)[0]
    if not base:
        return ""
    return f"{base}/USD"


def fetch_kraken_ohlcv(symbol, timeframe="1h", limit=100):
    exchange = kraken_exchange()
    if exchange is None:
        return None

    kraken_symbol = kraken_ohlcv_symbol(symbol)
    if not kraken_symbol:
        log_warn("Could not fetch Kraken candles: missing symbol")
        return None

    try:
        return exchange.fetch_ohlcv(kraken_symbol, timeframe=timeframe, limit=limit)
    except Exception as error:
        log_warn(f"{kraken_symbol}: Kraken candle fetch failed: {error}")
        return None


def validate_mike_alternate_symbol(exchange, symbol):
    try:
        markets = exchange.load_markets()
    except Exception as error:
        raise MarketDataError(
            f"{symbol}: {MIKE_ALTERNATE_EXCHANGE_ID} market list unavailable"
        ) from error

    if symbol not in markets:
        raise MarketDataError(
            f"{symbol}: unsupported {MIKE_ALTERNATE_EXCHANGE_ID} pair"
        )


def build_mike_symbol_snapshot(primary_exchange, symbol):
    alternate_symbol = MIKE_ALTERNATE_SYMBOLS.get(symbol)
    if not alternate_symbol:
        return build_levels_scan_snapshot(primary_exchange, symbol)

    alternate_exchange = mike_alternate_exchange()
    validate_mike_alternate_symbol(alternate_exchange, alternate_symbol)
    return build_levels_scan_snapshot(alternate_exchange, alternate_symbol)


def build_mike_list_rows(exchange):
    rows = []
    for symbol in mike_list_symbols():
        base = symbol.replace("/USD", "")
        try:
            snapshot = build_mike_symbol_snapshot(exchange, symbol)
            rows.append(
                {
                    "symbol": base,
                    "price": format_level(snapshot["current_price"]),
                    "trend": format_mike_trend(snapshot["bias"]),
                    "rsi": f"{snapshot['rsi']:.2f}",
                    "available": True,
                }
            )
        except Exception as error:
            log_warn(f"{symbol}: Mike list snapshot unavailable: {error}")
            rows.append(
                {
                    "symbol": base,
                    "price": "market data unavailable",
                    "trend": "n/a",
                    "rsi": "n/a",
                    "available": False,
                }
            )
    return rows


def build_mike_list_message_from_rows(rows):
    if not rows:
        return "Mike's list is temporarily unavailable."

    lines = []
    for row in rows:
        lines.append(
            f"{row['symbol']}: Price {row['price']} | "
            f"Trend {row['trend']} | RSI {row['rsi']}"
        )
    return "\n".join(lines)


def build_mike_list_message(exchange):
    return build_mike_list_message_from_rows(build_mike_list_rows(exchange))


def send_mike_list_card(telegram_token, chat_id, rows, caption):
    try:
        if render_mike_list_card is None:
            raise RuntimeError("Mike list card renderer unavailable")
        card_path = render_mike_list_card(rows, logo_path=POINKLE_RESEARCH_EMBLEM_PATH)
        return send_telegram_photo(telegram_token, chat_id, card_path, caption=caption)
    except Exception as error:
        log_warn(f"Mike list card rendering failed: {error}")
        return False


def handle_mike_command(exchange, telegram_token, telegram_chat_id, source_chat=None):
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    try:
        rows = build_mike_list_rows(exchange)
        message = build_mike_list_message_from_rows(rows)
    except Exception as error:
        log_warn(f"Error running /mike: {error}")
        message = "Mike's list is temporarily unavailable. Please try again soon."
        send_telegram_message(telegram_token, response_chat_id, message)
        return

    caption = "The Inner Circle - Mike's List"
    if not send_mike_list_card(telegram_token, response_chat_id, rows, caption):
        send_telegram_message(telegram_token, response_chat_id, message)


def handle_research_command(
    exchange,
    telegram_token,
    telegram_chat_id,
    message_text,
    source_chat=None,
    from_user=None,
):
    parts = message_text.strip().split()
    command = snapshot_command_name(message_text) or "/research"
    log_info(f"Received {message_text.strip()}")
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    from_user = from_user or {}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))

    if len(parts) < 2:
        log_warn(f"Missing symbol for {command} command")
        send_bare_command_watchlist_panel(
            telegram_token,
            telegram_chat_id,
            source_chat,
            from_user,
            command,
            "research",
            "Research",
            command_example_asset(2),
        )
        return

    symbol = normalize_symbol(parts[1])
    log_info(f"Mapped symbol: {symbol or 'UNKNOWN'}")
    if symbol is None:
        log_warn(f"Unsupported {command} symbol: {parts[1]}")
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Symbol currently unavailable.",
        )
        return

    try:
        message = build_research_command_message(exchange, symbol)
    except Exception as error:
        log_warn(f"{symbol}: {command} unavailable: {error}")
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Symbol currently unavailable.",
        )
        return

    if not send_research_cards(
        telegram_token,
        response_chat_id,
        message,
        symbol=symbol,
        chart_data=LAST_RESEARCH_CHART_DATA.get(symbol),
    ):
        send_telegram_message(telegram_token, response_chat_id, message)
    log_info(f"Answered {command} command for {symbol}")


def handle_whynot_command(
    exchange,
    telegram_token,
    telegram_chat_id,
    message_text,
    source_chat=None,
    from_user=None,
):
    parts = message_text.strip().split()
    command = snapshot_command_name(message_text) or "/whynot"
    log_info(f"Received {message_text.strip()}")
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    from_user = from_user or {}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))

    if len(parts) < 2:
        send_bare_command_watchlist_panel(
            telegram_token,
            telegram_chat_id,
            source_chat,
            from_user,
            command,
            "whynot",
            "Why not?",
            "BTC",
        )
        return

    symbol = validate_tradeable_symbol(exchange, parts[1])
    log_info(f"Mapped {command} symbol: {symbol or 'UNKNOWN'}")
    if symbol is None:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "I couldn't find that coin yet. Try the ticker, like /whynot BTC.",
        )
        return

    try:
        message = build_whynot_command_message(exchange, symbol)
    except Exception as error:
        log_warn(f"{symbol}: {command} unavailable: {error}")
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "I couldn't build that signal check right now. Try again in a bit.",
        )
        return

    send_telegram_message(telegram_token, response_chat_id, message)
    log_info(f"Answered {command} command for {symbol}")


def reference_card_symbols():
    return [
        symbol
        for symbol in WATCHLIST
        if symbol not in UNSUPPORTED_SYMBOLS_THIS_SESSION
    ]


def build_coins_command_message(symbols=None):
    symbols = reference_card_symbols() if symbols is None else symbols
    coins = [symbol.replace("/USD", "") for symbol in symbols]
    if not coins:
        return "🪙 Coins Poinkle tracks:\n\nNo tracked coins are available right now."

    return (
        f"🪙 Coins Poinkle tracks: {len(coins)} coins\n\n"
        f"{format_supported_coins_for_help(symbols)}"
    )


def handle_coins_command(telegram_token, telegram_chat_id, source_chat=None):
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    send_telegram_message(telegram_token, response_chat_id, build_coins_command_message())


def reference_text_fallback():
    coins = " ".join(symbol.replace("/USD", "") for symbol in reference_card_symbols())
    return (
        "POINKLE - QUICK REFERENCE\n\n"
        "/snapshot BTC - full visual chart + breakdown\n"
        "/snap ETH - quick version of the same\n"
        "/research SOL - deeper multi-card research brief\n"
        "/levels BTC - legacy text version\n"
        "/alerts XRP support - get DM'd when XRP nears a key zone\n"
        "/myalerts - see your active alerts\n"
        "/help - full command list anytime\n\n"
        f"Supported Coins:\n{coins}\n\n"
        "Every alert is a short-term signal on one specific timeframe - not a call on the overall trend.\n\n"
        "Educational market structure only. Not financial advice. Poinkle did the research. The decision is yours."
    )


def concept_menu_text():
    concepts = ", ".join(available_concepts())
    return (
        "Poinkle can explain these market concepts right now:\n\n"
        f"{concepts}\n\n"
        "Try: /explain rsi\n"
        "Or: /learn breakout"
    )


def unknown_concept_text():
    return (
        "I don't have that one yet — here's what I can explain right now:\n\n"
        f"{', '.join(available_concepts())}"
    )


def build_explain_command_message(message_text, skill_level=None):
    parts = message_text.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return concept_menu_text()

    concept = parts[1].strip()
    explanation = explain_concept(concept, skill_level)
    if explanation is None:
        return unknown_concept_text()

    resolved_key = normalize_concept_key(concept) or concept.lower()
    return f"<b>{concept_display_name(resolved_key)}</b>\n\n{explanation}"


def explain_command_concept_key(message_text):
    parts = message_text.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return None

    concept = parts[1].strip()
    if explain_concept(concept) is None:
        return None
    return normalize_concept_key(concept)


def concept_teaching_card_path(concept_key):
    resolved_key = normalize_concept_key(concept_key)
    if not resolved_key:
        return None

    card_filename = CONCEPT_TEACHING_CARD_FILES.get(resolved_key)
    if not card_filename:
        return None

    card_path = ASSETS_DIR / card_filename
    return card_path if card_path.exists() else None


def send_explain_command_response(telegram_token, response_chat_id, message, concept_key=None):
    card_path = concept_teaching_card_path(concept_key)
    if card_path is None:
        send_telegram_message(telegram_token, response_chat_id, message)
        return

    if send_telegram_photo(telegram_token, response_chat_id, str(card_path)):
        return

    send_telegram_message(telegram_token, response_chat_id, message)


def handle_snapshot_look_order_callback(telegram_token, callback_query):
    callback_query = callback_query or {}
    callback_query_id = callback_query.get("id")
    data = callback_query.get("data") or ""
    if not data.startswith(f"{SNAPSHOT_LOOK_ORDER_CALLBACK_PREFIX}:"):
        return False

    concept_key = data.split(":", 1)[1]
    resolved_key = normalize_concept_key(concept_key)
    if not resolved_key:
        if callback_query_id:
            answer_telegram_callback(telegram_token, callback_query_id, "Concept unavailable.")
        return True

    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    if not chat_id:
        if callback_query_id:
            answer_telegram_callback(telegram_token, callback_query_id, "Concept unavailable.")
        return True

    user_id = str((callback_query.get("from") or {}).get("id") or "")
    skill_level = user_skill_level(user_id) if user_id else None
    if callback_query_id:
        answer_telegram_callback(telegram_token, callback_query_id)
    send_explain_command_response(
        telegram_token,
        chat_id,
        build_explain_command_message(f"/explain {resolved_key}", skill_level=skill_level),
        concept_key=resolved_key,
    )
    return True


def handle_watchlist_coin_callback(telegram_token, callback_query, payload, exchange=None):
    callback_query_id = (callback_query or {}).get("id")
    if callback_query_id:
        answer_telegram_callback(telegram_token, callback_query_id)

    symbol = normalize_trade_symbol_input(payload)
    if not symbol:
        return False

    user_id = str(((callback_query or {}).get("from") or {}).get("id") or "")
    if not user_id:
        return False
    if symbol not in user_watchlist_symbols(user_id):
        return False

    send_telegram_message(
        telegram_token,
        user_id,
        f"<b>{base_symbol(symbol)}</b>\nWhat do you want to open?",
        reply_markup=watchlist_action_keyboard(symbol),
    )
    clear_callback_message_keyboard(telegram_token, callback_query)
    return True


def handle_watchlist_action_callback(telegram_token, callback_query, payload, exchange=None):
    callback_query_id = (callback_query or {}).get("id")
    if callback_query_id:
        answer_telegram_callback(telegram_token, callback_query_id)

    parts = str(payload or "").split(":", 1)
    if len(parts) != 2:
        return False

    action, symbol = parts
    symbol = normalize_trade_symbol_input(symbol)
    user = (callback_query or {}).get("from") or {}
    user_id = str(user.get("id") or "")
    if not user_id or not symbol:
        return False
    if symbol not in user_watchlist_symbols(user_id):
        return False

    source_chat = {"id": user_id, "type": "private"}
    ticker = base_symbol(symbol)
    if action == "snapshot":
        queued = enqueue_telegram_command_job(
            "snapshot",
            user_id,
            f"/snapshot {ticker}",
            source_chat=source_chat,
            from_user=user,
        )
        if queued:
            send_heavy_job_acknowledgment(telegram_token, user_id, "snapshot", f"/snapshot {ticker}")
            clear_callback_message_keyboard(telegram_token, callback_query)
        return True
    if action == "research":
        queued = enqueue_telegram_command_job(
            "research",
            user_id,
            f"/research {ticker}",
            source_chat=source_chat,
            from_user=user,
        )
        if queued:
            send_heavy_job_acknowledgment(telegram_token, user_id, "research", f"/research {ticker}")
            clear_callback_message_keyboard(telegram_token, callback_query)
        return True
    if action == "whynot":
        queued = enqueue_telegram_command_job(
            "whynot",
            user_id,
            f"/whynot {ticker}",
            source_chat=source_chat,
            from_user=user,
        )
        if queued:
            send_heavy_job_acknowledgment(telegram_token, user_id, "whynot", f"/whynot {ticker}")
            clear_callback_message_keyboard(telegram_token, callback_query)
        return True

    return False


def handle_telegram_callback_query(exchange, telegram_token, callback_query):
    callback_query = callback_query or {}
    callback_query_id = callback_query.get("id")
    data = callback_query.get("data") or ""
    namespace, separator, payload = data.partition(":")
    if not separator:
        if callback_query_id:
            answer_telegram_callback(telegram_token, callback_query_id, "Button unavailable.")
        log_warn(f"Unknown Telegram callback data: {data}")
        return False

    callback_handlers = {
        SNAPSHOT_LOOK_ORDER_CALLBACK_PREFIX: (
            lambda token, query, _payload, _exchange=None: handle_snapshot_look_order_callback(token, query)
        ),
        WATCHLIST_COIN_CALLBACK_PREFIX: handle_watchlist_coin_callback,
        WATCHLIST_ACTION_CALLBACK_PREFIX: handle_watchlist_action_callback,
    }
    handler = callback_handlers.get(namespace)
    if handler is None:
        if callback_query_id:
            answer_telegram_callback(telegram_token, callback_query_id, "Button unavailable.")
        log_warn(f"Unknown Telegram callback namespace: {namespace}")
        return False

    try:
        handled = handler(telegram_token, callback_query, payload, exchange)
    except Exception as error:
        if callback_query_id:
            answer_telegram_callback(telegram_token, callback_query_id, "Button unavailable.")
        log_warn(f"Telegram callback handler failed for {namespace}: {error}")
        return False

    if not handled:
        if callback_query_id:
            answer_telegram_callback(telegram_token, callback_query_id, "Button unavailable.")
        log_warn(f"Unhandled Telegram callback data: {data}")
    return bool(handled)


def handle_explain_command(telegram_token, telegram_chat_id, message_text, source_chat=None, from_user=None):
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    from_user = from_user or {}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    is_private = is_private_chat(source_chat)
    user_id = str(from_user.get("id") or response_chat_id if is_private else from_user.get("id") or "")
    skill_level = user_skill_level(user_id) if user_id else None
    send_explain_command_response(
        telegram_token,
        response_chat_id,
        build_explain_command_message(message_text, skill_level=skill_level),
        concept_key=explain_command_concept_key(message_text),
    )


def handle_reference_command(telegram_token, telegram_chat_id, source_chat=None):
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    try:
        if render_reference_card is None:
            raise RuntimeError("Reference card renderer unavailable")
        card_path = render_reference_card(
            reference_card_symbols(),
            logo_path=POINKLE_RESEARCH_EMBLEM_PATH,
        )
        if send_telegram_photo(telegram_token, response_chat_id, card_path):
            return
        raise RuntimeError("Reference card send failed")
    except Exception as error:
        log_warn(f"Reference card rendering failed: {error}")
        send_telegram_message(telegram_token, response_chat_id, reference_text_fallback())


def handle_status_command(telegram_token, telegram_chat_id, state, source_chat=None):
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    send_telegram_message(
        telegram_token,
        response_chat_id,
        build_bot_status_message(state, include_details=True),
    )


def mode_usage_text(command):
    return f"Use: /{command} on\nOr: /{command} off"


def handle_mode_command(telegram_token, telegram_chat_id, message_text, source_chat=None, from_user=None):
    parts = message_text.strip().split()
    command = parts[0].lower().lstrip("/") if parts else ""
    action = parts[1].lower() if len(parts) > 1 else ""
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    user_id = telegram_user_id(source_chat, from_user, telegram_chat_id)
    log_mode_command_debug(
        message_text.strip(),
        user_id,
        username_from_user(from_user),
        response_chat_id,
    )

    if not is_admin_user(user_id):
        send_telegram_message(telegram_token, response_chat_id, "Admin only.")
        return

    if action not in {"on", "off"}:
        send_telegram_message(telegram_token, response_chat_id, mode_usage_text(command))
        return

    if command == "devmode":
        config_key = "developer_mode"
        label = "Developer mode"
    elif command == "maintenance":
        config_key = "maintenance_mode"
        label = "Maintenance mode"
    else:
        config_key = "live_alerts_enabled"
        label = "Live alerts"
    enabled = action == "on"
    config = load_bot_config()
    config[config_key] = enabled
    save_bot_config(config)

    log_info(f"{label} {'enabled' if enabled else 'disabled'} by Telegram user {user_id}.")
    send_telegram_message(
        telegram_token,
        response_chat_id,
        f"✅ {label} {'enabled' if enabled else 'disabled'}.",
    )


def command_allowed_by_active_mode(telegram_token, chat_id, source_chat=None, from_user=None):
    config = load_bot_config()
    user_id = telegram_user_id(source_chat, from_user, chat_id)

    if config.get("developer_mode") and not is_owner_user(user_id):
        send_telegram_message(
            telegram_token,
            str((source_chat or {}).get("id", chat_id)),
            "🧪 Poinkle is currently in developer testing mode.",
        )
        return False

    if config.get("maintenance_mode") and not is_admin_user(user_id):
        send_telegram_message(
            telegram_token,
            str((source_chat or {}).get("id", chat_id)),
            "🔧 Poinkle is currently undergoing maintenance. Please try again shortly.",
        )
        return False

    return True


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


def handle_watch_command(
    exchange,
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

    if len(parts) < 2:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Use: /watch BTC\nI’ll add it to your personal Poinkle watchlist.",
        )
        return

    symbol = validate_tradeable_symbol(exchange, parts[1])
    if symbol is None:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "I couldn’t find that coin yet. Try the ticker, like /watch BTC.",
        )
        return

    watchlists = load_user_watchlists()
    user_symbols = watchlists.setdefault(user_chat_id, [])
    if symbol in user_symbols:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            f"✅ You’re already watching {base_symbol(symbol)}.",
        )
        return

    if len(user_symbols) >= MAX_USER_WATCHLIST:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            f"You’re at the {MAX_USER_WATCHLIST}-coin limit. Remove one first with /unwatch BTC.",
        )
        return

    user_symbols.append(symbol)
    watchlists[user_chat_id] = sorted(user_symbols, key=base_symbol)
    save_user_watchlists(watchlists)
    send_telegram_message(
        telegram_token,
        response_chat_id,
        f"✅ Added {base_symbol(symbol)} to your Poinkle watchlist.",
    )


def handle_unwatch_command(
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

    if len(parts) < 2:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Use: /unwatch BTC\nI’ll remove it from your personal Poinkle watchlist.",
        )
        return

    symbol = normalize_trade_symbol_input(parts[1])
    if symbol is None:
        send_telegram_message(telegram_token, response_chat_id, "Tell me which coin to remove, like /unwatch BTC.")
        return

    watchlists = load_user_watchlists()
    user_symbols = watchlists.get(user_chat_id, [])
    if symbol not in user_symbols:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            f"You weren’t watching {base_symbol(symbol)} yet.",
        )
        return

    user_symbols = [existing_symbol for existing_symbol in user_symbols if existing_symbol != symbol]
    if user_symbols:
        watchlists[user_chat_id] = user_symbols
    else:
        watchlists.pop(user_chat_id, None)
    save_user_watchlists(watchlists)
    send_telegram_message(
        telegram_token,
        response_chat_id,
        f"✅ Removed {base_symbol(symbol)} from your Poinkle watchlist.",
    )


def user_watchlist_symbols(user_chat_id):
    return load_user_watchlists().get(str(user_chat_id), [])


def send_bare_command_watchlist_panel(
    telegram_token,
    telegram_chat_id,
    source_chat,
    from_user,
    command,
    action,
    action_label,
    example_ticker,
):
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    from_user = from_user or {}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    user_chat_id = alert_dm_chat_id(source_chat, from_user, telegram_chat_id)
    user_symbols = user_watchlist_symbols(user_chat_id)

    if not user_symbols:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            f"Use: {command} {example_ticker}\n"
            f"Or start a watchlist with /watch {example_ticker}.",
        )
        return True

    sorted_symbols = sorted(user_symbols, key=base_symbol)
    is_private = is_private_chat(source_chat)
    try:
        send_telegram_message(
            telegram_token,
            user_chat_id,
            f"{action_label} — pick a coin below, or type any ticker (e.g. {command} {example_ticker})",
            reply_markup=watchlist_direct_action_keyboard(sorted_symbols, action),
        )
        if not is_private:
            send_telegram_message(
                telegram_token,
                response_chat_id,
                f"I sent your {action_label.lower()} coin picker to your DM.",
            )
    except Exception as error:
        log_warn(f"Could not DM {action} picker to user {user_chat_id}: {error}")
        if not is_private:
            send_telegram_message(telegram_token, response_chat_id, levels_dm_failed_message())
    return True


def handle_mywatch_command(
    telegram_token,
    telegram_chat_id,
    source_chat=None,
    from_user=None,
):
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    user_chat_id = alert_dm_chat_id(source_chat, from_user or {}, telegram_chat_id)
    is_private = is_private_chat(source_chat)
    user_symbols = user_watchlist_symbols(user_chat_id)

    if not user_symbols:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "You’re not watching any coins yet. Add one with /watch BTC.",
        )
        return

    sorted_symbols = sorted(user_symbols, key=base_symbol)
    lines = ["Your watchlist:"]
    for index, symbol in enumerate(sorted_symbols, start=1):
        lines.append(f"{index}. {base_symbol(symbol)}")
    try:
        send_telegram_message(
            telegram_token,
            user_chat_id,
            "\n".join(lines),
            reply_markup=watchlist_coin_keyboard(sorted_symbols),
        )
        if not is_private:
            send_telegram_message(
                telegram_token,
                response_chat_id,
                "I sent your watchlist panel to your DM.",
            )
    except Exception as error:
        log_warn(f"Could not DM watchlist panel to user {user_chat_id}: {error}")
        if not is_private:
            send_telegram_message(telegram_token, response_chat_id, levels_dm_failed_message())


def handle_clearwatch_command(
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
    watchlists = load_user_watchlists()
    user_symbols = sorted(watchlists.get(user_chat_id, []), key=base_symbol)

    if len(parts) < 2:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Use: /clearwatch 2\nOr: /clearwatch 2 3 4\nOr: /clearwatch all",
        )
        return

    if not user_symbols:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "You’re not watching any coins yet. Add one with /watch BTC.",
        )
        return

    args = [part.lower() for part in parts[1:]]
    if args[0] == "all":
        if len(args) >= 2 and args[1] == "confirm":
            watchlists.pop(user_chat_id, None)
            save_user_watchlists(watchlists)
            send_telegram_message(
                telegram_token,
                response_chat_id,
                f"✅ Cleared all {len(user_symbols)} coins from your watchlist.",
            )
            return
        send_telegram_message(
            telegram_token,
            response_chat_id,
            f"This will remove all {len(user_symbols)} coins. Reply /clearwatch all confirm to proceed.",
        )
        return

    requested_positions = []
    invalid_args = []
    for arg in args:
        try:
            position = int(arg)
        except ValueError:
            invalid_args.append(arg)
            continue
        if position < 1 or position > len(user_symbols):
            invalid_args.append(arg)
            continue
        requested_positions.append(position)

    if invalid_args:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            f"You don’t have an item {', '.join(invalid_args)}.",
        )
        return

    if not requested_positions:
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Use numbers from /mywatch, like /clearwatch 2.",
        )
        return

    positions_to_remove = set(requested_positions)
    removed_symbols = [
        symbol
        for index, symbol in enumerate(user_symbols, start=1)
        if index in positions_to_remove
    ]
    remaining_symbols = [
        symbol
        for index, symbol in enumerate(user_symbols, start=1)
        if index not in positions_to_remove
    ]

    if remaining_symbols:
        watchlists[user_chat_id] = remaining_symbols
    else:
        watchlists.pop(user_chat_id, None)
    save_user_watchlists(watchlists)

    removed = ", ".join(base_symbol(symbol) for symbol in removed_symbols)
    send_telegram_message(
        telegram_token,
        response_chat_id,
        f"Removed: {removed}.",
    )


def handle_levels_command(
    exchange,
    telegram_token,
    telegram_chat_id,
    message_text,
    source_chat=None,
    from_user=None,
):
    parts = message_text.strip().split()
    command = snapshot_command_name(message_text) or "/snapshot"
    log_info(f"Received {message_text.strip()}")
    source_chat = source_chat or {"id": telegram_chat_id, "type": "private"}
    from_user = from_user or {}
    response_chat_id = str(source_chat.get("id", telegram_chat_id))
    is_private = is_private_chat(source_chat)
    user_id = str(from_user.get("id") or response_chat_id if is_private else from_user.get("id") or "")
    skill_level = user_skill_level(user_id) if user_id else None

    if len(parts) < 2:
        log_warn(f"Missing symbol for {command} command")
        send_bare_command_watchlist_panel(
            telegram_token,
            telegram_chat_id,
            source_chat,
            from_user,
            command,
            "snapshot",
            "Snapshot",
            "BTC",
        )
        return

    symbol = normalize_symbol(parts[1])
    log_info(f"Mapped symbol: {symbol or 'UNKNOWN'}")
    if symbol is None:
        log_warn(f"Unsupported {command} symbol: {parts[1]}")
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Symbol currently unavailable.",
        )
        return

    if not is_private:
        maybe_send_skill_onboarding(telegram_token, source_chat, from_user)

    try:
        if skill_level:
            message = build_levels_command_message(exchange, symbol, skill_level=skill_level)
        else:
            message = build_levels_command_message(exchange, symbol)
    except Exception as error:
        log_warn(f"{symbol}: {command} unavailable: {error}")
        send_telegram_message(
            telegram_token,
            response_chat_id,
            "Symbol currently unavailable.",
        )
        return

    if is_private:
        log_info("Sending Poinkle snapshot")
        if not send_levels_chart(
            telegram_token,
            response_chat_id,
            symbol,
            message,
            reply_markup=snapshot_look_order_keyboard(),
        ):
            send_telegram_message(telegram_token, response_chat_id, message)
        log_info(f"Answered {command} command for {symbol}")
        return

    if not user_id:
        log_warn("Missing Telegram user id for DM delivery")
        send_telegram_message(telegram_token, response_chat_id, levels_dm_failed_message())
        return

    try:
        if not send_levels_chart(
            telegram_token,
            str(user_id),
            symbol,
            message,
            reply_markup=snapshot_look_order_keyboard(),
        ):
            send_telegram_message(telegram_token, str(user_id), message)
        send_telegram_message(
            telegram_token,
            response_chat_id,
            levels_dm_success_message(symbol),
        )
        log_info(f"Sent {symbol} snapshot to DM for user {user_id}")
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
        try:
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
                        f"user-alert:{alert_type}",
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
        except Exception as error:
            log_warn(f"Could not process user alerts for {user_chat_id}: {error}")
            continue

    if changed:
        save_user_alerts(user_alerts)


def process_telegram_commands(
    exchange,
    telegram_token,
    telegram_chat_id,
    state,
    defer_heavy_commands=False,
    telegram_poll_timeout=1,
):
    command_state = state.setdefault("__telegram_commands", {})
    last_update_id = command_state.get("last_update_id")

    try:
        offset = last_update_id + 1 if last_update_id is not None else None
        updates = get_telegram_updates(telegram_token, offset, poll_timeout=telegram_poll_timeout)
    except Exception as error:
        throttled_log_warn(
            "telegram",
            "updates",
            "Telegram command polling failed. Will retry quietly.",
        )
        return

    for update in updates:
        update_id = update["update_id"]
        callback_query = update.get("callback_query")
        if callback_query:
            callback_query_id = callback_query.get("id")
            if telegram_callback_already_handled(command_state, callback_query_id):
                if callback_query_id:
                    answer_telegram_callback(telegram_token, callback_query_id)
                command_state["last_update_id"] = update_id
                save_state(state)
                continue

            mark_telegram_callback_handled(command_state, callback_query_id)
            command_state["last_update_id"] = update_id
            save_state(state)
            handle_telegram_callback_query(exchange, telegram_token, callback_query)
            save_state(state)
            continue

        message = update.get("message") or {}
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()
        lower_text = text.lower()
        from_user = message.get("from", {})
        if text.startswith("/"):
            message_key = telegram_message_dedupe_key(message, text)
            if telegram_message_already_handled(command_state, message_key):
                command_state["last_update_id"] = update_id
                save_state(state)
                continue
            mark_telegram_message_handled(command_state, message_key)
            save_state(state)

        if maybe_send_alpha_onboarding(telegram_token, chat, text, from_user):
            pass
        elif handle_skill_level_reply(telegram_token, chat, text, from_user):
            pass
        elif lower_text.startswith("/start"):
            handle_start_command(telegram_token, chat_id, from_user=from_user)
        elif lower_text.startswith("/help"):
            handle_help_command(telegram_token, chat_id)
        elif not text.startswith("/"):
            pass
        elif (
            lower_text.startswith("/devmode")
            or lower_text.startswith("/maintenance")
            or lower_text.startswith("/livealerts")
        ):
            if command_allowed_by_active_mode(
                telegram_token,
                chat_id,
                source_chat=chat,
                from_user=from_user,
            ):
                handle_mode_command(
                    telegram_token,
                    chat_id,
                    text,
                    source_chat=chat,
                    from_user=from_user,
                )
        elif not command_allowed_by_active_mode(
            telegram_token,
            chat_id,
            source_chat=chat,
            from_user=from_user,
        ):
            pass
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
                from_user=from_user,
            )
        elif lower_text.startswith("/mywatch") or lower_text.startswith("/watching"):
            handle_mywatch_command(
                telegram_token,
                chat_id,
                source_chat=chat,
                from_user=from_user,
            )
        elif lower_text.startswith("/alerts"):
            handle_alerts_command(
                telegram_token,
                chat_id,
                text,
                source_chat=chat,
                from_user=from_user,
            )
        elif lower_text.startswith("/clearwatch"):
            handle_clearwatch_command(
                telegram_token,
                chat_id,
                text,
                source_chat=chat,
                from_user=from_user,
            )
        elif lower_text.startswith("/unwatch"):
            handle_unwatch_command(
                telegram_token,
                chat_id,
                text,
                source_chat=chat,
                from_user=from_user,
            )
        elif lower_text.startswith("/watch"):
            handle_watch_command(
                exchange,
                telegram_token,
                chat_id,
                text,
                source_chat=chat,
                from_user=from_user,
            )
        elif lower_text.startswith("/scan"):
            handle_scan_command(
                exchange,
                telegram_token,
                chat_id,
                text,
                source_chat=chat,
            )
        elif lower_text.startswith("/mike"):
            handle_mike_command(
                exchange,
                telegram_token,
                chat_id,
                source_chat=chat,
            )
        elif lower_text.startswith("/coins"):
            handle_coins_command(
                telegram_token,
                chat_id,
                source_chat=chat,
            )
        elif is_explain_command(text):
            handle_explain_command(
                telegram_token,
                chat_id,
                text,
                source_chat=chat,
                from_user=from_user,
            )
        elif is_reference_command(text):
            handle_reference_command(
                telegram_token,
                chat_id,
                source_chat=chat,
            )
        elif is_whynot_command(text):
            if defer_heavy_commands and should_enqueue_heavy_command(text):
                if enqueue_telegram_command_job("whynot", chat_id, text, source_chat=chat, from_user=from_user):
                    send_heavy_job_acknowledgment(
                        telegram_token,
                        alert_dm_chat_id(chat, from_user, chat_id),
                        "whynot",
                        text,
                    )
            else:
                handle_whynot_command(
                    exchange,
                    telegram_token,
                    chat_id,
                    text,
                    source_chat=chat,
                    from_user=from_user,
                )
        elif is_research_command(text):
            if defer_heavy_commands and should_enqueue_heavy_command(text):
                if enqueue_telegram_command_job("research", chat_id, text, source_chat=chat, from_user=from_user):
                    send_heavy_job_acknowledgment(
                        telegram_token,
                        alert_dm_chat_id(chat, from_user, chat_id),
                        "research",
                        text,
                    )
            else:
                handle_research_command(
                    exchange,
                    telegram_token,
                    chat_id,
                    text,
                    source_chat=chat,
                    from_user=from_user,
                )
        elif is_snapshot_command(text):
            if defer_heavy_commands and should_enqueue_heavy_command(text):
                if enqueue_telegram_command_job("snapshot", chat_id, text, source_chat=chat, from_user=from_user):
                    send_heavy_job_acknowledgment(
                        telegram_token,
                        alert_dm_chat_id(chat, from_user, chat_id),
                        "snapshot",
                        text,
                    )
            else:
                handle_levels_command(
                    exchange,
                    telegram_token,
                    chat_id,
                    text,
                    source_chat=chat,
                    from_user=from_user,
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


def evaluate_lightweight_signal_state(previous_closed_candles, closed_candles):
    previous_closed = closed_candles[-2]
    latest_closed = closed_candles[-1]
    previous_closes = [candle[4] for candle in previous_closed_candles]
    closes = [candle[4] for candle in closed_candles]

    previous_ema_21 = ema(previous_closes, TREND_GATE_FAST_EMA)
    previous_ema_55 = ema(previous_closes, TREND_GATE_SLOW_EMA)
    current_ema_21 = ema(closes, TREND_GATE_FAST_EMA)
    current_ema_55 = ema(closes, TREND_GATE_SLOW_EMA)
    previous_rsi = rsi(previous_closes, 14)
    current_rsi = rsi(closes, 14)

    previous_20_volumes = [candle[5] for candle in closed_candles[-21:-1]]
    volume_average = sum(previous_20_volumes) / len(previous_20_volumes)
    current_volume = latest_closed[5]
    volume_multiple = current_volume / volume_average if volume_average > 0 else 0

    crossed_above = previous_ema_21 <= previous_ema_55 and current_ema_21 > current_ema_55
    crossed_below = previous_ema_21 >= previous_ema_55 and current_ema_21 < current_ema_55
    rsi_crossed_above_70 = previous_rsi <= 70 and current_rsi > 70
    rsi_crossed_below_30 = previous_rsi >= 30 and current_rsi < 30

    alerts = []
    scorecard = [
        {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "state": "pass" if crossed_above else "fail",
            "direction": "bullish",
            "reason": (
                f"EMA21 {format_level(current_ema_21)} vs EMA55 {format_level(current_ema_55)}"
                f"{'' if crossed_above else '; no fresh bullish cross'}"
            ),
        },
        {
            "type": "ema_cross_below",
            "label": "EMA 21 crossed below EMA 55",
            "state": "pass" if crossed_below else "fail",
            "direction": "bearish",
            "reason": (
                f"EMA21 {format_level(current_ema_21)} vs EMA55 {format_level(current_ema_55)}"
                f"{'' if crossed_below else '; no fresh bearish cross'}"
            ),
        },
        {
            "type": "rsi_cross_above_70",
            "label": "RSI crossed above 70",
            "state": "pass" if rsi_crossed_above_70 else "fail",
            "direction": "bullish",
            "reason": f"RSI {current_rsi:.1f}{'' if rsi_crossed_above_70 else '; no cross above 70'}",
        },
        {
            "type": "rsi_cross_below_30",
            "label": "RSI crossed below 30",
            "state": "pass" if rsi_crossed_below_30 else "fail",
            "direction": "bearish",
            "reason": f"RSI {current_rsi:.1f}{'' if rsi_crossed_below_30 else '; no cross below 30'}",
        },
    ]

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

    volume_signal = {
        "type": "volume_spike",
        "label": "Volume spike",
        "state": "fail",
        "direction": "neutral",
        "reason": f"{volume_multiple:.2f}x recent average; below 2.00x spike threshold",
    }
    if volume_average > 0 and current_volume >= volume_average * 2:
        close = latest_closed[4]
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
        volume_signal.update(
            {
                "label": volume_label,
                "state": "pass" if volume_direction in {"bullish", "bearish"} else "neutral",
                "direction": volume_direction,
                "reason": f"{volume_multiple:.2f}x recent average",
            }
        )
    scorecard.insert(0, volume_signal)

    return {
        "previous_closed": previous_closed,
        "latest_closed": latest_closed,
        "alerts": alerts,
        "scorecard": scorecard,
        "previous_ema_21": previous_ema_21,
        "previous_ema_55": previous_ema_55,
        "ema_21": current_ema_21,
        "ema_55": current_ema_55,
        "previous_rsi": previous_rsi,
        "rsi": current_rsi,
        "volume_average": volume_average,
        "current_volume": current_volume,
        "volume_multiple": volume_multiple,
    }


def whynot_verdict(aligned_count):
    if aligned_count >= 4:
        return "Strong confluence"
    if aligned_count == 3:
        return "Building confluence"
    if aligned_count == 2:
        return "At alert threshold"
    if aligned_count == 1:
        return "Waiting for another same-direction signal"
    return "Waiting"


def whynot_marker(state):
    if state == "pass":
        return "✓"
    if state == "fail":
        return "✗"
    return "•"


def whynot_display_scorecard(scorecard):
    by_type = {item.get("type"): item for item in scorecard}
    volume = by_type.get("volume_spike", {})
    ema_above = by_type.get("ema_cross_above", {})
    ema_below = by_type.get("ema_cross_below", {})
    rsi_above = by_type.get("rsi_cross_above_70", {})
    rsi_below = by_type.get("rsi_cross_below_30", {})

    if ema_above.get("state") == "pass":
        ema_row = {
            "label": "EMA cross",
            "state": "pass",
            "reason": f"bullish cross; {ema_above.get('reason', '')}",
        }
    elif ema_below.get("state") == "pass":
        ema_row = {
            "label": "EMA cross",
            "state": "pass",
            "reason": f"bearish cross; {ema_below.get('reason', '')}",
        }
    else:
        ema_reason = ema_above.get("reason") or ema_below.get("reason") or "no fresh cross"
        ema_row = {
            "label": "EMA cross",
            "state": "fail",
            "reason": ema_reason.replace("; no fresh bullish cross", "; no fresh cross"),
        }

    if rsi_above.get("state") == "pass":
        rsi_row = {
            "label": "RSI extreme",
            "state": "pass",
            "reason": f"above 70; {rsi_above.get('reason', '')}",
        }
    elif rsi_below.get("state") == "pass":
        rsi_row = {
            "label": "RSI extreme",
            "state": "pass",
            "reason": f"below 30; {rsi_below.get('reason', '')}",
        }
    else:
        rsi_reason = rsi_above.get("reason") or rsi_below.get("reason") or "neutral"
        rsi_value = rsi_reason.split(";", 1)[0]
        rsi_row = {
            "label": "RSI extreme",
            "state": "fail",
            "reason": f"neutral ({rsi_value.replace('RSI ', '')})",
        }

    return [
        {
            "label": "Volume",
            "state": volume.get("state", "fail"),
            "reason": volume.get("reason", "no spike"),
        },
        ema_row,
        rsi_row,
    ]


def evaluate_whynot_scorecard(exchange, symbol):
    (
        _previous_candle,
        candle,
        alerts,
        ema_21,
        ema_55,
        current_rsi,
        current_atr_14,
        volume_avg,
        range_low,
        range_high,
        closed_candles,
        key_levels,
    ) = scan_symbol(exchange, symbol)

    signal_state = evaluate_lightweight_signal_state(closed_candles[:-2], closed_candles)
    directional_group = strongest_directional_lightweight_group(alerts)
    range_location, range_position = get_range_location(candle[4], range_low, range_high)

    scorecard = {
        "symbol": symbol,
        "candle": candle,
        "alerts": alerts,
        "scorecard": signal_state["scorecard"],
        "aligned_count": len(directional_group),
        "aligned_alerts": directional_group,
        "ema_21": ema_21,
        "ema_55": ema_55,
        "rsi": current_rsi,
        "atr_14": current_atr_14,
        "volume_average": volume_avg,
        "volume_multiple": signal_state["volume_multiple"],
        "range_low": range_low,
        "range_high": range_high,
        "range_location": range_location,
        "range_position": range_position,
    }
    enforce_validation(symbol, "whynot", validate_whynot_scorecard_data(scorecard))
    return scorecard


def build_whynot_command_message(exchange, symbol):
    scorecard = evaluate_whynot_scorecard(exchange, symbol)
    display_rows = whynot_display_scorecard(scorecard["scorecard"])
    lines = [
        f"<b>{html.escape(symbol)} - Why not?</b>",
        "",
        "Current lightweight signal state:",
    ]

    for item in display_rows:
        marker = whynot_marker(item.get("state"))
        label = html.escape(item.get("label", "Signal"))
        reason = html.escape(item.get("reason", "No current signal"))
        lines.append(f"{marker} {label}: {reason}")

    aligned_count = scorecard["aligned_count"]
    present_count = sum(1 for item in display_rows if item.get("state") == "pass")
    verdict = whynot_verdict(aligned_count)
    lines.extend(
        [
            "",
            f"<b>{present_count} of {len(display_rows)} signals present.</b>",
            f"<b>{aligned_count} same-direction aligned - {verdict}.</b>",
            (
                f"Range: {scorecard['range_location']} "
                f"({scorecard['range_position'] * 100:.0f}% through the current range)."
            ),
            "",
            "Honest limit: this describes right now; conditions change.",
        ]
    )
    return "\n".join(lines)


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
    if not TRADE_TRACKING_TELEGRAM_ENABLED:
        return

    if main_chat_safe_mode_enabled():
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
                if TRADE_TRACKING_TELEGRAM_ENABLED:
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
                "active-trade",
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
    candle_series=None,
    key_levels=None,
):
    levels = key_levels if key_levels is not None else get_key_levels(symbol, current_market_price)
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

            if direction == "breakout" and not breakout_confirmation_quality_met(
                current_candle,
                location_filter,
                candle_series or [previous_candle, current_candle],
            ):
                alerts.append(
                    {
                        "type": f"{setup_key}:weak_break",
                        "label": "Weak Break / Watch Only",
                        "emoji": "⚠️",
                        "level": level,
                        "detail": "Break detected, but breakout quality floor was not met.",
                        "location_filter": location_filter,
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
        if resolve_data_source(symbol) == "kraken":
            candles = fetch_kraken_ohlcv(symbol, timeframe=TIMEFRAME, limit=CANDLE_LIMIT)
        else:
            candles = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=CANDLE_LIMIT)
        validate_ohlcv_candles(candles, symbol, min_count=80)
    except Exception as error:
        raise MarketDataError(candle_error_message(symbol, error)) from error

    if len(candles) < 80:
        raise MarketDataError("Not enough candles for indicators")

    # Coinbase includes the currently forming candle as the last item.
    # The second-to-last candle is the most recent fully closed daily candle.
    previous_closed_candles = candles[:-2]
    closed_candles = candles[:-1]
    previous_closed = closed_candles[-2]
    latest_closed = closed_candles[-1]
    range_low, range_high = get_recent_range(closed_candles[:-1], 50)
    key_levels = daily_support_resistance_levels(closed_candles, latest_closed[4])

    signal_state = evaluate_lightweight_signal_state(previous_closed_candles, closed_candles)
    current_ema_21 = signal_state["ema_21"]
    current_ema_55 = signal_state["ema_55"]
    current_rsi = signal_state["rsi"]
    current_atr_14 = atr(closed_candles, 14)
    volume_average = signal_state["volume_average"]
    alerts = signal_state["alerts"]

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
        closed_candles,
        key_levels,
    )


def run_once(exchange, telegram_token, telegram_chat_id, state, poll_telegram_during_scan=False):
    scan_start = time.perf_counter()
    scanned_symbols = 0
    skipped_symbols = 0
    failed_symbols = 0
    compact_scan_lines = []
    main_chat_safe_mode = main_chat_safe_mode_enabled()
    scan_symbols = build_scan_symbols()
    for symbol_index, symbol in enumerate(scan_symbols, start=1):
        if (
            poll_telegram_during_scan
            and symbol_index > 1
            and (symbol_index - 1) % TELEGRAM_POLL_EVERY_N_SYMBOLS == 0
        ):
            process_telegram_commands(
                exchange,
                telegram_token,
                telegram_chat_id,
                state,
                defer_heavy_commands=True,
                telegram_poll_timeout=0,
            )
            process_telegram_command_jobs(
                exchange,
                telegram_token,
                time_budget_seconds=TELEGRAM_JOB_BUDGET_SECONDS_PER_CHUNK,
                allowed_weights={TELEGRAM_JOB_LIGHT},
            )

        if symbol in UNSUPPORTED_SYMBOLS_THIS_SESSION:
            skipped_symbols += 1
            continue
        try:
            scanned_symbols += 1
            symbol_state = state.setdefault(symbol, {})
            scan_result = scan_symbol(exchange, symbol)
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
            ) = scan_result[:10]
            alert_candles = scan_result[10] if len(scan_result) > 10 else [previous_candle, candle]
            key_levels = (
                scan_result[11]
                if len(scan_result) > 11
                else {"support": [range_low], "resistance": [range_high]}
            )
            support_levels = key_levels.get("support", [])
            resistance_levels = key_levels.get("resistance", [])
            candle_id = str(candle[0])
            sent_alerts = symbol_state.setdefault("sent_alerts", {})

            if symbol_state.get("last_checked_candle") == candle_id:
                continue

            pending_before_scan = bool(symbol_state.get("pending_setups"))
            tracking_is_active = symbol in state.setdefault("__active_trades", {})
            current_market_price = get_current_market_price(exchange, symbol, candle[4])
            if main_chat_safe_mode:
                if alerts and not LIVE_ALERT_TEST_CHAT_ID:
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
                        candle_series=alert_candles,
                        key_levels=key_levels,
                    )
                )

            active_trade_status = (
                state.setdefault("__active_trades", {})
                .get(symbol, {})
                .get("last_status")
            )
            range_location, _ = get_range_location(candle[4], range_low, range_high)
            pending_alerts = []
            for alert in alerts:
                dedup_key = alert_dedupe_key(alert, candle[4])
                event_key = f"{candle_id}:{dedup_key}"
                if sent_alerts.get(dedup_key) == event_key:
                    continue
                if not should_send_level_break_alert(alert):
                    if alert["type"].endswith(":early_warning"):
                        add_active_trade(state, symbol, alert, candle)
                        tracking_is_active = True
                    elif alert["type"].endswith(":late_move"):
                        remove_active_trade(state, symbol)
                    sent_alerts[dedup_key] = event_key
                    save_state(state)
                    continue
                if not should_send_telegram_alert(
                    alert,
                    alerts,
                    active_trade_status,
                    ema_21=ema_21,
                    ema_55=ema_55,
                    range_location=range_location,
                    current_price=candle[4],
                    range_low=range_low,
                    range_high=range_high,
                ):
                    log_suppressed_volume_alert(
                        symbol,
                        candle,
                        alert,
                        volume_avg,
                        (
                            "Bullish swing-entry qualification filters were not met."
                        ),
                    )
                    sent_alerts[dedup_key] = event_key
                    save_state(state)
                    continue
                pending_alerts.append(alert)

            log_accuracy_audit_snapshot(
                symbol,
                candle,
                current_market_price,
                ema_21,
                ema_55,
                current_rsi,
            )

            sent_alert_labels = []
            sent_alert_types = []
            alert_group = pending_alerts
            if pending_alerts:
                now = int(time.time())
                all_lightweight_alerts = all(is_lightweight_alert(alert) for alert in pending_alerts)
                if all_lightweight_alerts and is_stablecoin_symbol(symbol):
                    log_suppressed_lightweight_alert(
                        symbol,
                        candle,
                        pending_alerts,
                        "Stablecoin symbols are excluded from confluence alerts.",
                    )
                    for alert in pending_alerts:
                        dedup_key = alert_dedupe_key(alert, candle[4])
                        sent_alerts[dedup_key] = f"{candle_id}:{dedup_key}"
                    save_state(state)
                    pending_alerts = []
                    alert_group = []
                else:
                    alert_group = rolling_confluence_alerts(state, symbol, pending_alerts, now)
                    record_scan_alert_history(state, symbol, pending_alerts, now)
                if pending_alerts and all(is_lightweight_alert(alert) for alert in alert_group) and not has_lightweight_confluence(alert_group):
                    log_suppressed_lightweight_alert(
                        symbol,
                        candle,
                        alert_group,
                        "Waiting for another distinct lightweight signal within 15 minutes.",
                    )
                    for alert in pending_alerts:
                        dedup_key = alert_dedupe_key(alert, candle[4])
                        sent_alerts[dedup_key] = f"{candle_id}:{dedup_key}"
                    save_state(state)
                    pending_alerts = []
                    alert_group = []

            if pending_alerts:
                should_send_group, cooldown_tier, remaining_seconds = should_send_scan_alert_group(
                    state,
                    symbol,
                    alert_group,
                )
                if not should_send_group:
                    log_info(
                        f"Suppressed {cooldown_tier} scanner alert for {symbol}: "
                        f"cooldown active for {remaining_seconds}s."
                    )
                    for alert in pending_alerts:
                        dedup_key = alert_dedupe_key(alert, candle[4])
                        sent_alerts[dedup_key] = f"{candle_id}:{dedup_key}"
                    save_state(state)
                    pending_alerts = []
                    alert_group = []

            if pending_alerts:
                destination_chat_id = telegram_chat_id
                if main_chat_safe_mode:
                    if LIVE_ALERT_TEST_CHAT_ID:
                        destination_chat_id = LIVE_ALERT_TEST_CHAT_ID
                    else:
                        log_info(
                            f"MAIN_CHAT_SAFE_MODE active - skipped Telegram alert for {symbol}: "
                            f"{', '.join(alert['label'] for alert in pending_alerts)}"
                        )
                        pending_alerts = []

            if pending_alerts:
                secondary_timeframe_context = get_secondary_timeframe_context(exchange, symbol)
                if not secondary_timeframe_context:
                    log_info(
                        f"Suppressed scanner alert for {symbol}: "
                        "secondary 6h context unavailable."
                    )
                    for alert in pending_alerts:
                        dedup_key = alert_dedupe_key(alert, candle[4])
                        sent_alerts[dedup_key] = f"{candle_id}:{dedup_key}"
                    save_state(state)
                    pending_alerts = []
                    alert_group = []
                else:
                    for alert in alert_group:
                        alert["secondary_timeframe_context"] = secondary_timeframe_context

            if pending_alerts:
                for alert in pending_alerts:
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

                log_info(
                    "Alert timing candidate: "
                    f"{symbol} "
                    f"{' + '.join(alert['label'] for alert in alert_group)} | "
                    f"candle close {eastern_time_from_timestamp(candle_close_timestamp_ms(candle))} | "
                    f"scan time {eastern_time_now()}"
                )
                image_sent = send_alert_group_to_chat(
                    telegram_token,
                    destination_chat_id,
                    symbol,
                    candle,
                    alert_group,
                    ema_21,
                    ema_55,
                    current_rsi,
                    volume_avg,
                    alert_candles=alert_candles,
                    supports=support_levels,
                    resistances=resistance_levels,
                )
                sent_at = time.time()
                metric = record_alert_delivery_metric(
                    state,
                    symbol,
                    candle,
                    alert_group,
                    sent_at=sent_at,
                    delivery_type="photo" if image_sent else "text_fallback",
                )
                log_alert_delivery_metric(metric, alert_delivery_metrics(state))
                append_diagnostic_record(
                    {
                        "record_type": "delivery",
                        **metric,
                        "direction": [alert.get("direction", "") for alert in alert_group],
                        "volume_multiple": [alert.get("volume_multiple") for alert in alert_group],
                        "current_market_price": current_market_price,
                        "current_rsi": current_rsi,
                        "ema_21": ema_21,
                        "ema_55": ema_55,
                        "current_atr_14": current_atr_14,
                        "range_low": range_low,
                        "range_high": range_high,
                        "main_chat_safe_mode": main_chat_safe_mode,
                        "live_alert_test_chat_id_configured": bool(LIVE_ALERT_TEST_CHAT_ID),
                        "routed_to_test_chat": main_chat_safe_mode and bool(LIVE_ALERT_TEST_CHAT_ID),
                    }
                )
                if main_chat_safe_mode and LIVE_ALERT_TEST_CHAT_ID:
                    log_info(
                        f"MAIN_CHAT_SAFE_MODE active - routed live alert for {symbol} "
                        "to test chat instead of main chat."
                    )
                mark_scan_alert_group_sent(state, symbol, alert_group)
                if not main_chat_safe_mode:
                    deliver_personal_watchlist_alerts(
                        state,
                        telegram_token,
                        symbol,
                        candle,
                        alert_group,
                        ema_21,
                        ema_55,
                        current_rsi,
                        volume_avg,
                        alert_candles=alert_candles,
                        supports=support_levels,
                        resistances=resistance_levels,
                    )

            for alert in pending_alerts:
                dedup_key = alert_dedupe_key(alert, candle[4])
                event_key = f"{candle_id}:{dedup_key}"
                sent_alerts[dedup_key] = event_key
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
            failed_symbols += 1
            throttled_log_warn(
                symbol,
                str(error),
                candle_error_message(symbol, error),
            )
            append_diagnostic_record(
                {
                    "record_type": "scan_failure",
                    "symbol": symbol,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    "error_class": classify_scan_failure_error(error),
                }
            )

    benchmark = scan_cycle_benchmark(
        time.perf_counter() - scan_start,
        scanned_symbols,
        skipped_symbols=skipped_symbols,
        failed_symbols=failed_symbols,
    )
    log_info(format_scan_cycle_benchmark(benchmark))
    print_compact_scan_summary(compact_scan_lines)
    save_state(state)


def main():
    global LIVE_ALERT_TEST_CHAT_ID

    load_dotenv()

    if ccxt is None:
        raise SystemExit("Missing ccxt. Run: pip install -r requirements.txt")
    if requests is None:
        raise SystemExit("Missing requests. Run: pip install -r requirements.txt")

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    LIVE_ALERT_TEST_CHAT_ID = os.getenv("LIVE_ALERT_TEST_CHAT_ID", "").strip()

    if not telegram_token or not telegram_chat_id:
        raise SystemExit(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID. Add them to your .env file."
        )

    try:
        ensure_diagnostics_dir()
    except Exception as error:
        log_warn(f"Could not create diagnostics directory: {error}")

    exchange = ccxt.coinbase()
    supported_symbols, unsupported_symbols = validate_watchlist_against_exchange(exchange, WATCHLIST)
    UNSUPPORTED_SYMBOLS_THIS_SESSION.update(unsupported_symbols)
    state = load_state()
    update_bot_status(state, "Online", "Starting")
    save_state(state)
    register_bot_commands(telegram_token)
    send_status_update(telegram_token, telegram_chat_id, state, indicator="🟢")

    log_info("Poinkle scanner started.")
    log_info(f"Watching {len(WATCHLIST)} global symbols.")
    log_info(f"Loaded {count_enabled_user_alerts(load_user_alerts())} user alerts.")
    if TEST_MODE and DEBUG:
        run_test_mode_location_filter_examples()

    try:
        while True:
            loop_phase_start = time.perf_counter()
            update_bot_status(state, "Online", "Checking commands")
            save_state(state)
            process_telegram_commands(
                exchange,
                telegram_token,
                telegram_chat_id,
                state,
                defer_heavy_commands=True,
            )
            command_seconds = time.perf_counter() - loop_phase_start

            scan_phase_start = time.perf_counter()
            update_bot_status(state, "Online", "Scanning")
            save_state(state)
            run_once(
                exchange,
                telegram_token,
                telegram_chat_id,
                state,
                poll_telegram_during_scan=True,
            )
            update_bot_status(state, "Online", "Scan complete", last_scan_time=eastern_time_now())
            save_state(state)
            scan_seconds = time.perf_counter() - scan_phase_start

            process_telegram_command_jobs(exchange, telegram_token)

            user_alert_phase_start = time.perf_counter()
            check_user_level_alerts(exchange, telegram_token)
            user_alert_seconds = time.perf_counter() - user_alert_phase_start

            active_trade_phase_start = time.perf_counter()
            monitor_active_trades(exchange, telegram_token, telegram_chat_id, state)
            active_trade_seconds = time.perf_counter() - active_trade_phase_start

            log_info(
                format_loop_phase_benchmark(
                    command_seconds,
                    scan_seconds,
                    user_alert_seconds,
                    active_trade_seconds,
                )
            )

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
