import importlib.util
import json
import os
import re
import tempfile
import unittest
from unittest.mock import ANY, patch
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCANNER_PATH = PROJECT_DIR / "crypto_alert_scanner.py"

spec = importlib.util.spec_from_file_location("crypto_alert_scanner", SCANNER_PATH)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)

import prb_card_renderer


class FakeTelegramResponse:
    status_code = 200
    text = "OK"


class FakeTelegramSession:
    def __init__(self, posted):
        self.posted = posted

    def post(self, url, **kwargs):
        self.posted.append((url, kwargs))
        return FakeTelegramResponse()


class FakeCoingeckoResponse:
    status_code = 200
    text = "OK"

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class FakeCoingeckoSession:
    def __init__(self, payload):
        self.payload = payload
        self.gets = []

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return FakeCoingeckoResponse(self.payload)


def candle(timestamp, open_price, high, low, close, volume):
    return [timestamp, open_price, high, low, close, volume]


def make_tracking_candles(closes, volumes=None, start=1_800_000_000_000):
    if volumes is None:
        volumes = [100 for _ in closes]

    candles = []
    for index, close in enumerate(closes):
        open_price = closes[index - 1] if index else close
        high = max(open_price, close) + 0.5
        low = min(open_price, close) - 0.5
        candles.append(candle(start + index * 60_000, open_price, high, low, close, volumes[index]))

    forming = candles[-1][:]
    forming[0] += 60_000
    candles.append(forming)
    return candles


def make_ohlcv_series(closes, start=1_700_000_000_000, step=900_000, volume=100):
    candles = []
    for index, close in enumerate(closes):
        open_price = closes[index - 1] if index else close
        high = max(open_price, close) + 1
        low = min(open_price, close) - 1
        candles.append(candle(start + index * step, open_price, high, low, close, volume))
    return candles


def scan_result_for_alerts(alerts=None, current_close=101, current_volume=250, current_timestamp=None):
    alerts = alerts or []
    current_timestamp = scanner.TIMEFRAME_MS if current_timestamp is None else current_timestamp
    previous_candle = candle(current_timestamp - scanner.TIMEFRAME_MS, 99, 101, 98, 100, 100)
    current_candle = candle(current_timestamp, 100, 102, 99, current_close, current_volume)
    signal_state = {
        "alerts": alerts,
        "scorecard": [],
        "ema_21": 101,
        "ema_55": 99,
        "rsi": 55,
        "volume_average": 100,
        "volume_multiple": current_volume / 100,
    }
    return scanner.ScanSymbolResult(
        previous_candle=previous_candle,
        candle=current_candle,
        alerts=alerts,
        ema_21=101,
        ema_55=99,
        current_rsi=55,
        current_atr_14=1,
        volume_avg=100,
        range_low=90,
        range_high=110,
        closed_candles=[previous_candle, current_candle],
        key_levels={"support": [90], "resistance": [110]},
        signal_state=signal_state,
    )


def confirmed_break_alert(direction="breakout", level=100):
    return {
        "type": f"live:{direction}:{level}:confirmation",
        "label": "Breakout Confirmation" if direction == "breakout" else "Breakdown Confirmation",
        "emoji": "✅",
        "level": level,
    }


def severity_confirmed_break_alert(direction="breakout", level=100, ema_trend=None, volume_multiple=1.0):
    alert = confirmed_break_alert(direction=direction, level=level)
    trade_direction = "LONG" if direction == "breakout" else "SHORT"
    alert["trade_plan"] = {
        "direction": trade_direction,
        "classification": "Confirmed zone break",
        "confidence_score": 80,
        "break_strength_score": 80,
        "setup_quality": "B",
        "setup_status": "Building",
        "trade_quality": "Watchlist",
        "level": level,
        "first_close": level + 1 if direction == "breakout" else level - 1,
        "confirmation_close": level + 2 if direction == "breakout" else level - 2,
        "ema_trend": ema_trend or "Neutral EMA trend, not aligned",
        "ema_21": 101 if direction == "breakout" else 99,
        "ema_55": 99 if direction == "breakout" else 101,
        "volume_multiple": volume_multiple,
        "volume_status": "Elevated volume" if volume_multiple >= 2 else "Normal volume",
        "rsi": 58 if direction == "breakout" else 42,
        "rsi_trend": "Aligned bullish" if direction == "breakout" else "Aligned bearish",
        "retest_quality": "Needs follow-through",
    }
    alert["location_filter"] = {
        "label": "Middle Range",
        "range_low": 90,
        "range_high": 110,
        "room_to_target": "Good",
        "location_quality": "B",
        "next_target": 110 if direction == "breakout" else 90,
        "distance_to_target_pct": 5.0,
    }
    return alert


def secondary_timeframe_context_for_bias(bias):
    if bias == "bullish":
        return {scanner.MIDDLE_TIMEFRAME: {"latest_close": 105, "ema_21": 103, "ema_55": 100, "rsi_14": 55}}
    if bias == "bearish":
        return {scanner.MIDDLE_TIMEFRAME: {"latest_close": 95, "ema_21": 97, "ema_55": 100, "rsi_14": 45}}
    return {scanner.MIDDLE_TIMEFRAME: {"latest_close": 100, "ema_21": 100, "ema_55": 100, "rsi_14": 50}}


class FakeExchange:
    def __init__(self, candles_by_timeframe, ticker_price, failing_timeframes=None):
        self.candles_by_timeframe = candles_by_timeframe
        self.ticker_price = ticker_price
        self.failing_timeframes = set(failing_timeframes or [])

    def fetch_ohlcv(self, symbol, timeframe, limit):
        if timeframe in self.failing_timeframes:
            raise RuntimeError(f"{timeframe} unavailable")
        return self.candles_by_timeframe[timeframe][-limit:]

    def fetch_ticker(self, symbol):
        return {"last": self.ticker_price}


class ScannerLogicTests(unittest.TestCase):
    def load_scanner_with_data_dir(self, data_dir=None):
        env = {} if data_dir is None else {"POINKLE_DATA_DIR": str(data_dir)}
        with patch.dict(os.environ, env, clear=True):
            module_name = f"crypto_alert_scanner_data_dir_test_{id(data_dir)}"
            spec = importlib.util.spec_from_file_location(module_name, SCANNER_PATH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module

    def live_explain_snapshot(self, current_price=110):
        candles = [
            {
                "time": 1_700_000_000_000 + index * scanner.TIMEFRAME_MS,
                "open": 100 + index,
                "high": 103 + index,
                "low": 98 + index,
                "close": 101 + index,
                "volume": 1000 + index,
            }
            for index in range(8)
        ]
        return {
            "current_price": current_price,
            "support_zones": [(95, 100)],
            "resistance_zones": [(120, 125)],
            "chart_data": {
                "candles": candles,
                "current_price": current_price,
                "supports": [97.5],
                "resistances": [122.5],
                "ema21": [105 for _ in candles],
                "ema55": [103 for _ in candles],
                "ema200": None,
                "price_source": "ticker",
                "last_updated_label": "as of 9:30 AM ET",
            },
        }

    def setUp(self):
        self.original_test_mode = scanner.TEST_MODE
        self.original_key_levels = scanner.KEY_LEVELS.copy()
        self.original_unsupported_symbols = scanner.UNSUPPORTED_SYMBOLS_THIS_SESSION.copy()
        self.original_live_alert_test_chat_id = scanner.LIVE_ALERT_TEST_CHAT_ID
        self.original_last_research_chart_data = scanner.LAST_RESEARCH_CHART_DATA.copy()
        self.original_mike_alternate_exchange = scanner.MIKE_ALTERNATE_EXCHANGE
        self.original_kraken_exchange = scanner.KRAKEN_EXCHANGE
        self.original_diagnostics_file = scanner.DIAGNOSTICS_FILE
        self.diagnostics_tmpdir = tempfile.TemporaryDirectory()
        scanner.TEST_MODE = False
        scanner.KEY_LEVELS = {
            "BTC/USD": {"support": [95], "resistance": [100]},
        }
        scanner.UNSUPPORTED_SYMBOLS_THIS_SESSION.clear()
        scanner.LIVE_ALERT_TEST_CHAT_ID = ""
        scanner.LAST_RESEARCH_CHART_DATA.clear()
        scanner.MIKE_ALTERNATE_EXCHANGE = None
        scanner.KRAKEN_EXCHANGE = None
        scanner.DIAGNOSTICS_FILE = Path(self.diagnostics_tmpdir.name) / "diagnostics" / "alert_diagnostics.jsonl"

    def tearDown(self):
        scanner.TEST_MODE = self.original_test_mode
        scanner.KEY_LEVELS = self.original_key_levels
        scanner.UNSUPPORTED_SYMBOLS_THIS_SESSION.clear()
        scanner.UNSUPPORTED_SYMBOLS_THIS_SESSION.update(self.original_unsupported_symbols)
        scanner.LIVE_ALERT_TEST_CHAT_ID = self.original_live_alert_test_chat_id
        scanner.LAST_RESEARCH_CHART_DATA.clear()
        scanner.LAST_RESEARCH_CHART_DATA.update(self.original_last_research_chart_data)
        scanner.MIKE_ALTERNATE_EXCHANGE = self.original_mike_alternate_exchange
        scanner.KRAKEN_EXCHANGE = self.original_kraken_exchange
        scanner.DIAGNOSTICS_FILE = self.original_diagnostics_file
        self.diagnostics_tmpdir.cleanup()

    def test_resample_candles_combines_four_one_hour_candles(self):
        candles = [
            candle(1_700_000_000_000, 100, 105, 98, 102, 10),
            candle(1_700_003_600_000, 102, 108, 101, 107, 20),
            candle(1_700_007_200_000, 107, 109, 99, 101, 30),
            candle(1_700_010_800_000, 101, 104, 97, 103, 40),
        ]

        resampled = scanner.resample_candles(candles, 4)

        self.assertEqual(
            resampled,
            [[1_700_000_000_000, 100, 109, 97, 103, 100]],
        )

    def test_resample_candles_combines_eight_one_hour_candles(self):
        candles = [
            candle(1_700_000_000_000 + index * 3_600_000, 100 + index, 102 + index, 99 + index, 101 + index, 10 + index)
            for index in range(8)
        ]

        resampled = scanner.resample_candles(candles, 8)

        self.assertEqual(
            resampled,
            [[1_700_000_000_000, 100, 109, 99, 108, 108]],
        )

    def test_brett_is_enabled_in_main_watchlist(self):
        self.assertIn("BRETT/USD", scanner.WATCHLIST)

    def test_mike_list_message_uses_only_price_trend_and_rsi(self):
        self.assertEqual(
            scanner.MIKES_LIST,
            [
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
            ],
        )

        def fake_snapshot(exchange, symbol):
            if symbol == "JCT/USD":
                raise scanner.MarketDataError("JCT/USD: unsupported exchange pair")
            return {
                "current_price": 1.2345,
                "bias": "Bullish",
                "rsi": 57.891,
                "support_zones": [{"low": 1.0, "high": 1.1}],
                "resistance_zones": [{"low": 1.8, "high": 2.0}],
                "market_score": 77,
            }

        with patch.object(scanner, "build_mike_symbol_snapshot", side_effect=fake_snapshot):
            rows = scanner.build_mike_list_rows(exchange=object())
            message = scanner.build_mike_list_message_from_rows(rows)

        self.assertEqual([row["symbol"] for row in rows], [symbol.replace("/USD", "") for symbol in scanner.MIKES_LIST])
        self.assertEqual(len(rows), 10)
        self.assertEqual(len(message.splitlines()), 10)
        self.assertIn("BRETT: Price 1.2345 | Trend bullish | RSI 57.89", message)
        self.assertIn("JCT: Price market data unavailable | Trend n/a | RSI n/a", message)
        self.assertNotIn("support_zones", message.lower())
        self.assertNotIn("resistance", message.lower())
        self.assertNotIn("market score", message.lower())
        for row in rows:
            self.assertEqual(set(row), {"symbol", "price", "trend", "rsi", "available"})

    def test_mike_alternate_symbols_use_kucoin_snapshot_path(self):
        class FakeKuCoin:
            def __init__(self):
                self.loaded = False

            def load_markets(self):
                self.loaded = True
                return {"BRETT/USDT": {}, "JCT/USDT": {}}

        primary_exchange = object()
        kucoin_exchange = FakeKuCoin()
        calls = []

        def fake_snapshot(exchange, symbol):
            calls.append((exchange, symbol))
            return {
                "current_price": 2.5 if symbol == "BRETT/USDT" else 0.42,
                "bias": "Bearish" if symbol == "BRETT/USDT" else "Bullish",
                "rsi": 44.321 if symbol == "BRETT/USDT" else 61.987,
            }

        with patch.object(scanner, "MIKES_LIST", ["BRETT/USD", "JCT/USD"]), patch.object(
            scanner, "mike_alternate_exchange", return_value=kucoin_exchange
        ), patch.object(scanner, "build_levels_scan_snapshot", side_effect=fake_snapshot):
            rows = scanner.build_mike_list_rows(primary_exchange)

        self.assertTrue(kucoin_exchange.loaded)
        self.assertEqual(calls, [(kucoin_exchange, "BRETT/USDT"), (kucoin_exchange, "JCT/USDT")])
        self.assertEqual(
            rows,
            [
                {"symbol": "BRETT", "price": "2.5", "trend": "bearish", "rsi": "44.32", "available": True},
                {"symbol": "JCT", "price": "0.42", "trend": "bullish", "rsi": "61.99", "available": True},
            ],
        )

    def test_fetch_swing_ohlcv_allows_valid_native_coinbase_timeframe(self):
        class FakeCoinbase:
            timeframes = {"1d": "ONE_DAY", "6h": "SIX_HOUR", "2h": "TWO_HOUR"}

            def __init__(self):
                self.calls = []

            def fetch_ohlcv(self, symbol, timeframe, limit):
                self.calls.append((symbol, timeframe, limit))
                return [["candle"]]

        exchange = FakeCoinbase()
        candles = scanner.fetch_swing_ohlcv(exchange, "BTC/USD", scanner.MIDDLE_TIMEFRAME, 120)

        self.assertEqual(candles, [["candle"]])
        self.assertEqual(exchange.calls, [("BTC/USD", "6h", 120)])

    def test_fetch_swing_ohlcv_rejects_invalid_coinbase_timeframe(self):
        class FakeCoinbase:
            timeframes = {"1d": "ONE_DAY", "6h": "SIX_HOUR", "2h": "TWO_HOUR"}

            def fetch_ohlcv(self, symbol, timeframe, limit):
                raise AssertionError("fetch_ohlcv should not be called")

        with self.assertRaisesRegex(ValueError, "coinbase does not support timeframe 4h"):
            scanner.fetch_swing_ohlcv(FakeCoinbase(), "BTC/USD", "4h", 120)

    def test_fetch_swing_ohlcv_clamps_limit_to_three_hundred(self):
        warnings = []

        class FakeCoinbase:
            timeframes = {"1d": "ONE_DAY", "6h": "SIX_HOUR", "2h": "TWO_HOUR"}

            def __init__(self):
                self.calls = []

            def fetch_ohlcv(self, symbol, timeframe, limit):
                self.calls.append((symbol, timeframe, limit))
                return [["candle"]]

        exchange = FakeCoinbase()
        with patch.object(
            scanner, "log_warn", side_effect=lambda message: warnings.append(message)
        ):
            candles = scanner.fetch_swing_ohlcv(exchange, "BTC/USD", scanner.ENTRY_TIMEFRAME, 500)

        self.assertEqual(candles, [["candle"]])
        self.assertEqual(exchange.calls, [("BTC/USD", "2h", 300)])
        self.assertEqual(len(warnings), 1)
        self.assertIn("clamping swing OHLCV limit to 300", warnings[0])

    def test_kraken_exchange_returns_cached_object_without_raising(self):
        created = []

        class FakeKraken:
            def __init__(self, config):
                self.config = config

        class FakeCcxt:
            def kraken(self, config):
                exchange = FakeKraken(config)
                created.append(exchange)
                return exchange

        with patch.object(scanner, "ccxt", FakeCcxt()):
            first = scanner.kraken_exchange()
            second = scanner.kraken_exchange()

        self.assertIs(first, second)
        self.assertEqual(len(created), 1)
        self.assertEqual(first.config, {"enableRateLimit": True})

    def test_resolve_data_source_returns_kraken_for_fallback_symbol(self):
        self.assertEqual(scanner.resolve_data_source("XMR/USD"), "kraken")

    def test_resolve_data_source_returns_coinbase_for_normal_symbol(self):
        self.assertEqual(scanner.resolve_data_source("BTC/USD"), "coinbase")

    def test_resolve_data_source_is_case_insensitive(self):
        self.assertEqual(scanner.resolve_data_source("xmr/usd"), "kraken")

    def test_resolve_data_source_leaves_kucoin_only_symbol_on_coinbase_for_now(self):
        self.assertEqual(scanner.resolve_data_source("ROSE/USD"), "coinbase")

    def test_fetch_kraken_ohlcv_returns_none_on_fetch_failure(self):
        warnings = []

        class FakeKraken:
            def fetch_ohlcv(self, symbol, timeframe, limit):
                self.last_call = (symbol, timeframe, limit)
                raise RuntimeError("Kraken unavailable")

        exchange = FakeKraken()
        with patch.object(scanner, "kraken_exchange", return_value=exchange), patch.object(
            scanner,
            "log_warn",
            side_effect=lambda message: warnings.append(message),
        ):
            result = scanner.fetch_kraken_ohlcv("XMR/USD", timeframe="1h", limit=100)

        self.assertIsNone(result)
        self.assertEqual(exchange.last_call, ("XMR/USD", "1h", 100))
        self.assertEqual(len(warnings), 1)
        self.assertIn("Kraken candle fetch failed", warnings[0])

    def test_secondary_timeframe_context_returns_six_hour_indicators(self):
        closes = [100 + index * 0.5 for index in range(scanner.CANDLE_LIMIT)]
        six_hour_candles = make_ohlcv_series(closes, step=21_600_000, volume=100)

        class RecordingCoinbase:
            timeframes = {"1d": "ONE_DAY", "6h": "SIX_HOUR", "2h": "TWO_HOUR"}

            def __init__(self):
                self.calls = []

            def fetch_ohlcv(self, symbol, timeframe, limit):
                self.calls.append((symbol, timeframe, limit))
                return six_hour_candles[-limit:]

        exchange = RecordingCoinbase()
        context = scanner.get_secondary_timeframe_context(exchange, "BTC/USD")

        self.assertEqual(
            exchange.calls,
            [("BTC/USD", scanner.MIDDLE_TIMEFRAME, scanner.CANDLE_LIMIT)],
        )
        self.assertEqual(set(context), {"6h"})
        self.assertEqual(context["6h"]["candle_count"], 119)
        self.assertEqual(context["6h"]["latest_close"], six_hour_candles[118][4])
        self.assertAlmostEqual(context["6h"]["volume_multiple"], 1.0)
        self.assertIn("ema_21", context["6h"])
        self.assertIn("ema_55", context["6h"])
        self.assertIn("rsi_14", context["6h"])

    def test_secondary_timeframe_context_uses_kraken_for_kraken_symbol(self):
        six_hour_candles = make_ohlcv_series(
            [100 + index * 0.5 for index in range(scanner.CANDLE_LIMIT)],
            step=21_600_000,
            volume=100,
        )

        class FailingCoinbase:
            timeframes = {"1d": "ONE_DAY", "6h": "SIX_HOUR", "2h": "TWO_HOUR"}

            def fetch_ohlcv(self, symbol, timeframe, limit):
                raise AssertionError("Coinbase fetch should not be used")

        class FakeKraken:
            timeframes = {"1d": "1440", "6h": "360", "2h": "120"}

            def __init__(self):
                self.calls = []

            def fetch_ohlcv(self, symbol, timeframe, limit):
                self.calls.append((symbol, timeframe, limit))
                return six_hour_candles[-limit:]

        kraken = FakeKraken()
        with patch.object(scanner, "kraken_exchange", return_value=kraken):
            context = scanner.get_secondary_timeframe_context(FailingCoinbase(), "XMR/USD")

        self.assertEqual(kraken.calls, [("XMR/USD", scanner.MIDDLE_TIMEFRAME, scanner.CANDLE_LIMIT)])
        self.assertEqual(set(context), {"6h"})

    def test_secondary_timeframe_context_returns_none_on_fetch_failure(self):
        class FailingCoinbase:
            timeframes = {"1d": "ONE_DAY", "6h": "SIX_HOUR", "2h": "TWO_HOUR"}

            def fetch_ohlcv(self, symbol, timeframe, limit):
                raise RuntimeError("6h unavailable")

        with patch.object(scanner, "throttled_log_warn") as warn:
            context = scanner.get_secondary_timeframe_context(FailingCoinbase(), "BTC/USD")

        self.assertIsNone(context)
        warn.assert_called_once()

    def test_scan_symbol_uses_kraken_fetch_for_resolved_kraken_symbol(self):
        candles = make_ohlcv_series([100 + index for index in range(120)])

        class FailingCoinbase:
            def fetch_ohlcv(self, symbol, timeframe, limit):
                raise AssertionError("Coinbase fetch should not be used")

        with patch.object(scanner, "fetch_kraken_ohlcv", return_value=candles) as kraken_fetch:
            result = scanner.scan_symbol(FailingCoinbase(), "XMR/USD")

        kraken_fetch.assert_called_once_with(
            "XMR/USD",
            timeframe=scanner.TIMEFRAME,
            limit=scanner.CANDLE_LIMIT,
        )
        self.assertEqual(result[1], candles[-2])

    def test_scan_symbol_keeps_coinbase_fetch_for_resolved_coinbase_symbol(self):
        candles = make_ohlcv_series([100 + index for index in range(120)])

        class RecordingCoinbase:
            def __init__(self):
                self.calls = []

            def fetch_ohlcv(self, symbol, timeframe, limit):
                self.calls.append((symbol, timeframe, limit))
                return candles[-limit:]

        exchange = RecordingCoinbase()
        with patch.object(
            scanner,
            "fetch_kraken_ohlcv",
            side_effect=AssertionError("Kraken fetch should not be used"),
        ):
            result = scanner.scan_symbol(exchange, "BTC/USD")

        self.assertEqual(exchange.calls, [("BTC/USD", scanner.TIMEFRAME, scanner.CANDLE_LIMIT)])
        self.assertEqual(result[1], candles[-2])

    def test_scan_symbol_result_fields_are_accessible_by_name(self):
        candles = make_ohlcv_series([100 + index for index in range(120)])

        class RecordingCoinbase:
            def fetch_ohlcv(self, symbol, timeframe, limit):
                return candles[-limit:]

        result = scanner.scan_symbol(RecordingCoinbase(), "BTC/USD")

        self.assertIsInstance(result, scanner.ScanSymbolResult)
        self.assertEqual(result.previous_candle, result[0])
        self.assertEqual(result.candle, result[1])
        self.assertEqual(result.alerts, result[2])
        self.assertEqual(result.ema_21, result[3])
        self.assertEqual(result.ema_55, result[4])
        self.assertEqual(result.current_rsi, result[5])
        self.assertEqual(result.current_atr_14, result[6])
        self.assertEqual(result.volume_avg, result[7])
        self.assertEqual(result.range_low, result[8])
        self.assertEqual(result.range_high, result[9])
        self.assertEqual(result.closed_candles, result[10])
        self.assertEqual(result.key_levels, result[11])
        self.assertEqual(result.signal_state, result[12])

    def test_get_current_market_price_uses_kraken_ticker_for_resolved_kraken_symbol(self):
        class FailingCoinbase:
            def fetch_ticker(self, symbol):
                raise AssertionError("Coinbase ticker should not be used")

        class RecordingKraken:
            def __init__(self):
                self.calls = []

            def fetch_ticker(self, symbol):
                self.calls.append(symbol)
                return {"last": 172.25}

        kraken = RecordingKraken()
        with patch.object(scanner, "kraken_exchange", return_value=kraken):
            price = scanner.get_current_market_price(FailingCoinbase(), "XMR/USD", 100)

        self.assertEqual(price, 172.25)
        self.assertEqual(kraken.calls, ["XMR/USD"])

    def test_get_current_market_price_keeps_coinbase_ticker_for_resolved_coinbase_symbol(self):
        class RecordingCoinbase:
            def __init__(self):
                self.calls = []

            def fetch_ticker(self, symbol):
                self.calls.append(symbol)
                return {"last": 101.5}

        exchange = RecordingCoinbase()
        with patch.object(
            scanner,
            "kraken_exchange",
            side_effect=AssertionError("Kraken ticker should not be used"),
        ):
            price = scanner.get_current_market_price(exchange, "BTC/USD", 100)

        self.assertEqual(price, 101.5)
        self.assertEqual(exchange.calls, ["BTC/USD"])

    def test_get_current_market_price_falls_back_on_kraken_ticker_failure(self):
        warnings = []

        class FailingCoinbase:
            def fetch_ticker(self, symbol):
                raise AssertionError("Coinbase ticker should not be used")

        class FailingKraken:
            def fetch_ticker(self, symbol):
                raise RuntimeError("ticker unavailable")

        with patch.object(scanner, "kraken_exchange", return_value=FailingKraken()), patch.object(
            scanner,
            "throttled_log_warn",
            side_effect=lambda symbol, key, message: warnings.append((symbol, key, message)),
        ):
            price = scanner.get_current_market_price(FailingCoinbase(), "XMR/USD", 99.25)

        self.assertEqual(price, 99.25)
        self.assertEqual(warnings, [("XMR/USD", "ticker", "XMR/USD: Kraken ticker fetch failed. Using fallback price.")])

    def test_mike_card_renders_mike_knows_branding_and_watermark(self):
        centered_text = []
        watermarks = []

        def capture_centered_text(pixels, width, height, y, text, **kwargs):
            centered_text.append(text)

        def capture_watermark(pixels, watermark_path=None, opacity=None, **kwargs):
            watermarks.append((watermark_path, opacity))
            return True

        rows = [
            {
                "symbol": "BRETT",
                "price": "2.5",
                "trend": "bullish",
                "rsi": "61.00",
                "available": True,
            }
        ]

        with tempfile.TemporaryDirectory() as output_dir, patch.object(
            prb_card_renderer,
            "draw_centered_text",
            side_effect=capture_centered_text,
        ), patch.object(
            prb_card_renderer,
            "draw_ghost_watermark",
            side_effect=capture_watermark,
        ), patch.object(prb_card_renderer, "write_png"):
            prb_card_renderer.render_mike_list_card(rows, output_dir=output_dir)

        self.assertIn("THE INNER CIRCLE", centered_text)
        self.assertIn("MIKE KNOWS", centered_text)
        self.assertIn("MIKE'S CURATED LIST", centered_text)
        self.assertIn((prb_card_renderer.MIKE_WATERMARK_PATH, prb_card_renderer.MIKE_WATERMARK_OPACITY), watermarks)

    def test_mike_card_keeps_poinkle_header_logo(self):
        rows = [
            {
                "symbol": "BRETT",
                "price": "2.5",
                "trend": "bullish",
                "rsi": "61.00",
                "available": True,
            }
        ]

        with patch.object(scanner, "render_mike_list_card", return_value="/tmp/mike.png") as render_card, patch.object(
            scanner, "send_telegram_photo", return_value=True
        ):
            sent = scanner.send_mike_list_card("TOKEN", "999", rows, "caption")

        self.assertTrue(sent)
        render_card.assert_called_once_with(rows, logo_path=scanner.POINKLE_RESEARCH_EMBLEM_PATH)

    def test_mike_card_list_rows_use_larger_legible_spacing(self):
        draw_calls = []

        def capture_draw_text(pixels, width, height, x, y, text, **kwargs):
            draw_calls.append({"x": x, "y": y, "text": text, "scale": kwargs.get("scale")})

        rows = [
            {"symbol": "JASMY", "price": "0.0123", "trend": "bullish", "rsi": "57.89", "available": True},
            {"symbol": "ICP", "price": "6.12", "trend": "neutral", "rsi": "51.44", "available": True},
        ]

        with tempfile.TemporaryDirectory() as output_dir, patch.object(
            prb_card_renderer, "draw_text", side_effect=capture_draw_text
        ), patch.object(prb_card_renderer, "write_png"):
            prb_card_renderer.render_mike_list_card(rows, output_dir=output_dir)

        symbol_rows = [call for call in draw_calls if call["text"] in {"JASMY", "ICP"}]
        self.assertEqual([call["scale"] for call in symbol_rows], [prb_card_renderer.MIKE_TABLE_SCALE] * 2)
        self.assertEqual(symbol_rows[1]["y"] - symbol_rows[0]["y"], prb_card_renderer.MIKE_TABLE_ROW_GAP)
        self.assertGreater(prb_card_renderer.MIKE_TABLE_SCALE, prb_card_renderer.SMALL_SCALE)
        self.assertEqual(symbol_rows[0]["x"], 76 + prb_card_renderer.MIKE_TABLE_X_OFFSET)

    def test_breakout_attempt_uses_closed_candle_and_range_context(self):
        symbol_state = {}
        previous_candle = candle(0, 98, 100, 97, 99, 100)
        current_candle = candle(scanner.TIMEFRAME_MS, 99, 103, 98, 102, 140)

        alerts = scanner.build_level_alerts(
            "BTC/USD",
            previous_candle,
            current_candle,
            symbol_state,
            atr_14=1.5,
            current_market_price=102,
            range_low=90,
            range_high=110,
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["label"], "Breakout Attempt")
        self.assertEqual(alerts[0]["range_context"]["range_low"], 90)
        self.assertEqual(alerts[0]["range_context"]["range_high"], 110)
        self.assertIn("next_target", alerts[0]["range_context"])
        self.assertIn("distance_to_target_pct", alerts[0]["range_context"])
        self.assertEqual(alerts[0]["setup_quality"], "A")
        self.assertEqual(alerts[0]["setup_status"], "High Interest Setup")
        self.assertIn("break_strength_score", alerts[0])
        self.assertEqual(len(symbol_state["pending_setups"]), 1)
        pending_setup = next(iter(symbol_state["pending_setups"].values()))
        self.assertEqual(pending_setup["setup_quality"], "A")

        duplicate_alerts = scanner.build_level_alerts(
            "BTC/USD",
            previous_candle,
            current_candle,
            symbol_state,
            atr_14=1.5,
            current_market_price=102,
            range_low=90,
            range_high=110,
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
        )
        self.assertEqual(duplicate_alerts, [])

    def test_early_warning_marks_poor_location_as_watch_only(self):
        symbol_state = {}
        previous_candle = candle(0, 98, 100, 97, 99, 100)
        current_candle = candle(scanner.TIMEFRAME_MS, 99, 103, 98, 102.5, 220)

        alerts = scanner.build_level_alerts(
            "BTC/USD",
            previous_candle,
            current_candle,
            symbol_state,
            atr_14=1.0,
            current_market_price=102.5,
            range_low=90,
            range_high=103,
            ema_21=101,
            ema_55=99,
            current_rsi=60,
            volume_avg=100,
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["label"], "Breakout Attempt")
        self.assertEqual(alerts[0]["range_context"]["range_position"], "Upper Range")
        self.assertEqual(alerts[0]["setup_quality"], "D")
        self.assertEqual(alerts[0]["setup_status"], "Weak Setup / Avoid Chasing")
        self.assertIn("Weak setup", alerts[0]["warning"])

    def test_upper_range_confirmation_rejects_chasey_setup_even_with_large_body(self):
        current_timestamp = scanner.TIMEFRAME_MS * 2
        symbol_state = {
            "pending_setups": {
                "live:breakout:100": {
                    "direction": "breakout",
                    "level": 100,
                    "first_candle": scanner.TIMEFRAME_MS,
                    "first_candle_open": 99,
                    "first_candle_high": 101,
                    "first_candle_low": 98,
                    "first_candle_close": 100.5,
                    "first_candle_volume": 180,
                    "expected_confirmation_candle": current_timestamp,
                }
            }
        }
        confirmation_candle = candle(current_timestamp, 99.5, 101.0, 99.4, 100.6, 300)

        alerts = scanner.build_level_alerts(
            "BTC/USD",
            candle(scanner.TIMEFRAME_MS, 99, 101, 98, 100.5, 180),
            confirmation_candle,
            symbol_state,
            atr_14=1.0,
            current_market_price=100.6,
            range_low=90,
            range_high=100.4,
            ema_21=100,
            ema_55=99,
            current_rsi=60,
            volume_avg=100,
            candle_series=[
                candle(index * scanner.TIMEFRAME_MS, 100, 100.5, 99.5, 100, 100)
                for index in range(15)
            ],
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["label"], "Weak Break / Watch Only")
        self.assertLess(alerts[0]["trade_plan"]["break_strength_score"], 70)
        self.assertEqual(alerts[0]["trade_plan"]["setup_quality"], "D")
        self.assertEqual(symbol_state["pending_setups"], {})

    def test_weak_confirmation_rejects_trade_plan(self):
        current_timestamp = scanner.TIMEFRAME_MS * 2
        symbol_state = {
            "pending_setups": {
                "live:breakout:100": {
                    "direction": "breakout",
                    "level": 100,
                    "first_candle": scanner.TIMEFRAME_MS,
                    "first_candle_open": 99,
                    "first_candle_high": 101,
                    "first_candle_low": 98,
                    "first_candle_close": 100.6,
                    "first_candle_volume": 80,
                    "expected_confirmation_candle": current_timestamp,
                }
            }
        }
        confirmation_candle = candle(current_timestamp, 100.4, 101.0, 100.2, 100.6, 50)

        alerts = scanner.build_level_alerts(
            "BTC/USD",
            candle(scanner.TIMEFRAME_MS, 99, 101, 98, 100.6, 80),
            confirmation_candle,
            symbol_state,
            atr_14=2.0,
            current_market_price=100.6,
            range_low=90,
            range_high=110,
            ema_21=101,
            ema_55=100,
            current_rsi=48,
            volume_avg=100,
            candle_series=make_ohlcv_series([100 for _ in range(14)] + [100.6], step=scanner.TIMEFRAME_MS),
        )

        self.assertEqual(len(alerts), 1)
        self.assertIn(alerts[0]["label"], {"Weak Break / Watch Only", "Failed Follow-Through"})
        self.assertNotEqual(alerts[0]["label"], "Breakout Confirmation")
        self.assertLess(alerts[0].get("trade_plan", alerts[0])["break_strength_score"], 70)

    def test_breakout_confirmation_requires_body_at_least_one_atr(self):
        location_filter = {"range_position": "Upper Range"}
        atr_candles = [
            candle(index * scanner.TIMEFRAME_MS, 100, 101, 99, 100, 100)
            for index in range(15)
        ]

        weak_body = candle(15 * scanner.TIMEFRAME_MS, 100, 101, 99, 101.5, 100)
        strong_body = candle(15 * scanner.TIMEFRAME_MS, 100, 102, 99, 102, 100)

        self.assertFalse(
            scanner.breakout_confirmation_quality_met(weak_body, location_filter, atr_candles)
        )
        self.assertTrue(
            scanner.breakout_confirmation_quality_met(strong_body, location_filter, atr_candles)
        )

    def test_breakout_confirmation_returns_false_when_atr_candles_are_insufficient(self):
        location_filter = {"range_position": "Upper Range"}
        short_candle_series = [
            candle(0, 100, 101, 99, 100, 100),
            candle(scanner.TIMEFRAME_MS, 100, 102, 99, 102, 100),
        ]

        self.assertFalse(
            scanner.breakout_confirmation_quality_met(
                short_candle_series[-1],
                location_filter,
                short_candle_series,
            )
        )

    def test_dedupe_price_levels_drops_invalid_sorts_and_merges_nearby_levels(self):
        self.assertEqual(
            scanner.dedupe_price_levels([105.0, -1.0, 100.3, 0.0, 100.0], 100.0),
            [100.0, 105.0],
        )

    def test_daily_support_resistance_levels_uses_daily_swing_levels(self):
        candles = [
            candle(index * scanner.TIMEFRAME_MS, 100, 102, 98, 100, 100)
            for index in range(20)
        ]
        candles[4][3] = 90
        candles[7][2] = 110
        candles[12][3] = 95
        candles[15][2] = 106

        levels = scanner.daily_support_resistance_levels(candles, current_price=100)

        self.assertEqual(levels["support"], [95, 90])
        self.assertEqual(levels["resistance"], [106, 110])
        self.assertLessEqual(len(levels["support"]), scanner.SR_MAX_LEVELS_PER_SIDE)
        self.assertLessEqual(len(levels["resistance"]), scanner.SR_MAX_LEVELS_PER_SIDE)

    def test_alert_dedupe_key_buckets_nearby_level_alerts(self):
        first = {"type": "live:breakout:100.0:confirmation"}
        nearby = {"type": "live:breakout:100.2:confirmation"}
        different = {"type": "live:breakout:105.0:confirmation"}

        self.assertEqual(
            scanner.alert_dedupe_key(first, 100),
            scanner.alert_dedupe_key(nearby, 100),
        )
        self.assertNotEqual(
            scanner.alert_dedupe_key(first, 100),
            scanner.alert_dedupe_key(different, 100),
        )

    def test_alert_dedupe_key_leaves_non_level_alerts_unchanged(self):
        self.assertEqual(
            scanner.alert_dedupe_key({"type": "volume_spike"}, 100),
            "volume_spike",
        )

    def test_alert_dedupe_key_handles_malformed_level_alerts(self):
        malformed = "live:breakout:not-a-number:confirmation"

        self.assertEqual(
            scanner.alert_dedupe_key({"type": malformed}, 100),
            malformed,
        )

    def test_trend_gate_only_allows_bullish_downtrend_alerts_deep_in_support(self):
        bullish_alert = {"type": "volume_spike", "direction": "bullish"}

        self.assertFalse(
            scanner.should_send_telegram_alert(
                bullish_alert,
                [bullish_alert],
                ema_21=90,
                ema_55=100,
                current_price=110,
                range_low=90,
                range_high=120,
            )
        )
        self.assertTrue(
            scanner.should_send_telegram_alert(
                bullish_alert,
                [bullish_alert],
                ema_21=90,
                ema_55=100,
                current_price=99,
                range_low=90,
                range_high=120,
            )
        )

    def test_level_break_send_filter_only_allows_confirmations(self):
        self.assertFalse(
            scanner.should_send_level_break_alert(
                {"type": "live:breakout:100:early_warning", "label": "Breakout Attempt"}
            )
        )
        self.assertFalse(
            scanner.should_send_level_break_alert(
                {"type": "live:breakdown:95:weak_break", "label": "Weak Break / Watch Only"}
            )
        )
        self.assertTrue(
            scanner.should_send_level_break_alert(
                {"type": "live:breakout:100:confirmation", "label": "Breakout Confirmation"}
            )
        )
        self.assertTrue(
            scanner.should_send_level_break_alert(
                {"type": "volume_spike", "label": "Bullish Volume Spike"}
            )
        )

    def test_tracking_rejects_fake_breakout(self):
        closes = [101 + index * 0.05 for index in range(80)]
        closes[60] = 99.4
        volumes = [100 for _ in closes]
        volumes[-1] = 150
        candles = make_tracking_candles(closes, volumes)
        trade = {
            "direction": "LONG",
            "level": 100,
            "started_at": candles[61][0],
            "last_rsi": 55,
            "last_volume": 100,
            "retest_seen": False,
            "lower_tf_candles_checked": 0,
            "distance_to_target_pct": 2,
            "next_target": 105,
        }

        status, reason, metrics = scanner.evaluate_active_trade(trade, candles[-2][4], candles)

        self.assertEqual(status, "Failed Breakout")
        self.assertIn("Trade invalidated by reclaim", reason)
        self.assertIn("closed back below", reason)
        self.assertGreaterEqual(metrics["lower_tf_candles_checked"], 1)
        self.assertIn("setup_quality", metrics)
        self.assertLessEqual(metrics["break_strength_score"], 25)
        self.assertEqual(metrics["setup_quality"], "F")
        self.assertEqual(metrics["setup_status"], "Weak Setup / Avoid Chasing")

    def test_volume_alert_title_and_wording_are_awareness_only(self):
        message = scanner.build_alert(
            "BTC/USD",
            candle(0, 100, 105, 99, 104, 250),
            {
                "type": "volume_spike",
                "label": "Bullish Volume Spike",
                "emoji": "🟢",
                "direction": "bullish",
                "volume_multiple": 2.5,
            },
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
        )

        self.assertIn("🟢 <b>BTC/USD Bullish Volume Spike</b>", message)
        self.assertIn("<b>Timeframe:</b> Daily  |  Candle Close Time:", message)
        self.assertIn("<b>Price:</b> 104  (<b>Body:</b> 4.00%)", message)
        self.assertIn("<b>Volume:</b> 2.50x average", message)
        self.assertIn("<b>RSI:</b> 58.00 —", message)
        self.assertIn("<b>EMA21:</b> 101  <b>EMA55:</b> 99", message)
        self.assertIn("High volume detected. Watch for breakout confirmation.", message)
        self.assertNotIn("<b>Open:</b>", message)
        self.assertNotIn("<b>20-candle average:</b>", message)
        self.assertNotIn("Strong buyer participation detected.", message)

    def test_alert_text_includes_secondary_timeframe_context_when_attached(self):
        message = scanner.build_alert(
            "BTC/USD",
            candle(0, 100, 105, 99, 104, 250),
            {
                "type": "volume_spike",
                "label": "Bullish Volume Spike",
                "emoji": "🟢",
                "direction": "bullish",
                "volume_multiple": 2.5,
                "secondary_timeframe_context": {
                    "6h": {"latest_close": 110, "ema_21": 105, "ema_55": 100, "rsi_14": 58},
                },
            },
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
        )

        self.assertIn(
            "<b>6h Context:</b> 6h bullish (RSI 58)",
            message,
        )

    def test_volume_spike_direction_comes_from_candle_body_not_indicators(self):
        candles = make_ohlcv_series([100 for _ in range(80)], volume=100)
        candles[-1] = candle(candles[-1][0], 98.5, 100.0, 98.0, 99.5, 250)

        signal_state = scanner.evaluate_lightweight_signal_state(candles[:-1], candles)
        volume_alert = next(alert for alert in signal_state["alerts"] if alert["type"] == "volume_spike")

        self.assertEqual(volume_alert["direction"], "bullish")
        self.assertEqual(volume_alert["label"], "Volume Spike on an Up Candle")
        self.assertIsNone(scanner.lightweight_alert_direction(volume_alert))

    def test_volume_spike_doji_is_neutral(self):
        candles = make_ohlcv_series([100 for _ in range(80)], volume=100)
        candles[-1] = candle(candles[-1][0], 99.0, 100.0, 98.0, 99.0, 250)

        signal_state = scanner.evaluate_lightweight_signal_state(candles[:-1], candles)
        volume_alert = next(alert for alert in signal_state["alerts"] if alert["type"] == "volume_spike")

        self.assertEqual(volume_alert["direction"], "neutral")
        self.assertEqual(volume_alert["label"], "Volume Spike — Indecision Candle")
        self.assertIsNone(scanner.lightweight_alert_direction(volume_alert))

    def test_rsi_extremes_are_directionless_readings(self):
        self.assertIsNone(scanner.lightweight_alert_direction({"type": "rsi_cross_above_70"}))
        self.assertIsNone(scanner.lightweight_alert_direction({"type": "rsi_cross_below_30"}))

    def test_whynot_command_message_accepts_current_scan_symbol_shape(self):
        candles = make_ohlcv_series([100 for _ in range(80)], volume=100)
        candles[-1] = candle(candles[-1][0], 98.5, 100.0, 98.0, 99.5, 250)
        signal_state = scanner.evaluate_lightweight_signal_state(candles[:-1], candles)

        scan_result = scanner.ScanSymbolResult(
            previous_candle=candles[-2],
            candle=candles[-1],
            alerts=signal_state["alerts"],
            ema_21=signal_state["ema_21"],
            ema_55=signal_state["ema_55"],
            current_rsi=signal_state["rsi"],
            current_atr_14=1.0,
            volume_avg=signal_state["volume_average"],
            range_low=90.0,
            range_high=110.0,
            closed_candles=candles,
            key_levels={"support": [90.0], "resistance": [110.0]},
            signal_state=signal_state,
        )

        with patch.object(scanner, "scan_symbol", return_value=scan_result):
            message = scanner.build_whynot_command_message(object(), "BTC/USD")

        self.assertIn("<b>BTC/USD - Why not?</b>", message)
        self.assertIn("Current lightweight signal state:", message)

    def whynot_scan_result(self, current_price=100.0):
        signal_state = {
            "alerts": [],
            "scorecard": [
                {"type": "volume_spike", "state": "fail", "reason": "0.8x, no spike"},
                {"type": "ema_cross_above", "state": "fail", "reason": "EMA 21 below EMA 55; no fresh bullish cross"},
                {"type": "ema_cross_below", "state": "fail", "reason": "EMA 21 below EMA 55; no fresh bearish cross"},
                {"type": "rsi_cross_above_70", "state": "fail", "reason": "RSI 52; below 70"},
                {"type": "rsi_cross_below_30", "state": "fail", "reason": "RSI 52; above 30"},
            ],
            "volume_multiple": 0.8,
        }
        previous_candle = candle(1_700_000_000_000, 99.0, 101.0, 98.0, 99.0, 100)
        current_candle = candle(1_700_086_400_000, 99.0, 102.0, 94.0, current_price, 100)
        return scanner.ScanSymbolResult(
            previous_candle=previous_candle,
            candle=current_candle,
            alerts=signal_state["alerts"],
            ema_21=101.0,
            ema_55=103.0,
            current_rsi=52.0,
            current_atr_14=1.0,
            volume_avg=100.0,
            range_low=80.0,
            range_high=120.0,
            closed_candles=[previous_candle, current_candle],
            key_levels={"support": [95.0], "resistance": [110.0]},
            signal_state=signal_state,
        )

    def test_whynot_and_run_once_use_named_scan_result_access(self):
        scan_result = self.whynot_scan_result()

        with patch.object(scanner, "scan_symbol", return_value=scan_result):
            scorecard = scanner.evaluate_whynot_scorecard(object(), "BTC/USD", state={})

        self.assertEqual(scorecard["candle"], scan_result.candle)
        self.assertEqual(scorecard["scorecard"], scan_result.signal_state["scorecard"])

        class NamedOnlyScanResult:
            def __init__(self, result):
                self.__dict__.update(result._asdict())

            def __getitem__(self, key):
                raise AssertionError("run_once should use named scan result fields")

            def __len__(self):
                raise AssertionError("run_once should not inspect scan result length")

            def __iter__(self):
                raise AssertionError("run_once should not unpack scan result positionally")

        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        try:
            with patch.object(scanner, "scan_symbol", return_value=NamedOnlyScanResult(scan_result)), patch.object(
                scanner, "get_current_market_price", return_value=scan_result.candle[4]
            ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                scanner, "load_bot_config", return_value={"live_alerts_enabled": True}
            ), patch.object(scanner, "save_state"):
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", {})
        finally:
            scanner.WATCHLIST = original_watchlist

    def test_whynot_zone_state_renders_pending_setup_direction(self):
        state = {
            "BTC/USD": {
                "pending_setups": {
                    "live:breakdown:95.0": {
                        "level": 95.0,
                        "direction": "breakdown",
                    }
                }
            }
        }

        with patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()):
            message = scanner.build_whynot_command_message(object(), "BTC/USD", state=state)

        self.assertIn("<b>ZONE STATE</b>", message)
        self.assertIn("BTC/USD closed below the 95.00 zone once.", message)
        self.assertIn("It needs a SECOND daily close below to confirm.", message)
        self.assertIn("One close is an attempt. Two consecutive closes is confirmation.", message)

    def test_whynot_zone_state_renders_nearest_zones_without_pending_setup(self):
        with patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()):
            message = scanner.build_whynot_command_message(object(), "BTC/USD", state={})

        self.assertIn("<b>ZONE STATE</b>", message)
        self.assertIn("Nearest support: around 95.00 (5.0% below)", message)
        self.assertIn("Nearest resistance: around 110.00 (10.0% above)", message)
        self.assertIn("Price isn't at a zone. There's nothing to confirm yet.", message)

    def test_whynot_zone_state_renders_without_state(self):
        with patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()):
            message = scanner.build_whynot_command_message(object(), "BTC/USD", state=None)

        self.assertIn("<b>ZONE STATE</b>", message)
        self.assertIn("Nearest support: around 95.00 (5.0% below)", message)
        self.assertIn("Price isn't at a zone. There's nothing to confirm yet.", message)

    def test_whatnow_opens_with_refusal(self):
        with patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()):
            message = scanner.build_whatnow_command_message(object(), "BTC/USD", state={})

        self.assertTrue(message.startswith("<b>I can't make that decision for you.</b>"))

    def test_whatnow_card_avoids_action_language(self):
        with patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()):
            message = scanner.build_whatnow_command_message(object(), "BTC/USD", state={})

        for forbidden_word in ("buy", "sell", "enter", "exit", "long", "short", "target"):
            self.assertNotRegex(message.lower(), rf"\b{forbidden_word}\b")

    def test_whatnow_shows_nearest_zones_with_distances(self):
        with patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()):
            message = scanner.build_whatnow_command_message(object(), "BTC/USD", state={})

        self.assertIn("Nearest support: 95.00  (5.0% below)", message)
        self.assertIn("Nearest resistance: 110.00  (10.0% above)", message)
        self.assertNotIn("95.00 - 95.00", message)
        self.assertNotIn("110.00 - 110.00", message)

    def test_whatnow_names_two_close_rule_and_honest_limit(self):
        with patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()):
            message = scanner.build_whatnow_command_message(object(), "BTC/USD", state={})

        self.assertIn("Two consecutive daily closes below 95.00 - or above 110.00.", message)
        self.assertIn("One close is an attempt; two is confirmation.", message)
        self.assertTrue(
            message.endswith(
                "Honest limit: zones break. Confirmation can fail. This describes right now, not what comes next."
            )
        )

    def test_whatnow_renders_pending_setup_when_present(self):
        state = {
            "BTC/USD": {
                "pending_setups": {
                    "live:breakdown:95.0": {
                        "level": 95.0,
                        "direction": "breakdown",
                    }
                }
            }
        }

        with patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()):
            message = scanner.build_whatnow_command_message(object(), "BTC/USD", state=state)

        self.assertIn(
            "<b>BTC closed below the 95.00 zone once. That's an attempt, not confirmation.</b>",
            message,
        )

    def test_whynot_still_renders_rsi_extreme_reading(self):
        signal_state = self.whynot_scan_result().signal_state.copy()
        signal_state["scorecard"] = [
            {"type": "volume_spike", "state": "fail", "reason": "0.8x, no spike"},
            {"type": "ema_cross_above", "state": "fail", "reason": "EMA 21 below EMA 55; no fresh bullish cross"},
            {"type": "ema_cross_below", "state": "fail", "reason": "EMA 21 below EMA 55; no fresh bearish cross"},
            {"type": "rsi_cross_above_70", "state": "pass", "reason": "RSI 72.0"},
            {"type": "rsi_cross_below_30", "state": "fail", "reason": "RSI 72.0; no cross below 30"},
        ]
        scan_result = self.whynot_scan_result()._replace(signal_state=signal_state)

        with patch.object(scanner, "scan_symbol", return_value=scan_result):
            message = scanner.build_whynot_command_message(object(), "BTC/USD", state={})

        self.assertIn("RSI extreme", message)
        self.assertIn("above 70; RSI 72.0", message)

    def pending_breakdown_state(self, expected_candle=2_000, first_candle=1_000):
        return {
            "pending_setups": {
                "live:breakdown:95.0": {
                    "direction": "breakdown",
                    "level": 95.0,
                    "first_candle": first_candle,
                    "first_candle_open": 97.0,
                    "first_candle_high": 98.0,
                    "first_candle_low": 94.0,
                    "first_candle_close": 94.5,
                    "first_candle_volume": 100,
                    "expected_confirmation_candle": expected_candle,
                    "setup_quality": "B",
                    "setup_status": "Watch",
                    "break_strength_score": 72,
                }
            }
        }

    def build_level_alerts_for_pending_state(self, symbol_state, current_close, current_timestamp=2_000):
        previous_candle = candle(1_000, 97.0, 98.0, 94.0, 94.5, 100)
        current_candle = candle(current_timestamp, 94.5, 97.0, 94.0, current_close, 100)
        return scanner.build_level_alerts(
            "BTC/USD",
            previous_candle,
            current_candle,
            symbol_state,
            1.0,
            current_close,
            80.0,
            120.0,
            101.0,
            103.0,
            52.0,
            100.0,
            candle_series=[previous_candle, current_candle],
            key_levels={"support": [], "resistance": []},
        )

    def test_failed_level_attempt_records_only_path_b_failure(self):
        symbol_state = self.pending_breakdown_state()

        self.build_level_alerts_for_pending_state(symbol_state, current_close=96.0)

        self.assertEqual(
            symbol_state["failed_level_attempts"],
            [
                {
                    "direction": "breakdown",
                    "level": 95.0,
                    "first_close": 94.5,
                    "first_candle": 1_000,
                    "failed_close": 96.0,
                    "failed_candle": 2_000,
                }
            ],
        )

    def test_expired_pending_setup_does_not_record_failed_attempt(self):
        symbol_state = self.pending_breakdown_state(expected_candle=1_500)

        self.build_level_alerts_for_pending_state(symbol_state, current_close=96.0, current_timestamp=2_000)

        self.assertNotIn("failed_level_attempts", symbol_state)

    def test_confirmed_break_does_not_record_failed_attempt(self):
        symbol_state = self.pending_breakdown_state()
        trade_plan = {
            "setup_quality": "B",
            "failed_follow_through": False,
            "break_strength_score": 80,
            "weak_volume": False,
        }
        location_filter = {
            "allowed": True,
            "location_quality": "A",
            "room_to_target": "Open",
        }

        with (
            patch.object(scanner, "get_location_filter", return_value=location_filter),
            patch.object(scanner, "build_trade_plan", return_value=trade_plan),
        ):
            self.build_level_alerts_for_pending_state(symbol_state, current_close=94.0)

        self.assertNotIn("failed_level_attempts", symbol_state)

    def test_failed_level_attempts_trim_to_last_three(self):
        symbol_state = self.pending_breakdown_state()
        symbol_state["failed_level_attempts"] = [
            {"failed_candle": 10, "level": 91.0},
            {"failed_candle": 20, "level": 92.0},
            {"failed_candle": 30, "level": 93.0},
        ]

        self.build_level_alerts_for_pending_state(symbol_state, current_close=96.0)

        self.assertEqual([attempt["level"] for attempt in symbol_state["failed_level_attempts"]], [92.0, 93.0, 95.0])

    def test_whynot_renders_recent_failed_level_attempt(self):
        failed_candle = 1_700_086_400_000
        state = {
            "BTC/USD": {
                "failed_level_attempts": [
                    {
                        "direction": "breakdown",
                        "level": 95.0,
                        "first_close": 94.5,
                        "first_candle": failed_candle - scanner.TIMEFRAME_MS,
                        "failed_close": 96.0,
                        "failed_candle": failed_candle,
                    }
                ]
            }
        }

        with (
            patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()),
            patch.object(scanner, "current_time_ms", return_value=failed_candle + scanner.TIMEFRAME_MS),
        ):
            message = scanner.build_whynot_command_message(object(), "BTC/USD", state=state)

        self.assertIn("Last attempt: BTC/USD closed below the 95.00 zone", message)
        self.assertIn("then failed to confirm the next day", message)
        self.assertIn("Two consecutive closes is confirmation", message)

    def test_whynot_omits_old_failed_level_attempt(self):
        failed_candle = 1_700_086_400_000
        state = {
            "BTC/USD": {
                "failed_level_attempts": [
                    {
                        "direction": "breakdown",
                        "level": 95.0,
                        "first_close": 94.5,
                        "first_candle": failed_candle - scanner.TIMEFRAME_MS,
                        "failed_close": 96.0,
                        "failed_candle": failed_candle,
                    }
                ]
            }
        }

        with (
            patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()),
            patch.object(scanner, "current_time_ms", return_value=failed_candle + scanner.FAILED_LEVEL_ATTEMPT_TTL_MS + 1),
        ):
            message = scanner.build_whynot_command_message(object(), "BTC/USD", state=state)

        self.assertNotIn("Last attempt:", message)

    def confirmed_level_alert(self, direction="breakdown", level=95.0):
        label = "Breakdown Confirmation" if direction == "breakdown" else "Breakout Confirmation"
        return {
            "type": f"live:{direction}:{level}:confirmation",
            "label": label,
            "level": level,
        }

    def test_confirmed_breakdown_records_level_break_followup(self):
        state = {}
        current_candle = candle(2_000, 96.0, 97.0, 94.0, 94.0, 100)

        followup = scanner.record_level_break_followup(
            state,
            "BTC/USD",
            current_candle,
            self.confirmed_level_alert("breakdown", 95.0),
            "999",
            now=int(scanner.time.time()),
        )

        self.assertIsNotNone(followup)
        self.assertEqual(followup["kind"], "level_break")
        self.assertEqual(followup["direction"], "breakdown")
        self.assertEqual(followup["level"], 95.0)
        self.assertEqual(followup["destination_chat_id"], "999")

    def test_confirmed_breakout_records_level_break_followup(self):
        state = {}
        current_candle = candle(2_000, 104.0, 107.0, 103.0, 106.0, 100)

        followup = scanner.record_level_break_followup(
            state,
            "BTC/USD",
            current_candle,
            self.confirmed_level_alert("breakout", 105.0),
            "999",
            now=int(scanner.time.time()),
        )

        self.assertIsNotNone(followup)
        self.assertEqual(followup["kind"], "level_break")
        self.assertEqual(followup["direction"], "breakout")
        self.assertEqual(followup["level"], 105.0)

    def test_mixed_group_records_lightweight_and_level_break_followups(self):
        state = {}
        current_candle = candle(2_000, 96.0, 97.0, 94.0, 94.0, 100)
        signal_state = {
            "ema_21": 101.0,
            "ema_55": 103.0,
            "rsi": 52.0,
            "volume_multiple": 2.4,
        }
        alert_group = [
            {"type": "volume_spike", "label": "Volume Spike", "direction": "bearish"},
            self.confirmed_level_alert("breakdown", 95.0),
        ]

        recorded = scanner.record_post_send_followups(
            state,
            "BTC/USD",
            current_candle,
            alert_group,
            ["999"],
            signal_state,
            sent_at=int(scanner.time.time()),
        )

        self.assertTrue(recorded)
        followups = scanner.signal_followups(state)
        self.assertEqual(len(followups), 2)
        self.assertEqual(
            sorted(followup.get("kind", "lightweight") for followup in followups.values()),
            ["level_break", "lightweight"],
        )

    def test_level_break_breakdown_that_holds_stays_open_and_sends_nothing(self):
        state = {}
        sent_messages = []
        scanner.record_level_break_followup(
            state,
            "BTC/USD",
            candle(2_000, 96.0, 97.0, 94.0, 94.0, 100),
            self.confirmed_level_alert("breakdown", 95.0),
            "999",
            now=int(scanner.time.time()),
        )

        with patch.object(scanner, "send_telegram_message", side_effect=lambda *args: sent_messages.append(args)):
            changed = scanner.process_signal_followups_for_symbol(
                state,
                "TOKEN",
                "BTC/USD",
                "3_000",
                {},
                candle=candle(3_000, 94.0, 95.0, 93.0, 94.5, 100),
            )

        self.assertFalse(changed)
        self.assertEqual(sent_messages, [])
        self.assertEqual(len(scanner.signal_followups(state)), 1)

    def test_level_break_breakdown_reclaim_sends_fade_note(self):
        state = {}
        sent_messages = []
        scanner.record_level_break_followup(
            state,
            "BTC/USD",
            candle(2_000, 96.0, 97.0, 94.0, 94.0, 100),
            self.confirmed_level_alert("breakdown", 95.0),
            "999",
            now=int(scanner.time.time()),
        )

        with patch.object(scanner, "send_telegram_message", side_effect=lambda token, chat_id, text: sent_messages.append((chat_id, text))):
            changed = scanner.process_signal_followups_for_symbol(
                state,
                "TOKEN",
                "BTC/USD",
                "3_000",
                {},
                candle=candle(3_000, 94.0, 96.5, 93.5, 96.0, 100),
            )

        self.assertTrue(changed)
        self.assertEqual(len(scanner.signal_followups(state)), 0)
        self.assertEqual(sent_messages[0][0], "999")
        self.assertIn("price closed back ABOVE the 95.00 zone", sent_messages[0][1])
        self.assertIn("The breakdown was reclaimed", sent_messages[0][1])

    def test_level_break_breakout_reclaim_sends_fade_note(self):
        state = {}
        sent_messages = []
        scanner.record_level_break_followup(
            state,
            "BTC/USD",
            candle(2_000, 104.0, 107.0, 103.0, 106.0, 100),
            self.confirmed_level_alert("breakout", 105.0),
            "999",
            now=int(scanner.time.time()),
        )

        with patch.object(scanner, "send_telegram_message", side_effect=lambda token, chat_id, text: sent_messages.append((chat_id, text))):
            changed = scanner.process_signal_followups_for_symbol(
                state,
                "TOKEN",
                "BTC/USD",
                "3_000",
                {},
                candle=candle(3_000, 106.0, 106.5, 103.5, 104.0, 100),
            )

        self.assertTrue(changed)
        self.assertEqual(len(scanner.signal_followups(state)), 0)
        self.assertIn("price closed back BELOW the 105.00 zone", sent_messages[0][1])
        self.assertIn("The breakout was reclaimed", sent_messages[0][1])

    def test_lightweight_only_followups_keep_one_check_behavior(self):
        state = {}
        sent_messages = []
        current_candle = candle(2_000, 100.0, 102.0, 99.0, 101.0, 100)
        signal_state = {
            "ema_21": 101.0,
            "ema_55": 103.0,
            "rsi": 52.0,
            "volume_multiple": 2.4,
        }
        alert_group = [{"type": "volume_spike", "label": "Volume Spike", "direction": "bullish"}]

        scanner.record_post_send_followups(
            state,
            "BTC/USD",
            current_candle,
            alert_group,
            ["999"],
            signal_state,
            sent_at=int(scanner.time.time()),
        )

        with patch.object(scanner, "send_telegram_message", side_effect=lambda *args: sent_messages.append(args)):
            changed = scanner.process_signal_followups_for_symbol(
                state,
                "TOKEN",
                "BTC/USD",
                "3_000",
                {"volume_multiple": 2.5},
                candle=candle(3_000, 101.0, 103.0, 100.0, 102.0, 100),
            )

        self.assertTrue(changed)
        self.assertEqual(sent_messages, [])
        self.assertEqual(scanner.signal_followups(state), {})

    def test_telegram_sends_html_parse_mode_for_messages_and_photos(self):
        posted = []
        with tempfile.NamedTemporaryFile() as photo, patch.object(
            scanner, "TELEGRAM_HTTP_SESSION", FakeTelegramSession(posted)
        ):
            scanner.send_telegram_message("TOKEN", "999", "<b>Hello</b>")
            self.assertTrue(scanner.send_telegram_photo("TOKEN", "999", photo.name, caption="<b>Card</b>"))

        self.assertEqual(posted[0][1]["json"]["parse_mode"], "HTML")
        self.assertEqual(posted[0][1]["json"]["disable_web_page_preview"], True)
        self.assertEqual(posted[1][1]["data"]["parse_mode"], "HTML")

    def test_telegram_media_group_uses_multipart_attachments(self):
        posted = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "TELEGRAM_HTTP_SESSION", FakeTelegramSession(posted)
        ):
            first = Path(tmpdir) / "first.png"
            second = Path(tmpdir) / "second.png"
            first.write_bytes(b"one")
            second.write_bytes(b"two")

            self.assertTrue(scanner.send_telegram_media_group("TOKEN", "999", [first, second]))

        url, kwargs = posted[0]
        media = json.loads(kwargs["data"]["media"])
        self.assertTrue(url.endswith("/sendMediaGroup"))
        self.assertEqual(kwargs["data"]["chat_id"], "999")
        self.assertEqual(
            media,
            [
                {"type": "photo", "media": "attach://photo0"},
                {"type": "photo", "media": "attach://photo1"},
            ],
        )
        self.assertEqual(sorted(kwargs["files"].keys()), ["photo0", "photo1"])

    def test_runtime_data_paths_default_to_project_dir_when_env_unset(self):
        module = self.load_scanner_with_data_dir()

        self.assertEqual(module.DATA_DIR, module.PROJECT_DIR)
        self.assertEqual(module.STATE_FILE, module.PROJECT_DIR / "scanner_state.json")
        self.assertEqual(module.USER_ALERTS_FILE, module.PROJECT_DIR / "user_alerts.json")
        self.assertEqual(module.USER_WATCHLISTS_FILE, module.PROJECT_DIR / "user_watchlists.json")
        self.assertEqual(module.USER_PROFILES_FILE, module.PROJECT_DIR / "user_profiles.json")
        self.assertEqual(module.CREATORS_FILE, module.PROJECT_DIR / "creators.json")
        self.assertEqual(module.BOT_CONFIG_FILE, module.PROJECT_DIR / "bot_config.json")
        self.assertEqual(module.DIAGNOSTICS_FILE, module.PROJECT_DIR / "diagnostics" / "alert_diagnostics.jsonl")

    def test_runtime_data_paths_follow_configured_data_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "poinkle-data"
            module = self.load_scanner_with_data_dir(data_dir)

            self.assertEqual(module.DATA_DIR, data_dir)
            self.assertTrue(data_dir.exists())
            self.assertEqual(module.STATE_FILE, data_dir / "scanner_state.json")
            self.assertEqual(module.USER_ALERTS_FILE, data_dir / "user_alerts.json")
            self.assertEqual(module.USER_WATCHLISTS_FILE, data_dir / "user_watchlists.json")
            self.assertEqual(module.USER_PROFILES_FILE, data_dir / "user_profiles.json")
            self.assertEqual(module.CREATORS_FILE, data_dir / "creators.json")
            self.assertEqual(module.BOT_CONFIG_FILE, data_dir / "bot_config.json")
            self.assertEqual(module.DIAGNOSTICS_FILE, data_dir / "diagnostics" / "alert_diagnostics.jsonl")

    def test_runtime_data_migration_copies_project_file_when_data_dir_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "project"
            data_dir = Path(tmpdir) / "data"
            project_dir.mkdir()
            data_dir.mkdir()
            (project_dir / "creators.json").write_text('{"mike_knows": {}}')

            with patch.object(scanner, "PROJECT_DIR", project_dir), patch.object(
                scanner, "DATA_DIR", data_dir
            ), patch.object(scanner, "RUNTIME_DATA_FILES", (("creators", "creators.json"),)):
                copied = scanner.migrate_runtime_data_files()

            self.assertEqual(copied, [str(data_dir / "creators.json")])
            self.assertEqual((data_dir / "creators.json").read_text(), '{"mike_knows": {}}')

    def test_runtime_data_migration_does_not_overwrite_existing_data_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "project"
            data_dir = Path(tmpdir) / "data"
            project_dir.mkdir()
            data_dir.mkdir()
            (project_dir / "creators.json").write_text('{"project": true}')
            (data_dir / "creators.json").write_text('{"data": true}')

            with patch.object(scanner, "PROJECT_DIR", project_dir), patch.object(
                scanner, "DATA_DIR", data_dir
            ), patch.object(scanner, "RUNTIME_DATA_FILES", (("creators", "creators.json"),)):
                copied = scanner.migrate_runtime_data_files()

            self.assertEqual(copied, [])
            self.assertEqual((data_dir / "creators.json").read_text(), '{"data": true}')

    def test_register_bot_commands_posts_public_command_list(self):
        posted = []
        with patch.object(scanner, "TELEGRAM_HTTP_SESSION", FakeTelegramSession(posted)):
            self.assertTrue(scanner.register_bot_commands("TOKEN"))

        url, kwargs = posted[0]
        command_names = [item["command"] for item in kwargs["json"]["commands"]]
        self.assertTrue(url.endswith("/setMyCommands"))
        self.assertEqual(
            command_names,
            [item["command"] for item in scanner.PUBLIC_BOT_COMMANDS],
        )
        self.assertIn("verify", command_names)
        for deleted_command in (
            "commands",
            "levels",
            "snap",
            "why",
            "learn",
            "watching",
            "reference",
            "guide",
            "coins",
            "clearwatch",
            "mywatch",
            "scan",
            "status",
        ):
            self.assertNotIn(deleted_command, command_names)
        self.assertNotIn("devmode", command_names)
        self.assertNotIn("maintenance", command_names)
        self.assertNotIn("livealerts", command_names)
        self.assertEqual(kwargs["timeout"], 20)

    def test_main_registers_bot_commands_at_startup(self):
        class FakeCcxt:
            @staticmethod
            def coinbase():
                return object()

        registered = []

        def stop_after_startup(_seconds):
            raise KeyboardInterrupt

        with patch.object(scanner, "load_dotenv"), patch.object(
            scanner.os,
            "getenv",
            side_effect=lambda key, default=None: {
                "TELEGRAM_BOT_TOKEN": "TOKEN",
                "TELEGRAM_CHAT_ID": "999",
                "LIVE_ALERT_TEST_CHAT_ID": "",
            }.get(key, default),
        ), patch.object(scanner, "ccxt", FakeCcxt), patch.object(
            scanner, "requests", object()
        ), patch.object(
            scanner, "validate_watchlist_against_exchange", return_value=(scanner.WATCHLIST, [])
        ), patch.object(
            scanner, "load_state", return_value={}
        ), patch.object(
            scanner, "save_state"
        ), patch.object(
            scanner, "send_status_update"
        ), patch.object(
            scanner, "count_enabled_user_alerts", return_value=0
        ), patch.object(
            scanner, "load_user_alerts", return_value={}
        ), patch.object(
            scanner,
            "register_bot_commands",
            side_effect=lambda token: registered.append(token) or True,
        ), patch.object(
            scanner, "process_telegram_commands"
        ), patch.object(
            scanner, "run_once"
        ), patch.object(
            scanner, "check_user_level_alerts"
        ), patch.object(
            scanner, "monitor_active_trades"
        ), patch.object(
            scanner.time, "sleep", side_effect=stop_after_startup
        ):
            scanner.main()

        self.assertEqual(registered, ["TOKEN"])

    def test_test_mode_defaults_to_false(self):
        loaded = self.load_scanner_with_data_dir()

        self.assertFalse(loaded.TEST_MODE)

    def test_test_mode_env_can_turn_it_on(self):
        with patch.dict(os.environ, {"POINKLE_TEST_MODE": "true"}, clear=True):
            module_name = f"crypto_alert_scanner_test_mode_on_{id(self)}"
            spec = importlib.util.spec_from_file_location(module_name, SCANNER_PATH)
            loaded = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loaded)

        self.assertTrue(loaded.TEST_MODE)

    def test_alert_text_omits_test_mode_banner_when_off(self):
        scanner.TEST_MODE = False

        message = scanner.build_alert(
            "BTC/USD",
            candle(0, 100, 105, 99, 104, 250),
            {
                "type": "volume_spike",
                "label": "Bullish Volume Spike",
                "emoji": "🟢",
                "direction": "bullish",
                "volume_multiple": 2.5,
            },
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
        )

        self.assertNotIn("TEST MODE", message)

    def test_status_shows_production_when_test_mode_off(self):
        scanner.TEST_MODE = False

        message = scanner.build_bot_status_message({"__bot_status": {"status": "Online"}})

        self.assertIn("Mode: PRODUCTION", message)
        self.assertNotIn("Mode: TEST", message)

    def test_pending_setup_keys_migrate_from_test_to_live(self):
        state = {
            "BTC/USD": {
                "pending_setups": {
                    "test:breakout:100": {"direction": "breakout", "level": 100},
                },
            },
        }

        result = scanner.migrate_pending_setup_mode_keys(state)

        self.assertEqual(result, {"migrated": 1, "dropped_duplicates": 0})
        self.assertNotIn("test:breakout:100", state["BTC/USD"]["pending_setups"])
        self.assertEqual(
            state["BTC/USD"]["pending_setups"]["live:breakout:100"],
            {"direction": "breakout", "level": 100},
        )

    def test_pending_setup_migration_does_not_overwrite_existing_live_key(self):
        state = {
            "BTC/USD": {
                "pending_setups": {
                    "test:breakout:100": {"direction": "breakout", "level": 100, "source": "old"},
                    "live:breakout:100": {"direction": "breakout", "level": 100, "source": "new"},
                },
            },
        }

        result = scanner.migrate_pending_setup_mode_keys(state)

        self.assertEqual(result, {"migrated": 0, "dropped_duplicates": 1})
        self.assertNotIn("test:breakout:100", state["BTC/USD"]["pending_setups"])
        self.assertEqual(state["BTC/USD"]["pending_setups"]["live:breakout:100"]["source"], "new")

    def test_live_scan_builds_level_alerts_with_computed_key_levels(self):
        source = (PROJECT_DIR / "crypto_alert_scanner.py").read_text()
        run_once_source = source[source.index("def run_once(") : source.index("def main():")]
        build_call = run_once_source[run_once_source.index("build_level_alerts(") : run_once_source.index(")\n                )", run_once_source.index("build_level_alerts("))]

        self.assertIn("key_levels=key_levels", build_call)

    def test_startup_ping_defaults_to_silent(self):
        with patch.object(
            scanner.os,
            "getenv",
            side_effect=lambda key, default=None: default if key == "POINKLE_STARTUP_PING" else None,
        ), patch.object(scanner, "send_status_update") as send_status:
            scanner.send_startup_status_update("TOKEN", {})

        send_status.assert_not_called()

    def test_startup_ping_owner_sends_only_to_owner_dm(self):
        with patch.object(
            scanner.os,
            "getenv",
            side_effect=lambda key, default=None: {
                "POINKLE_STARTUP_PING": "owner",
                "OWNER_ID": "OWNER_DM",
            }.get(key, default),
        ), patch.object(scanner, "send_status_update") as send_status:
            scanner.send_startup_status_update("TOKEN", {"__bot_status": {"status": "Online"}})

        send_status.assert_called_once_with("TOKEN", "OWNER_DM", {"__bot_status": {"status": "Online"}}, indicator="🟢")

    def test_startup_ping_never_targets_group_chat(self):
        with patch.object(
            scanner.os,
            "getenv",
            side_effect=lambda key, default=None: {
                "POINKLE_STARTUP_PING": "owner",
                "OWNER_ID": "OWNER_DM",
                "TELEGRAM_CHAT_ID": "GROUP_CHAT",
            }.get(key, default),
        ), patch.object(scanner, "send_status_update") as send_status:
            scanner.send_startup_status_update("TOKEN", {})

        sent_chat_ids = [call.args[1] for call in send_status.call_args_list]
        self.assertEqual(sent_chat_ids, ["OWNER_DM"])
        self.assertNotIn("GROUP_CHAT", sent_chat_ids)

    def test_mike_command_returns_creator_door_with_three_room_buttons(self):
        sent_messages = []

        with patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
        ), patch.object(scanner, "send_mike_list_card") as send_card:
            scanner.handle_mike_command(object(), "TOKEN", "999")

        send_card.assert_not_called()
        self.assertEqual(sent_messages[0][0], "999")
        self.assertIn("Welcome to Mike Knows' corner of Poinkle", sent_messages[0][1])
        self.assertIn("The Inner Circle", sent_messages[0][1])
        self.assertIn("Built for Mike Knows' Inner Circle. Powered by Poinkle.", sent_messages[0][1])
        buttons = [row[0] for row in sent_messages[0][2]["inline_keyboard"]]
        self.assertEqual(
            [button["text"] for button in buttons],
            [
                "✅ Is this really Mike?",
                "📚 Questions Mike Gets All The Time",
                "📈 Coins Mike Watches",
            ],
        )
        self.assertEqual(
            [button["callback_data"] for button in buttons],
            [
                "cdoor:mike_knows:verify",
                "cdoor:mike_knows:questions",
                "cdoor:mike_knows:coins",
            ],
        )

    def test_mike_coins_room_preserves_curated_symbols_and_reports_failures(self):
        sent_messages = []
        seen_symbols = []

        def fake_snapshot(_exchange, symbol):
            seen_symbols.append(symbol)
            if symbol == "NOTREAL/USD":
                raise scanner.MarketDataError("NOTREAL/USD: Unsupported Coinbase pair. Skipping.")
            return {
                "current_price": 100 + len(seen_symbols),
                "bias": "Bullish",
                "rsi": 55 + len(seen_symbols),
            }

        with patch.object(scanner, "MIKES_LIST", ["BTC/USD", "ETH/USD", "NOTREAL/USD"]), patch.object(
            scanner, "build_levels_scan_snapshot", side_effect=fake_snapshot
        ), patch.object(scanner, "answer_telegram_callback"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
        ), patch.object(scanner, "send_mike_list_card", return_value=False) as send_card:
            expected_keyboard = scanner.creator_watched_coins_keyboard(scanner.CREATOR_DOORS["mike_knows"])
            scanner.handle_creator_door_callback(
                "TOKEN",
                {
                    "id": "callback-1",
                    "message": {"chat": {"id": "999", "type": "private"}, "message_id": 44},
                    "from": {"id": 777},
                },
                "mike_knows:coins",
                exchange=object(),
            )

        self.assertEqual(seen_symbols, ["BTC/USD", "ETH/USD", "NOTREAL/USD"])
        self.assertEqual(send_card.call_args.kwargs["reply_markup"], expected_keyboard)
        self.assertEqual(sent_messages[0][0], "999")
        self.assertEqual(len(sent_messages[0][1].splitlines()), 3)
        self.assertEqual(sent_messages[0][2], expected_keyboard)
        self.assertIn("BTC: Price 101 | Trend bullish | RSI 56.00", sent_messages[0][1])
        self.assertIn("ETH: Price 102 | Trend bullish | RSI 57.00", sent_messages[0][1])
        self.assertIn("NOTREAL: Price market data unavailable | Trend n/a | RSI n/a", sent_messages[0][1])

    def test_mike_coins_room_includes_snapshot_buttons_for_each_coin(self):
        with patch.object(scanner, "MIKES_LIST", ["SOL/USD", "TAO/USD", "JCT/USD"]):
            keyboard = scanner.creator_watched_coins_keyboard(scanner.CREATOR_DOORS["mike_knows"])

        coin_buttons = [button for row in keyboard["inline_keyboard"][:-1] for button in row]
        self.assertEqual([button["text"] for button in coin_buttons], ["SOL", "TAO", "JCT"])
        self.assertEqual(
            [button["callback_data"] for button in coin_buttons],
            ["coinpick:snapshot:SOL", "coinpick:snapshot:TAO", "coinpick:snapshot:JCT"],
        )
        self.assertEqual(
            keyboard["inline_keyboard"][-1],
            [{"text": "⬅️ Back", "callback_data": "cdoor:mike_knows:open"}],
        )

    def test_mike_coin_button_routes_through_existing_snapshot_coinpick_path(self):
        with patch.object(scanner, "MIKES_LIST", ["SOL/USD"]):
            keyboard = scanner.creator_watched_coins_keyboard(scanner.CREATOR_DOORS["mike_knows"])
        callback_data = keyboard["inline_keyboard"][0][0]["callback_data"]
        callback_query = {
            "id": "callback-mike-sol",
            "data": callback_data,
            "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }

        with patch.object(scanner, "answer_telegram_callback"), patch.object(
            scanner, "clear_callback_message_keyboard"
        ), patch.object(scanner, "enqueue_telegram_command_job", return_value=True) as enqueue_job, patch.object(
            scanner, "send_heavy_job_acknowledgment"
        ) as send_ack:
            handled = scanner.handle_telegram_callback_query(object(), "TOKEN", callback_query)

        self.assertTrue(handled)
        enqueue_job.assert_called_once()
        self.assertEqual(enqueue_job.call_args.args[:3], ("snapshot", "777", "/snapshot SOL"))
        send_ack.assert_called_once()

    def test_mike_door_room_buttons_route_to_existing_handlers(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "tiktok", "handle": "@mikeknows.io"}],
                "registered_at": "2026-07-13",
            }
        }
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "999", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }

        with patch.object(scanner, "answer_telegram_callback"), patch.object(
            scanner, "load_creators", return_value=creators
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
        ):
            self.assertTrue(scanner.handle_creator_door_callback("TOKEN", callback_query, "mike_knows:verify", exchange=object()))
            self.assertTrue(scanner.handle_creator_door_callback("TOKEN", callback_query, "mike_knows:questions", exchange=object()))
            self.assertTrue(scanner.handle_creator_door_callback("TOKEN", callback_query, "mike_knows:support_resistance", exchange=object()))

        self.assertIn("✅ <b>VERIFIED</b>", sent_messages[0][1])
        self.assertIn("@mikeknows.io is <b>Mike Knows</b>' real TikTok.", sent_messages[0][1])

        question_keyboard = sent_messages[1][2]
        question_buttons = [row[0] for row in question_keyboard["inline_keyboard"][:-1]]
        self.assertEqual(
            [(button["text"], button["callback_data"]) for button in question_buttons],
            [
                ("Should I buy or sell?", "panel:whatnow"),
                ("Support & resistance", "cdoor:mike_knows:support_resistance"),
                ("Chart patterns", "xgroup:1"),
                ("BTC.D / USDT.D", "xconcept:dominance"),
                ("Real breakout or fakeout?", "panel:fakeout"),
            ],
        )
        self.assertIn("Mike brings the question. Poinkle teaches the concept.", sent_messages[1][1])
        self.assertEqual(sent_messages[2][2], scanner.creator_support_resistance_keyboard(scanner.CREATOR_DOORS["mike_knows"]))

    def test_mike_buy_sell_question_uses_whatnow_refusal_path(self):
        door_config = scanner.CREATOR_DOORS["mike_knows"]
        first_question = door_config["questions"][0]
        self.assertEqual(first_question["label"], "Should I buy or sell?")
        self.assertEqual(first_question["callback"], "panel:whatnow")

        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "999", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }
        with patch.object(scanner, "answer_telegram_callback"), patch.object(scanner, "send_target_coin_picker") as picker:
            handled = scanner.handle_panel_callback("TOKEN", callback_query, "whatnow", exchange=object())

        self.assertTrue(handled)
        picker.assert_called_once()
        self.assertEqual(picker.call_args.args[:3], ("TOKEN", "999", "whatnow"))

    def test_mike_door_text_has_no_creator_attributed_market_call_language(self):
        door_config = scanner.CREATOR_DOORS["mike_knows"]
        text = "\n".join(
            [
                scanner.creator_door_welcome_text(door_config),
                door_config["questions_intro"],
                "\n".join(door_config["room_labels"].values()),
                "\n".join(question["label"] for question in door_config["questions"]),
            ]
        ).lower()

        banned_phrases = (
            "mike's levels",
            "mike's signal",
            "mike's breakout",
            "mike is watching this right now",
            "mike says",
            "mike thinks",
            "mike expects",
        )
        for phrase in banned_phrases:
            self.assertNotIn(phrase, text)

    def test_mike_door_reads_labels_from_config(self):
        door_config = {
            "creator_key": "test_creator",
            "display_name": "Test Creator",
            "community": "Test Room",
            "branding_line": "Built for Test Room. Taught by Poinkle.",
            "welcome_title": "Welcome to Test Creator's corner",
            "room_labels": {
                "verify": "Verify Test",
                "questions": "Test Questions",
                "coins": "Test Coins",
            },
        }

        self.assertIn("Welcome to Test Creator's corner", scanner.creator_door_welcome_text(door_config))
        keyboard = scanner.creator_door_keyboard(door_config)
        self.assertEqual(
            [row[0]["text"] for row in keyboard["inline_keyboard"]],
            ["Verify Test", "Test Questions", "Test Coins"],
        )
        self.assertEqual(
            [row[0]["callback_data"] for row in keyboard["inline_keyboard"]],
            [
                "cdoor:test_creator:verify",
                "cdoor:test_creator:questions",
                "cdoor:test_creator:coins",
            ],
        )

    def test_lightweight_confluence_requires_two_distinct_directional_signal_types(self):
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }
        rsi_alert = {
            "type": "rsi_cross_above_70",
            "label": "RSI above 70 — extended",
            "emoji": "🔥",
        }

        self.assertFalse(scanner.has_lightweight_confluence([volume_alert]))
        self.assertFalse(scanner.has_lightweight_confluence([ema_alert]))
        self.assertFalse(scanner.has_lightweight_confluence([rsi_alert]))
        self.assertFalse(scanner.has_lightweight_confluence([volume_alert, volume_alert.copy()]))
        self.assertFalse(scanner.has_lightweight_confluence([volume_alert, ema_alert]))
        self.assertFalse(scanner.has_lightweight_confluence([ema_alert, rsi_alert]))
        self.assertEqual(scanner.lightweight_alert_direction(ema_alert), "bullish")
        self.assertIsNone(scanner.lightweight_alert_direction(rsi_alert))

    def test_volume_spike_returns_no_lightweight_direction(self):
        self.assertIsNone(
            scanner.lightweight_alert_direction(
                {
                    "type": "volume_spike",
                    "label": "Volume Spike on an Up Candle",
                    "direction": "bullish",
                    "volume_multiple": 2.5,
                }
            )
        )

    def test_tracking_failed_break_title_includes_symbol(self):
        trade = {"direction": "LONG", "level": 100}
        metrics = {
            "candle_timestamp": 0,
            "setup_quality": "F",
            "setup_status": "Weak Setup / Avoid Chasing",
            "break_strength_score": 25,
            "volume_status": "Below-average volume",
            "rsi_status": "Not aligned for long",
            "ema_trend": "Bearish EMA trend, not aligned",
            "next_target": 105,
            "price": 99,
            "rsi": 45,
            "rsi_direction": "falling",
            "volume_direction": "decreasing",
            "ema_alignment": "strongly opposed",
            "retest_status": "not yet",
        }

        message = scanner.build_trade_tracking_message(
            "AVAX/USD",
            trade,
            "Failed Breakout",
            "Trade invalidated by reclaim.",
            metrics,
        )

        self.assertIn("⚠️ AVAX/USD Failed Breakout", message)
        self.assertIn("Setup Quality:</b> F", message)

    def test_tracking_confirms_only_when_strength_is_high(self):
        closes = [101 + index * 0.12 for index in range(80)]
        volumes = [100 for _ in closes]
        volumes[-1] = 220
        candles = make_tracking_candles(closes, volumes)
        trade = {
            "direction": "LONG",
            "level": 100,
            "started_at": candles[76][0],
            "last_rsi": 50,
            "last_volume": 100,
            "retest_seen": True,
            "lower_tf_candles_checked": 0,
            "distance_to_target_pct": 2,
            "next_target": 115,
        }

        status, reason, metrics = scanner.evaluate_active_trade(trade, candles[-2][4], candles)

        self.assertEqual(status, "Trade Confirmed")
        self.assertGreaterEqual(metrics["break_strength_score"], 70)

    def test_monitor_active_trades_stays_disabled_when_tracking_telegram_is_off(self):
        class TrackingExchange:
            def __init__(self, candles):
                self.candles = candles

            def fetch_ohlcv(self, symbol, timeframe, limit):
                return self.candles[-limit:]

            def fetch_ticker(self, symbol):
                return {"last": self.candles[-2][4]}

        closes = [101 + index * 0.08 for index in range(80)]
        volumes = [100 for _ in closes]
        candles = make_tracking_candles(closes, volumes)
        state = {
            "__active_trades": {
                "BTC/USD": {
                    "direction": "LONG",
                    "level": 100,
                    "started_at": scanner.current_time_ms(),
                    "last_monitor_at": 0,
                    "last_status": None,
                    "last_rsi": 50,
                    "last_volume": 100,
                    "retest_seen": False,
                    "lower_tf_candles_checked": 0,
                    "distance_to_target_pct": 2,
                    "next_target": 115,
                }
            }
        }

        with patch.object(scanner, "TRADE_TRACKING_TELEGRAM_ENABLED", False), patch.object(
            scanner, "load_bot_config", return_value={"live_alerts_enabled": True}
        ), patch.object(
            scanner, "send_telegram_message", side_effect=AssertionError("tracking send should be muted")
        ), patch.object(scanner, "save_state") as save_state:
            scanner.monitor_active_trades(TrackingExchange(candles), "TOKEN", "MAIN_CHAT", state)

        trade = state["__active_trades"]["BTC/USD"]
        self.assertIsNone(trade["last_status"])
        self.assertEqual(trade["last_monitor_at"], 0)
        self.assertEqual(trade["last_rsi"], 50)
        self.assertEqual(trade["last_volume"], 100)
        save_state.assert_not_called()

    def test_levels_command_returns_market_levels_not_exact_key_levels(self):
        scanner.TEST_MODE = True
        scanner.KEY_LEVELS = {
            "BTC/USD": {"support": [99.9], "resistance": [100.1]},
        }
        fifteen_minute_closes = [95 + (index % 20) * 0.5 for index in range(119)] + [100]
        four_hour_closes = [90 + (index % 16) * 1.2 for index in range(179)] + [100]
        daily_closes = [82 + (index % 30) * 1.1 for index in range(179)] + [100]
        weekly_closes = [60 + (index % 18) * 3 for index in range(103)] + [100]
        fake_exchange = FakeExchange(
            {
                "15m": make_ohlcv_series(fifteen_minute_closes),
                "1h": make_ohlcv_series(four_hour_closes, step=3_600_000),
                "1d": make_ohlcv_series(daily_closes, step=86_400_000),
                "1w": make_ohlcv_series(weekly_closes, step=604_800_000),
            },
            ticker_price=100,
        )

        message = scanner.build_levels_command_message(fake_exchange, "BTC/USD")

        self.assertTrue(message.startswith("📍 POINKLE SNAPSHOT — BTC / USD"))
        self.assertIn("💰 PRICE\n100.00", message)
        self.assertIn("📈 TREND", message)
        self.assertIn("🎯 FOCUS", message)
        self.assertIn("⭐ MARKET SCORE", message)
        self.assertIn("🧠 SETUP GRADE", message)
        self.assertIn("📊 RSI", message)
        self.assertIn("👀 LOOK ORDER", message)
        self.assertIn("① Trend", message)
        self.assertIn("② Key Levels", message)
        self.assertIn("③ Liquidity", message)
        self.assertIn("④ Confirmation", message)
        self.assertIn("⑤ Decision", message)
        self.assertIn(scanner.poinkle_educational_footer(), message)
        self.assertNotIn("BTC/USD Market Levels", message)
        self.assertNotIn("Levels Engine v1.0", message)
        self.assertNotIn("Suggested plan", message)
        self.assertNotIn("Stop loss", message)
        self.assertNotIn("Risk/Reward To First Resistance", message)
        self.assertNotIn("99.9", message)

    def test_main_chat_safe_mode_suppresses_automatic_scanner_alerts(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        sent_alert_groups = []
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }
        scan_result = scan_result_for_alerts([confirmed_break_alert(), volume_alert, ema_alert], current_volume=200)

        try:
            with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(
                scanner, "build_level_alerts", side_effect=AssertionError("level alerts disabled")
            ), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda *args, **kwargs: sent_alert_groups.append(args),
            ), patch.object(
                scanner, "load_bot_config", return_value={"live_alerts_enabled": False}
            ), patch.object(scanner, "load_user_watchlists", return_value={}), patch.object(scanner, "save_state"):
                scanner.run_once(object(), "TOKEN", "999", {})
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(sent_alert_groups, [])

    def test_main_chat_safe_mode_routes_automatic_alerts_to_test_chat_when_configured(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        scanner.LIVE_ALERT_TEST_CHAT_ID = "TEST_CHAT"
        sent_alert_groups = []
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }
        scan_result = scan_result_for_alerts([confirmed_break_alert(), volume_alert, ema_alert], current_volume=200)

        try:
            with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(
                scanner, "build_level_alerts", side_effect=AssertionError("level alerts disabled")
            ), patch.object(
                scanner, "get_secondary_timeframe_context", return_value={"6h": {"latest_close": 101}}
            ), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, *args, **kwargs: sent_alert_groups.append((str(chat_id), args)),
            ), patch.object(
                scanner, "load_bot_config", return_value={"live_alerts_enabled": False}
            ), patch.object(scanner, "load_user_watchlists", return_value={}), patch.object(scanner, "save_state"):
                scanner.run_once(object(), "TOKEN", "999", {})
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(len(sent_alert_groups), 1)
        self.assertEqual(sent_alert_groups[0][0], "TEST_CHAT")
        self.assertEqual(sent_alert_groups[0][1][0], "BTC/USD")

    def test_tier2_confluence_scan_alert_cooldown_is_per_symbol(self):
        original_watchlist = scanner.WATCHLIST[:]
        sent_alert_groups = []
        call_counts = {"BTC/USD": 0, "ETH/USD": 0}
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }
        level_alert = confirmed_break_alert()

        def fake_scan_symbol(exchange, symbol):
            call_counts[symbol] += 1
            return scan_result_for_alerts([level_alert.copy(), volume_alert.copy(), ema_alert.copy()])

        state = {}
        try:
            with patch.object(scanner, "scan_symbol", side_effect=fake_scan_symbol), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                scanner, "get_secondary_timeframe_context", return_value={"6h": {"latest_close": 101}}
            ), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, *args, **kwargs: sent_alert_groups.append((str(chat_id), args)),
            ), patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
                scanner, "load_user_watchlists", return_value={}
            ), patch.object(
                scanner, "save_state"
            ), patch.object(scanner.time, "time", return_value=1_000):
                scanner.WATCHLIST = ["BTC/USD"]
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)

                scanner.WATCHLIST = ["BTC/USD"]
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)

                scanner.WATCHLIST = ["ETH/USD"]
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
        finally:
            scanner.WATCHLIST = original_watchlist

        sent_symbols = [args[0] for _chat_id, args in sent_alert_groups]
        self.assertEqual(sent_symbols, ["BTC/USD", "ETH/USD"])
        self.assertEqual(state["__scan_alert_cooldowns"]["BTC/USD"]["tier2"], 1_000)
        self.assertEqual(state["__scan_alert_cooldowns"]["ETH/USD"]["tier2"], 1_000)

    def test_indicator_only_rolling_confluence_no_longer_sends_across_scan_cycles(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        sent_alert_groups = []
        call_count = {"BTC/USD": 0}
        current_time = {"now": 1_000}
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }

        def fake_scan_symbol(exchange, symbol):
            call_count[symbol] += 1
            candle_time = scanner.TIMEFRAME_MS * call_count[symbol]
            alerts = [volume_alert.copy()] if call_count[symbol] == 1 else [ema_alert.copy()]
            return scan_result_for_alerts(alerts, current_timestamp=candle_time)

        try:
            with patch.object(scanner, "scan_symbol", side_effect=fake_scan_symbol), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, symbol, candle_arg, alerts, *args, **kwargs: sent_alert_groups.append(
                    [alert["type"] for alert in alerts]
                ),
            ), patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
                scanner, "load_user_watchlists", return_value={}
            ), patch.object(
                scanner, "save_state"
            ), patch.object(scanner.time, "time", side_effect=lambda: current_time["now"]):
                state = {}
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
                current_time["now"] += scanner.ROLLING_CONFLUENCE_WINDOW_SECONDS
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(sent_alert_groups, [])
        self.assertEqual(state["__inversion_metrics"]["suppressed_lightweight_groups"], 2)
        self.assertEqual(state["__inversion_metrics"]["would_have_fired_under_old_rules"], 0)

    def test_rolling_confluence_does_not_combine_signals_outside_window(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        sent_alert_groups = []
        call_count = {"BTC/USD": 0}
        current_time = {"now": 1_000}
        alerts_by_call = [
            {
                "type": "volume_spike",
                "label": "Bullish Volume Spike",
                "emoji": "🟢",
                "direction": "bullish",
                "volume_multiple": 2.5,
            },
            {
                "type": "ema_cross_above",
                "label": "EMA 21 crossed above EMA 55",
                "emoji": "🟢",
            },
        ]

        def fake_scan_symbol(exchange, symbol):
            call_count[symbol] += 1
            candle_time = scanner.TIMEFRAME_MS * call_count[symbol]
            return scan_result_for_alerts(
                [alerts_by_call[call_count[symbol] - 1].copy()],
                current_timestamp=candle_time,
            )

        try:
            with patch.object(scanner, "scan_symbol", side_effect=fake_scan_symbol), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, symbol, candle_arg, alerts, *args, **kwargs: sent_alert_groups.append(
                    [alert["type"] for alert in alerts]
                ),
            ), patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
                scanner, "load_user_watchlists", return_value={}
            ), patch.object(
                scanner, "save_state"
            ), patch.object(scanner.time, "time", side_effect=lambda: current_time["now"]):
                state = {}
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
                current_time["now"] += scanner.ROLLING_CONFLUENCE_WINDOW_SECONDS + 1
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(sent_alert_groups, [])

    def test_run_once_does_not_fetch_secondary_context_without_daily_alerts(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        scan_result = scan_result_for_alerts([], current_volume=100)

        try:
            with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                scanner,
                "get_secondary_timeframe_context",
                side_effect=AssertionError("secondary context should not be fetched"),
            ), patch.object(scanner, "send_alert_group_to_chat") as send_group, patch.object(
                scanner, "load_bot_config", return_value={"live_alerts_enabled": True}
            ), patch.object(scanner, "save_state"):
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", {})
        finally:
            scanner.WATCHLIST = original_watchlist

        send_group.assert_not_called()

    def test_run_once_suppresses_lightweight_only_group_with_directionless_rsi(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        sent_alert_groups = []
        ema_below = {
            "type": "ema_cross_below",
            "label": "EMA 21 crossed below EMA 55",
            "emoji": "🔴",
        }
        rsi_below = {
            "type": "rsi_cross_below_30",
            "label": "RSI below 30 — extended",
            "emoji": "🧊",
        }
        scan_result = scan_result_for_alerts([ema_below, rsi_below])
        state = {}

        try:
            with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, symbol, candle_arg, alerts, *args, **kwargs: sent_alert_groups.append(
                    [alert["type"] for alert in alerts]
                ),
            ), patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
                scanner, "load_user_watchlists", return_value={}
            ), patch.object(
                scanner, "save_state"
            ):
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(sent_alert_groups, [])
        self.assertEqual(state["__inversion_metrics"]["suppressed_lightweight_groups"], 1)
        self.assertEqual(state["__inversion_metrics"]["would_have_fired_under_old_rules"], 0)

    def test_run_once_sends_group_with_confirmed_level_break(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        sent_alert_groups = []
        scan_result = scan_result_for_alerts([confirmed_break_alert()])
        state = {}

        try:
            with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                scanner, "get_secondary_timeframe_context", return_value={"6h": {"latest_close": 101}}
            ), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, symbol, candle_arg, alerts, *args, **kwargs: sent_alert_groups.append(
                    [alert["type"] for alert in alerts]
                ),
            ), patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
                scanner, "load_user_watchlists", return_value={}
            ), patch.object(
                scanner, "save_state"
            ):
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(sent_alert_groups, [["live:breakout:100:confirmation"]])
        self.assertEqual(state["__inversion_metrics"]["level_breaks_sent"], 1)

    def test_run_once_attaches_secondary_context_to_outgoing_alert_group(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        sent_alert_groups = []
        secondary_context = {"6h": {"latest_close": 101}}
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }
        level_alert = confirmed_break_alert()
        scan_result = scan_result_for_alerts([level_alert, volume_alert, ema_alert])

        try:
            with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                scanner, "get_secondary_timeframe_context", return_value=secondary_context
            ) as secondary_fetch, patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, symbol, candle_arg, alerts, *args, **kwargs: sent_alert_groups.append(
                    alerts
                ),
            ), patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
                scanner, "load_user_watchlists", return_value={}
            ), patch.object(
                scanner, "save_state"
            ):
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", {})
        finally:
            scanner.WATCHLIST = original_watchlist

        secondary_fetch.assert_called_once_with(ANY, "BTC/USD")
        self.assertEqual(len(sent_alert_groups), 1)
        self.assertTrue(
            all(alert["secondary_timeframe_context"] == secondary_context for alert in sent_alert_groups[0])
        )
        self.assertEqual(
            [alert["type"] for alert in sent_alert_groups[0]],
            ["live:breakout:100:confirmation", "volume_spike", "ema_cross_above"],
        )

    def test_run_once_suppresses_confirmed_alert_when_secondary_context_is_unavailable(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        sent_alert_groups = []
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }
        scan_result = scan_result_for_alerts([confirmed_break_alert(), volume_alert, ema_alert])

        try:
            with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                scanner, "get_secondary_timeframe_context", return_value=None
            ), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, symbol, candle_arg, alerts, *args, **kwargs: sent_alert_groups.append(
                    [alert["type"] for alert in alerts]
                ),
            ), patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
                scanner, "load_user_watchlists", return_value={}
            ), patch.object(
                scanner, "save_state"
            ):
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", {})
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(sent_alert_groups, [])

    def test_run_once_suppresses_level_attempts_and_indicator_only_context(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD"]
        sent_alert_groups = []
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }
        break_attempt = {
            "type": "live:breakout:100:early_warning",
            "label": "Breakout Attempt",
            "emoji": "⚠️",
            "level": 100,
        }
        scan_result = scan_result_for_alerts([volume_alert, ema_alert])
        state = {}

        try:
            with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(scanner, "build_level_alerts", return_value=[break_attempt]), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, symbol, candle_arg, alerts, *args, **kwargs: sent_alert_groups.append(
                    [alert["type"] for alert in alerts]
                ),
            ), patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
                scanner, "load_user_watchlists", return_value={}
            ), patch.object(
                scanner, "save_state"
            ):
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(sent_alert_groups, [])
        early_warning_keys = [
            key
            for key in state["BTC/USD"]["sent_alerts"]
            if key.startswith("live:breakout:") and key.endswith(":early_warning")
        ]
        self.assertEqual(len(early_warning_keys), 1)
        self.assertEqual(
            state["__active_trades"]["BTC/USD"]["source_alert"],
            "Breakout Attempt",
        )
        self.assertEqual(state["__inversion_metrics"]["suppressed_lightweight_groups"], 1)

    def test_livealerts_command_toggles_main_chat_routing(self):
        original_watchlist = scanner.WATCHLIST[:]
        original_test_chat = scanner.LIVE_ALERT_TEST_CHAT_ID
        scanner.WATCHLIST = ["BTC/USD"]
        scanner.LIVE_ALERT_TEST_CHAT_ID = "TEST_CHAT"
        config = scanner.DEFAULT_BOT_CONFIG.copy()
        sent_messages = []
        sent_alert_groups = []
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }
        scan_result = scan_result_for_alerts([confirmed_break_alert(), volume_alert, ema_alert], current_volume=200)

        def save_config(updated_config):
            config.clear()
            config.update(updated_config)

        try:
            with patch.object(scanner, "is_admin_user", return_value=True), patch.object(
                scanner, "load_bot_config", side_effect=lambda: config.copy()
            ), patch.object(scanner, "save_bot_config", side_effect=save_config), patch.object(
                scanner, "log_mode_command_debug"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_mode_command(
                    "TOKEN",
                    "999",
                    "/livealerts on",
                    source_chat={"id": "999", "type": "private"},
                    from_user={"id": 123},
                )
                self.assertTrue(config["live_alerts_enabled"])

                with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                    scanner, "get_current_market_price", return_value=101
                ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                    scanner, "get_secondary_timeframe_context", return_value={"6h": {"latest_close": 101}}
                ), patch.object(
                    scanner,
                    "send_alert_group_to_chat",
                    side_effect=lambda token, chat_id, *args, **kwargs: sent_alert_groups.append((str(chat_id), args)),
                ), patch.object(scanner, "load_user_watchlists", return_value={}), patch.object(scanner, "save_state"):
                    scanner.run_once(object(), "TOKEN", "MAIN_CHAT", {})

                scanner.handle_mode_command(
                    "TOKEN",
                    "999",
                    "/livealerts off",
                    source_chat={"id": "999", "type": "private"},
                    from_user={"id": 123},
                )
                self.assertFalse(config["live_alerts_enabled"])

                with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                    scanner, "get_current_market_price", return_value=101
                ), patch.object(scanner, "build_level_alerts", side_effect=AssertionError("level alerts disabled")), patch.object(
                    scanner, "get_secondary_timeframe_context", return_value={"6h": {"latest_close": 101}}
                ), patch.object(
                    scanner,
                    "send_alert_group_to_chat",
                    side_effect=lambda token, chat_id, *args, **kwargs: sent_alert_groups.append((str(chat_id), args)),
                ), patch.object(scanner, "load_user_watchlists", return_value={}), patch.object(
                    scanner, "save_state"
                ):
                    scanner.run_once(object(), "TOKEN", "MAIN_CHAT", {})
        finally:
            scanner.WATCHLIST = original_watchlist
            scanner.LIVE_ALERT_TEST_CHAT_ID = original_test_chat

        alert_destinations = [chat_id for chat_id, args in sent_alert_groups]
        self.assertEqual(alert_destinations, ["MAIN_CHAT", "TEST_CHAT"])

    def test_levels_command_falls_back_when_higher_timeframes_fail(self):
        primary_closes = [95 + (index % 20) * 0.5 for index in range(119)] + [100]
        fake_exchange = FakeExchange(
            {
                scanner.TIMEFRAME: make_ohlcv_series(primary_closes),
            },
            ticker_price=100,
            failing_timeframes={"1h"},
        )

        message = scanner.build_levels_command_message(fake_exchange, "BTC/USD")

        self.assertTrue(message.startswith("📍 POINKLE SNAPSHOT — BTC / USD"))
        self.assertIn("💰 PRICE\n100.00", message)
        self.assertIn("📈 TREND", message)
        self.assertIn("🎯 FOCUS", message)
        self.assertIn("⭐ MARKET SCORE", message)
        self.assertIn("🧠 SETUP GRADE", message)
        self.assertIn("📊 RSI", message)
        self.assertIn("👀 LOOK ORDER", message)
        self.assertIn(scanner.poinkle_educational_footer(), message)

    def test_help_command_sends_question_panel(self):
        sent_messages = []

        with patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
        ):
            scanner.handle_help_command("TOKEN", "999")

        self.assertEqual(sent_messages, [("999", scanner.command_panel_text(), scanner.command_panel_keyboard())])

    def test_poinkle_info_text_is_short_and_points_to_learning_and_coins(self):
        message = scanner.poinkle_onboarding_text("help")

        self.assertIn("Poinkle watches the zones", message)
        self.assertIn("You don't have to remember any of these. Just send /help and tap.", message)
        self.assertIn("VERIFY\n/verify", message)
        self.assertIn("/explain", message)
        self.assertIn("/whynot", message)
        for deleted_command in (
            "/levels",
            "/snap",
            "/why",
            "/learn",
            "/watching",
            "/reference",
            "/guide",
            "/coins",
            "/clearwatch",
            "/mywatch",
            "/scan",
            "/status",
            "/commands",
        ):
            self.assertIsNone(re.search(rf"{re.escape(deleted_command)}(?:\s|,|—|$)", message))
        self.assertNotIn("Current Supported Coins", message)
        self.assertLess(len(message), 4096)

    def test_help_does_not_use_stale_trade_or_confluence_language(self):
        message = scanner.poinkle_onboarding_text("help").lower()

        for stale_phrase in ("confluence", "trade plan", "trade levels", "patience grade"):
            self.assertNotIn(stale_phrase, message)

    def test_no_user_facing_removed_command_message_exists(self):
        scanner_source = (PROJECT_DIR / "crypto_alert_scanner.py").read_text()

        self.assertNotIn("send /commands", scanner_source)
        self.assertNotIn("doesn't exist anymore", scanner_source)
        self.assertNotIn("no longer exists", scanner_source)
        self.assertNotIn("command was removed", scanner_source)
        self.assertFalse(hasattr(scanner, "DELETED_COMMAND_MESSAGE"))

    def test_help_lists_no_command_without_handler(self):
        message = scanner.poinkle_onboarding_text("help")
        help_commands = set(re.findall(r"/([a-z]+)", message))
        public_commands = {item["command"] for item in scanner.PUBLIC_BOT_COMMANDS}

        self.assertTrue(help_commands)
        self.assertTrue(help_commands.issubset(public_commands))
        self.assertNotIn("mystats", help_commands)
        self.assertNotIn("chart", help_commands)
        self.assertNotIn("watchlist", help_commands)

    def test_every_public_command_menu_entry_appears_in_help(self):
        message = scanner.poinkle_onboarding_text("help")

        for command in scanner.PUBLIC_BOT_COMMANDS:
            self.assertIn(f"/{command['command']}", message)

    def test_hidden_public_handlers_appear_in_help(self):
        message = scanner.poinkle_onboarding_text("help")

        expected_commands = {
            "start",
            "help",
            "verify",
            "explain",
            "whatnow",
            "snapshot",
            "research",
            "whynot",
            "watch",
            "unwatch",
            "alertlevel",
            "alerts",
            "myalerts",
            "mike",
        }

        self.assertEqual(set(re.findall(r"/([a-z]+)", message)), expected_commands)

    def test_panel_help_sends_poinkle_info_text_with_command_list(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }
        sent_messages = []

        with patch.object(scanner, "answer_telegram_callback"), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            handled = scanner.handle_panel_callback("TOKEN", callback_query, "help", exchange=object())

        self.assertTrue(handled)
        self.assertEqual(sent_messages[0][0], "777")
        self.assertIn("Poinkle watches the zones", sent_messages[0][1])
        self.assertIn("/snapshot", sent_messages[0][1])
        self.assertIn("/mike", sent_messages[0][1])
        self.assertIsNone(sent_messages[0][2])

    def test_verify_registered_handle_returns_verified(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
                "registered_at": "2026-07-13",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_verify_command("TOKEN", "999", "/verify @MikeKnows_Official")

        self.assertIn("✅ <b>VERIFIED</b>", sent_messages[0][1])
        self.assertIn("@MikeKnows_Official is <b>Mike Knows</b>' real Telegram.", sent_messages[0][1])
        self.assertIn("All registered accounts for <b>Mike Knows</b> · The Inner Circle:", sent_messages[0][1])
        self.assertIn("Registered with Poinkle on 13 Jul 2026.", sent_messages[0][1])

    def test_verify_tiktok_handle_names_platform_and_lists_all_accounts(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [
                    {"platform": "telegram", "handle": "@MikeKnows_Official"},
                    {"platform": "tiktok", "handle": "@mikeknows"},
                    {"platform": "youtube", "handle": "@MikeKnows"},
                ],
                "registered_at": "2026-07-13",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_verify_command("TOKEN", "999", "/verify mikeknows")

        message = sent_messages[0][1]
        self.assertIn("@mikeknows is registered for <b>Mike Knows</b> on: TikTok, YouTube.", message)
        self.assertIn("Telegram  @MikeKnows_Official", message)
        self.assertIn("TikTok    @mikeknows", message)
        self.assertIn("YouTube   @MikeKnows", message)

    def test_verified_card_uses_possessive_s_for_names_not_ending_in_s(self):
        creator = {
            "display_name": "Test Creator",
            "community": "Test Community",
            "accounts": [{"platform": "tiktok", "handle": "@testtok"}],
            "registered_at": "2026-07-13",
        }

        message = scanner.render_verified_creator_message(
            "@testtok",
            creator,
            matched_accounts=creator["accounts"],
        )

        self.assertIn("@testtok is <b>Test Creator</b>'s real TikTok.", message)

    def test_verified_card_uses_apostrophe_for_names_ending_in_s(self):
        creator = {
            "display_name": "Chris",
            "community": "Test Community",
            "accounts": [{"platform": "tiktok", "handle": "@chris"}],
            "registered_at": "2026-07-13",
        }

        message = scanner.render_verified_creator_message(
            "@chris",
            creator,
            matched_accounts=creator["accounts"],
        )

        self.assertIn("@chris is <b>Chris</b>' real TikTok.", message)

    def test_verify_same_handle_on_two_platforms_shows_both_matches(self):
        creator = {
            "display_name": "Mike Knows",
            "community": "The Inner Circle",
            "accounts": [
                {"platform": "tiktok", "handle": "@mikeknows"},
                {"platform": "x", "handle": "@mikeknows"},
            ],
            "registered_at": "2026-07-13",
        }

        message = scanner.render_verified_creator_message(
            "@mikeknows",
            creator,
            matched_accounts=creator["accounts"],
        )

        self.assertIn("@mikeknows is registered for <b>Mike Knows</b> on: TikTok, X.", message)
        self.assertIn("TikTok  @mikeknows", message)
        self.assertIn("X       @mikeknows", message)

    def test_verify_matching_is_case_insensitive_and_at_optional(self):
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
                "registered_at": "2026-07-13",
            }
        }
        self.assertEqual(scanner.find_creator_by_handle(creators, "mikeknows_official")[0], "mike_knows")
        self.assertEqual(scanner.find_creator_by_handle(creators, "@MIKEKNOWS_OFFICIAL")[0], "mike_knows")

    def test_old_creator_handles_shape_loads_as_telegram_accounts(self):
        creator = {
            "display_name": "Mike Knows",
            "community": "The Inner Circle",
            "handles": ["@MikeKnows_Official"],
            "registered_at": "2026-07-13",
        }

        self.assertEqual(
            scanner.creator_accounts(creator),
            [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
        )
        self.assertEqual(scanner.find_creator_by_handle({"mike_knows": creator}, "mikeknows_official")[0], "mike_knows")

    def test_verify_unregistered_handle_is_not_registered_and_never_accuses(self):
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
                "registered_at": "2026-07-13",
            }
        }
        message = scanner.render_not_registered_creator_message("@SomeHandle", creators)

        self.assertIn("⚠️ <b>NOT REGISTERED</b>", message)
        self.assertIn("This does NOT mean it's fake", message)
        self.assertNotIn("is fake", message.replace("does NOT mean it's fake", ""))

    def test_verify_response_never_asserts_account_is_fake(self):
        creator = {
            "display_name": "Mike Knows",
            "community": "The Inner Circle",
            "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
            "registered_at": "2026-07-13",
        }
        responses = [
            scanner.render_verified_creator_message("@MikeKnows_Official", creator),
            scanner.render_not_registered_creator_message("@SomeHandle", {"mike_knows": creator}),
            scanner.render_not_registered_creator_message("@SomeHandle", {}),
        ]

        for response in responses:
            self.assertNotIn("is fake", response.replace("does NOT mean it's fake", ""))
            self.assertNotIn("are fake", response)

    def test_bare_verify_empty_registry_replies_without_keyboard(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text("{}")
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_verify_command("TOKEN", "999", "/verify")

        self.assertEqual(sent_messages, [("999", "No creators are registered with Poinkle yet.", None)])

    def test_bare_verify_with_creators_shows_picker(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
                "registered_at": "2026-07-13",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_verify_command("TOKEN", "999", "/verify")

        self.assertEqual(sent_messages[0][1], "Which creator's accounts do you want to check?")
        self.assertEqual(
            sent_messages[0][2],
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "Mike Knows · The Inner Circle",
                            "callback_data": "verifycreator:mike_knows",
                        }
                    ],
                    [{"text": "⬅️ Back", "callback_data": "panel:open"}],
                ]
            },
        )

    def test_verify_creator_callback_shows_one_account_button_per_registered_account(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [
                    {"platform": "telegram", "handle": "@MikeKnows_Official"},
                    {"platform": "tiktok", "handle": "@mikeknows.io"},
                    {"platform": "youtube", "handle": "@MikeKnows"},
                ],
                "registered_at": "2026-07-13",
            }
        }
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "answer_telegram_callback"
            ), patch.object(scanner, "clear_callback_message_keyboard"), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                handled = scanner.handle_verify_creator_callback("TOKEN", callback_query, "mike_knows")

        self.assertTrue(handled)
        rows = sent_messages[0][2]["inline_keyboard"]
        self.assertEqual([len(row) for row in rows], [1, 1, 1, 1])
        self.assertEqual(rows[0][0]["text"], "Telegram  @MikeKnows_Official")
        self.assertEqual(rows[0][0]["callback_data"], "verifyhandle:mike_knows:0")
        self.assertEqual(rows[1][0]["text"], "TikTok  @mikeknows.io")
        self.assertEqual(rows[1][0]["callback_data"], "verifyhandle:mike_knows:1")
        self.assertEqual(rows[2][0]["text"], "YouTube  @MikeKnows")
        self.assertEqual(rows[2][0]["callback_data"], "verifyhandle:mike_knows:2")
        self.assertEqual(rows[3][0]["callback_data"], "panel:verify")

    def test_verify_handle_callback_sends_verified_card_for_that_handle(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [
                    {"platform": "telegram", "handle": "@MikeKnows_Official"},
                    {"platform": "tiktok", "handle": "@mikeknows.io"},
                ],
                "registered_at": "2026-07-13",
            }
        }
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "answer_telegram_callback"
            ), patch.object(scanner, "clear_callback_message_keyboard"), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                handled = scanner.handle_verify_handle_callback("TOKEN", callback_query, "mike_knows:1")

        self.assertTrue(handled)
        self.assertIn("✅ <b>VERIFIED</b>", sent_messages[0][1])
        self.assertIn("@mikeknows.io is <b>Mike Knows</b>' real TikTok.", sent_messages[0][1])

    def test_verify_handle_button_path_matches_typed_verify_card(self):
        typed_messages = []
        button_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [
                    {"platform": "telegram", "handle": "@MikeKnows_Official"},
                    {"platform": "tiktok", "handle": "@mikeknows.io"},
                ],
                "registered_at": "2026-07-13",
            }
        }
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: typed_messages.append(text),
            ):
                scanner.handle_verify_command("TOKEN", "777", "/verify @mikeknows.io")
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "answer_telegram_callback"
            ), patch.object(scanner, "clear_callback_message_keyboard"), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: button_messages.append(text),
            ):
                scanner.handle_verify_handle_callback("TOKEN", callback_query, "mike_knows:1")

        self.assertEqual(button_messages[0], typed_messages[0])

    def test_verify_handle_double_tap_sends_verified_card_once(self):
        state = {}
        sent_messages = []
        acked_callbacks = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "tiktok", "handle": "@mikeknows.io"}],
                "registered_at": "2026-07-13",
            }
        }
        updates = [
            {
                "update_id": 301,
                "callback_query": {
                    "id": "callback-1",
                    "data": "verifyhandle:mike_knows:0",
                    "message": {"chat": {"id": "777"}, "message_id": 55},
                    "from": {"id": 777},
                },
            },
            {
                "update_id": 302,
                "callback_query": {
                    "id": "callback-2",
                    "data": "verifyhandle:mike_knows:0",
                    "message": {"chat": {"id": "777"}, "message_id": 55},
                    "from": {"id": 777},
                },
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "get_telegram_updates", return_value=updates
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(text),
            ), patch.object(
                scanner,
                "answer_telegram_callback",
                side_effect=lambda token, callback_id, text="": acked_callbacks.append(callback_id),
            ), patch.object(scanner, "clear_callback_message_keyboard", return_value=True), patch.object(
                scanner, "save_state"
            ):
                scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(acked_callbacks, ["callback-1", "callback-2"])

    def test_verify_creator_with_same_handle_on_two_platforms_renders_two_account_buttons(self):
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [
                    {"platform": "instagram", "handle": "@mikeknows_og"},
                    {"platform": "x", "handle": "@mikeknows_og"},
                ],
                "registered_at": "2026-07-13",
            }
        }
        keyboard = scanner.creator_account_keyboard("mike_knows", creators["mike_knows"])
        rows = keyboard["inline_keyboard"]

        self.assertEqual(rows[0][0]["text"], "Instagram  @mikeknows_og")
        self.assertEqual(rows[1][0]["text"], "X  @mikeknows_og")
        self.assertIn("Instagram, X", scanner.render_verified_creator_message(
            "@mikeknows_og",
            creators["mike_knows"],
            matched_accounts=scanner.creator_accounts(creators["mike_knows"]),
        ))

    def test_verify_handle_callback_data_stays_under_telegram_limit(self):
        creator_key = "mike_knows"
        creator = {
            "display_name": "Mike Knows",
            "community": "The Inner Circle",
            "accounts": [{"platform": "tiktok", "handle": "@mikeknows.io"}],
            "registered_at": "2026-07-13",
        }
        keyboard = scanner.creator_account_keyboard(creator_key, creator)
        callback_data = keyboard["inline_keyboard"][0][0]["callback_data"]

        self.assertLessEqual(len(callback_data.encode("utf-8")), 64)

    def test_onboard_routes_store_experience_and_show_next_steps(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }
        routes = ("beginner", "basics", "trader", "browsing")

        for route in routes:
            sent_messages = []
            with self.subTest(route=route), tempfile.TemporaryDirectory() as tmpdir, patch.object(
                scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
            ), patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
                scanner, "clear_callback_message_keyboard"
            ) as clear_keyboard, patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                handled = scanner.handle_onboard_callback("TOKEN", callback_query, route)
                profiles = scanner.load_user_profiles()

            self.assertTrue(handled)
            answer_callback.assert_called_once_with("TOKEN", "callback-1")
            clear_keyboard.assert_not_called()
            self.assertEqual(profiles["777"]["experience"], route)
            self.assertEqual(sent_messages[0][0], "777")
            self.assertEqual(sent_messages[0][1], scanner.onboard_route_text(route))
            self.assertEqual(sent_messages[0][2], scanner.onboard_route_keyboard(route))
            flat_buttons = [
                button["callback_data"]
                for row in sent_messages[0][2]["inline_keyboard"]
                for button in row
            ]
            self.assertIn("panel:open", flat_buttons)

    def test_orientation_card_first_button_shows_bitcoin(self):
        keyboard = scanner.start_orientation_keyboard()
        labels = [row[0]["text"] for row in keyboard["inline_keyboard"]]
        callbacks = [row[0]["callback_data"] for row in keyboard["inline_keyboard"]]

        self.assertNotIn("Before I throw anything at you", scanner.start_orientation_text())
        self.assertEqual(
            labels,
            [
                "📍 Show me Bitcoin",
                "📍 Show me another coin",
                "📚 Teach me something",
                "🔍 Verify a creator",
                "⚡ Everything else",
            ],
        )
        self.assertEqual(
            callbacks,
            ["coinpick:snapshot:BTC", "panel:where", "panel:explain", "panel:verify", "panel:open"],
        )

    def test_orientation_bitcoin_button_queues_btc_snapshot_and_keeps_keyboard(self):
        callback_query = {
            "id": "callback-1",
            "data": "coinpick:snapshot:BTC",
            "message": {
                "chat": {"id": "777", "type": "private"},
                "message_id": 44,
                "reply_markup": scanner.start_orientation_keyboard(),
            },
            "from": {"id": 777},
        }

        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner, "clear_callback_message_keyboard"
        ) as clear_keyboard, patch.object(scanner, "enqueue_telegram_command_job", return_value=True) as enqueue_job, patch.object(
            scanner, "send_heavy_job_acknowledgment"
        ) as send_ack:
            handled = scanner.handle_coin_pick_callback("TOKEN", callback_query, "snapshot:BTC", exchange=object())

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        clear_keyboard.assert_not_called()
        enqueue_job.assert_called_once()
        self.assertEqual(enqueue_job.call_args.args[0:3], ("snapshot", "777", "/snapshot BTC"))
        send_ack.assert_called_once_with("TOKEN", "777", "snapshot", "/snapshot BTC")

    def test_command_panel_opens_from_callback_and_help_command(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }
        sent_messages = []

        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner, "clear_callback_message_keyboard"
        ) as clear_keyboard, patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            handled = scanner.handle_panel_callback("TOKEN", callback_query, "open")
            scanner.handle_help_command("TOKEN", "777")

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        clear_keyboard.assert_not_called()
        self.assertEqual(sent_messages[0], ("777", scanner.command_panel_text(), scanner.command_panel_keyboard()))
        self.assertEqual(sent_messages[1], ("777", scanner.command_panel_text(), scanner.command_panel_keyboard()))

    def test_command_panel_shows_questions_not_command_names(self):
        self.assertEqual(scanner.command_panel_text(), "What do you want to know?")
        labels = [
            row[0]["text"]
            for row in scanner.command_panel_keyboard()["inline_keyboard"]
        ]
        callbacks = [
            row[0]["callback_data"]
            for row in scanner.command_panel_keyboard()["inline_keyboard"]
        ]

        self.assertEqual(
            labels,
            [
                "🤷 Should I buy or sell?",
                "🌱 I'm new — where should I start?",
                "📍 Where is this coin right now?",
                "🤔 Why isn't it alerting?",
                "🎭 Real breakout or fakeout?",
                "🔍 Tell me more about a coin",
                "👀 Watch a coin for me",
                "📚 Teach me a concept",
                "🔍 Verify a creator's account",
                "🔔 How much should I hear from you?",
                "ℹ️ What is Poinkle?",
            ],
        )
        self.assertEqual(
            callbacks,
            [
                "panel:whatnow",
                "onboard:ask",
                "panel:where",
                "panel:whynot",
                "panel:fakeout",
                "panel:research",
                "panel:watch",
                "panel:explain",
                "panel:verify",
                "panel:alertlevel",
                "panel:help",
            ],
        )
        joined_labels = "\n".join(labels)
        for command_name in ("Research a coin", "Daily snapshot", "Key levels"):
            self.assertNotIn(command_name, joined_labels)

    def test_onboarding_question_is_reachable_from_command_panel(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }
        sent_messages = []

        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            handled = scanner.handle_onboard_callback("TOKEN", callback_query, "ask")

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        self.assertEqual(sent_messages[0], ("777", scanner.onboarding_question_text(), scanner.onboarding_question_keyboard()))
        callbacks = [
            button["callback_data"]
            for row in sent_messages[0][2]["inline_keyboard"]
            for button in row
        ]
        self.assertEqual(
            callbacks,
            ["onboard:beginner", "onboard:basics", "onboard:trader", "onboard:browsing", "panel:open"],
        )

    def test_no_button_label_uses_snapshot_language(self):
        keyboards = [
            scanner.start_orientation_keyboard(),
            scanner.command_panel_keyboard(),
            scanner.onboarding_question_keyboard(),
            scanner.target_coin_picker_keyboard("snapshot", user_id="777"),
            scanner.target_coin_picker_keyboard("research", user_id="777"),
            scanner.target_coin_picker_keyboard("whynot", user_id="777"),
            scanner.target_coin_picker_keyboard("whatnow", user_id="777"),
            scanner.target_coin_picker_keyboard("fakeout", user_id="777"),
        ]

        labels = [
            button["text"]
            for keyboard in keyboards
            for row in keyboard["inline_keyboard"]
            for button in row
        ]

        for label in labels:
            self.assertNotIn("snapshot", label.lower())

    def test_panel_buttons_open_existing_paths_or_coin_picker(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }

        cases = [
            ("verify", "handle_verify_command"),
            ("explain", "handle_explain_command"),
            ("alertlevel", "handle_alertlevel_command"),
            ("help", "send_poinkle_info_text"),
        ]
        for payload, handler_name in cases:
            with self.subTest(payload=payload), patch.object(scanner, "answer_telegram_callback"), patch.object(
                scanner, "clear_callback_message_keyboard"
            ), patch.object(scanner, "handle_verify_command") as verify_handler, patch.object(
                scanner, "handle_explain_command"
            ) as explain_handler, patch.object(scanner, "handle_alertlevel_command") as alertlevel_handler, patch.object(
                scanner, "send_poinkle_info_text"
            ) as info_handler:
                handled = scanner.handle_panel_callback("TOKEN", callback_query, payload, exchange=object())

            self.assertTrue(handled)
            handlers = {
                "handle_verify_command": verify_handler,
                "handle_explain_command": explain_handler,
                "handle_alertlevel_command": alertlevel_handler,
                "send_poinkle_info_text": info_handler,
            }
            handlers[handler_name].assert_called_once()
            for other_name, handler in handlers.items():
                if other_name != handler_name:
                    handler.assert_not_called()

        for payload, expected_target in (
            ("whatnow", "whatnow"),
            ("where", "snapshot"),
            ("whynot", "whynot"),
            ("fakeout", "fakeout"),
            ("watch", "watch"),
            ("research", "research"),
        ):
            sent_messages = []
            with self.subTest(payload=payload), patch.object(scanner, "answer_telegram_callback"), patch.object(
                scanner, "clear_callback_message_keyboard"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                handled = scanner.handle_panel_callback("TOKEN", callback_query, payload, exchange=object())

            self.assertTrue(handled)
            self.assertEqual(sent_messages[0][0], "777")
            if payload == "watch":
                self.assertEqual(sent_messages[0][1], scanner.watch_toggle_picker_text())
                self.assertEqual(sent_messages[0][2], scanner.watch_toggle_keyboard("777"))
            else:
                self.assertEqual(sent_messages[0][1], "Which coin?")
                self.assertEqual(sent_messages[0][2], scanner.target_coin_picker_keyboard(expected_target))

    def test_bare_watch_opens_toggle_picker(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "user_watchlists.json"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_watch_command(
                object(),
                "TOKEN",
                "777",
                "/watch",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )
            expected_keyboard = scanner.watch_toggle_keyboard("777")

        self.assertEqual(sent_messages[0][0], "777")
        self.assertEqual(sent_messages[0][1], scanner.watch_toggle_picker_text())
        self.assertNotIn("Use: /watch BTC", sent_messages[0][1])
        self.assertEqual(sent_messages[0][2], expected_keyboard)

    def test_watch_toggle_adds_unchecked_coin_and_updates_keyboard(self):
        edited_keyboards = []
        callback_query = {
            "id": "callback-1",
            "data": "watchtoggle:BTC/USD",
            "message": {
                "chat": {"id": "777", "type": "private"},
                "message_id": 44,
                "reply_markup": scanner.watch_toggle_keyboard("777"),
            },
            "from": {"id": 777},
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "user_watchlists.json"
        ), patch.object(scanner, "answer_telegram_callback"), patch.object(
            scanner,
            "edit_telegram_message_reply_markup",
            side_effect=lambda token, chat_id, message_id, reply_markup: edited_keyboards.append(reply_markup) or True,
        ):
            handled = scanner.handle_watch_toggle_callback("TOKEN", callback_query, "BTC/USD")
            watchlists = scanner.load_user_watchlists()

        self.assertTrue(handled)
        self.assertEqual(watchlists, {"777": ["BTC/USD"]})
        button_texts = [
            button["text"]
            for row in edited_keyboards[-1]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("✅ BTC", button_texts)

    def test_watch_toggle_removes_checked_coin_and_updates_keyboard(self):
        edited_keyboards = []
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "user_watchlists.json"
            watchlist_path.write_text(json.dumps({"777": ["BTC/USD"]}))
            callback_query = {
                "id": "callback-1",
                "data": "watchtoggle:BTC/USD",
                "message": {
                    "chat": {"id": "777", "type": "private"},
                    "message_id": 44,
                    "reply_markup": scanner.watch_toggle_keyboard("777"),
                },
                "from": {"id": 777},
            }
            with patch.object(scanner, "USER_WATCHLISTS_FILE", watchlist_path), patch.object(
                scanner, "answer_telegram_callback"
            ), patch.object(
                scanner,
                "edit_telegram_message_reply_markup",
                side_effect=lambda token, chat_id, message_id, reply_markup: edited_keyboards.append(reply_markup) or True,
            ):
                handled = scanner.handle_watch_toggle_callback("TOKEN", callback_query, "BTC/USD")
                watchlists = scanner.load_user_watchlists()

        self.assertTrue(handled)
        self.assertEqual(watchlists, {})
        button_texts = [
            button["text"]
            for row in edited_keyboards[-1]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("  BTC", button_texts)

    def test_watch_toggle_keyboard_survives_multiple_adds(self):
        edited_keyboards = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "user_watchlists.json"
        ), patch.object(scanner, "answer_telegram_callback"), patch.object(
            scanner,
            "edit_telegram_message_reply_markup",
            side_effect=lambda token, chat_id, message_id, reply_markup: edited_keyboards.append(reply_markup) or True,
        ), patch.object(scanner, "send_telegram_message") as send_message:
            for index, symbol in enumerate(("BTC/USD", "ETH/USD", "SOL/USD"), start=1):
                callback_query = {
                    "id": f"callback-{index}",
                    "data": f"watchtoggle:{symbol}",
                    "message": {
                        "chat": {"id": "777", "type": "private"},
                        "message_id": 44,
                        "reply_markup": scanner.watch_toggle_keyboard("777"),
                    },
                    "from": {"id": 777},
                }
                self.assertTrue(scanner.handle_watch_toggle_callback("TOKEN", callback_query, symbol))
            watchlists = scanner.load_user_watchlists()

        self.assertEqual(watchlists, {"777": ["BTC/USD", "ETH/USD", "SOL/USD"]})
        self.assertEqual(len(edited_keyboards), 3)
        send_message.assert_not_called()

    def test_watch_toggle_same_coin_off_then_on_is_not_message_deduped(self):
        state = {}
        edited_keyboards = []
        updates = [
            {
                "update_id": 301,
                "callback_query": {
                    "id": "callback-1",
                    "data": "watchtoggle:BTC/USD",
                    "message": {
                        "chat": {"id": "777", "type": "private"},
                        "message_id": 44,
                        "reply_markup": scanner.watch_toggle_keyboard("777"),
                    },
                    "from": {"id": 777},
                },
            },
            {
                "update_id": 302,
                "callback_query": {
                    "id": "callback-2",
                    "data": "watchtoggle:BTC/USD",
                    "message": {
                        "chat": {"id": "777", "type": "private"},
                        "message_id": 44,
                        "reply_markup": scanner.watch_toggle_keyboard("777"),
                    },
                    "from": {"id": 777},
                },
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "user_watchlists.json"
            watchlist_path.write_text(json.dumps({"777": ["BTC/USD"]}))
            with patch.object(
                scanner, "USER_WATCHLISTS_FILE", watchlist_path
            ), patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
                scanner, "answer_telegram_callback"
            ), patch.object(
                scanner,
                "edit_telegram_message_reply_markup",
                side_effect=lambda token, chat_id, message_id, reply_markup: edited_keyboards.append(reply_markup) or True,
            ), patch.object(scanner, "save_state"):
                scanner.process_telegram_commands(object(), "TOKEN", "999", state)
                watchlists = scanner.load_user_watchlists()

        self.assertEqual(watchlists, {"777": ["BTC/USD"]})
        self.assertEqual(len(edited_keyboards), 2)
        self.assertEqual(state["__telegram_commands"].get("handled_callback_message_keys", []), [])

    def test_watch_letter_grid_only_shows_letters_with_coins(self):
        original_watchlist = scanner.WATCHLIST[:]
        try:
            scanner.WATCHLIST = ["BTC/USD", "ETH/USD", "SOL/USD"]
            callbacks = [
                button["callback_data"]
                for row in scanner.watch_letter_keyboard()["inline_keyboard"]
                for button in row
            ]
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(callbacks[:-1], ["watchletter:B", "watchletter:E", "watchletter:S"])
        self.assertEqual(callbacks[-1], "panel:watch")

    def test_watch_letter_picker_shows_matching_coins_with_checked_state(self):
        original_watchlist = scanner.WATCHLIST[:]
        sent_messages = []
        try:
            scanner.WATCHLIST = ["BTC/USD", "BCH/USD", "ETH/USD"]
            with tempfile.TemporaryDirectory() as tmpdir:
                watchlist_path = Path(tmpdir) / "user_watchlists.json"
                watchlist_path.write_text(json.dumps({"777": ["BCH/USD"]}))
                callback_query = {
                    "id": "callback-1",
                    "data": "watchletter:B",
                    "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
                    "from": {"id": 777},
                }
                with patch.object(scanner, "USER_WATCHLISTS_FILE", watchlist_path), patch.object(
                    scanner, "answer_telegram_callback"
                ), patch.object(
                    scanner,
                    "send_telegram_message",
                    side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                        (str(chat_id), text, reply_markup)
                    ),
                ):
                    handled = scanner.handle_watch_letter_callback("TOKEN", callback_query, "B")
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertTrue(handled)
        self.assertEqual(sent_messages[0][1], "Coins starting with B.")
        button_texts = [
            button["text"]
            for row in sent_messages[0][2]["inline_keyboard"]
            for button in row
        ]
        self.assertIn("  BTC", button_texts)
        self.assertIn("✅ BCH", button_texts)
        self.assertNotIn("  ETH", button_texts)

    def test_typed_watch_single_coin_still_adds(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "user_watchlists.json"
        ), patch.object(scanner, "validate_tradeable_symbol", return_value="BTC/USD"), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_watch_command(
                object(),
                "TOKEN",
                "777",
                "/watch BTC",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )
            watchlists = scanner.load_user_watchlists()

        self.assertEqual(watchlists, {"777": ["BTC/USD"]})
        self.assertEqual(sent_messages, [("777", "✅ Added to your watchlist: BTC")])

    def test_bare_snapshot_opens_coin_picker(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "missing_user_watchlists.json"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_levels_command(
                object(),
                "TOKEN",
                "777",
                "/snapshot",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )

        self.assertEqual(sent_messages[0][0], "777")
        self.assertEqual(sent_messages[0][1], scanner.target_coin_picker_text("snapshot"))
        self.assertEqual(sent_messages[0][2], scanner.target_coin_picker_keyboard("snapshot", user_id="777"))
        self.assertNotIn("Use: /snapshot BTC", sent_messages[0][1])

    def test_bare_research_opens_coin_picker(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "missing_user_watchlists.json"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_research_command(
                object(),
                "TOKEN",
                "777",
                "/research",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )

        self.assertEqual(sent_messages[0][1], scanner.target_coin_picker_text("research"))
        self.assertEqual(sent_messages[0][2], scanner.target_coin_picker_keyboard("research", user_id="777"))

    def test_bare_whynot_opens_coin_picker(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "missing_user_watchlists.json"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_whynot_command(
                object(),
                "TOKEN",
                "777",
                "/whynot",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )

        self.assertEqual(sent_messages[0][1], scanner.target_coin_picker_text("whynot"))
        self.assertEqual(sent_messages[0][2], scanner.target_coin_picker_keyboard("whynot", user_id="777"))

    def test_bare_whatnow_opens_coin_picker(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "missing_user_watchlists.json"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_whatnow_command(
                object(),
                "TOKEN",
                "777",
                "/whatnow",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )

        self.assertEqual(sent_messages[0][1], scanner.target_coin_picker_text("whatnow"))
        self.assertEqual(sent_messages[0][2], scanner.target_coin_picker_keyboard("whatnow", user_id="777"))

    def test_bare_unwatch_opens_toggle_picker(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "user_watchlists.json"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_unwatch_command(
                "TOKEN",
                "777",
                "/unwatch",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )
            expected_keyboard = scanner.watch_toggle_keyboard("777")

        self.assertEqual(sent_messages[0], ("777", scanner.watch_toggle_picker_text(), expected_keyboard))

    def test_no_bare_coin_command_reply_contains_use_command(self):
        command_calls = [
            lambda: scanner.handle_levels_command(
                object(),
                "TOKEN",
                "777",
                "/snapshot",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            ),
            lambda: scanner.handle_research_command(
                object(),
                "TOKEN",
                "777",
                "/research",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            ),
            lambda: scanner.handle_whynot_command(
                object(),
                "TOKEN",
                "777",
                "/whynot",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            ),
            lambda: scanner.handle_whatnow_command(
                object(),
                "TOKEN",
                "777",
                "/whatnow",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            ),
            lambda: scanner.handle_unwatch_command(
                "TOKEN",
                "777",
                "/unwatch",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "missing_user_watchlists.json"
        ), patch.object(scanner, "send_telegram_message") as send_message:
            for command_call in command_calls:
                command_call()

        for call in send_message.call_args_list:
            self.assertNotIn("Use: /", call.args[2])

    def test_coin_picker_routes_to_correct_handler_per_target(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }

        with patch.object(scanner, "answer_telegram_callback"), patch.object(
            scanner, "clear_callback_message_keyboard"
        ), patch.object(scanner, "handle_watch_command") as watch_handler:
            self.assertTrue(scanner.handle_coin_pick_callback("TOKEN", callback_query, "watch:BTC", exchange=object()))
        watch_handler.assert_called_once()
        self.assertEqual(watch_handler.call_args.args[3], "/watch BTC")

    def test_coin_picker_heavy_targets_go_through_job_queue(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }

        for target, action, command in (
            ("whynot", "whynot", "/whynot BTC"),
            ("whatnow", "whatnow", "/whatnow BTC"),
            ("fakeout", "explain", "/explain confirmation BTC"),
            ("research", "research", "/research BTC"),
            ("snapshot", "snapshot", "/snapshot BTC"),
        ):
            with self.subTest(target=target), patch.object(scanner, "answer_telegram_callback"), patch.object(
                scanner, "clear_callback_message_keyboard"
            ), patch.object(scanner, "enqueue_telegram_command_job", return_value=True) as enqueue_job, patch.object(
                scanner, "send_heavy_job_acknowledgment"
            ) as send_ack:
                handled = scanner.handle_coin_pick_callback("TOKEN", callback_query, f"{target}:BTC", exchange=object())

            self.assertTrue(handled)
            enqueue_job.assert_called_once()
            self.assertEqual(enqueue_job.call_args.args[:3], (action, "777", command))
            send_ack.assert_called_once()

    def test_whatnow_heavy_job_executes_whatnow_card(self):
        class FakeExchange:
            def load_markets(self):
                return {"BTC/USD": {}}

        sent_messages = []
        job = {
            "action": "whatnow",
            "telegram_chat_id": "777",
            "message_text": "/whatnow BTC",
            "source_chat": {"id": "777", "type": "private"},
            "from_user": {"id": 777},
        }

        with patch.object(scanner, "scan_symbol", return_value=self.whynot_scan_result()), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
        ), patch.object(
            scanner, "handle_levels_command", side_effect=AssertionError("whatnow job must not execute snapshot")
        ):
            handled = scanner.run_telegram_command_job(FakeExchange(), "TOKEN", job, state={})

        self.assertTrue(handled)
        self.assertEqual(sent_messages[0][0], "777")
        self.assertTrue(sent_messages[0][1].startswith("<b>I can't make that decision for you.</b>"))
        self.assertIn("Nothing has broken. Nothing has confirmed.", sent_messages[0][1])

    def test_coin_picker_type_fallback_is_not_the_primary_whynot_action(self):
        keyboard = scanner.target_coin_picker_keyboard("whynot")
        callbacks = [
            button["callback_data"]
            for row in keyboard["inline_keyboard"]
            for button in row
        ]

        self.assertIn("coinpick:whynot:BTC", callbacks)
        self.assertEqual(callbacks[-2], "coinpick:whynot:__type__")
        self.assertEqual(callbacks[-1], "panel:open")
        self.assertNotIn("Use: /whynot BTC", scanner.start_orientation_text())

    def test_coin_picker_shows_user_watchlist_first_then_popular(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = Path(tmpdir) / "user_watchlists.json"
            watchlist_path.write_text(json.dumps({"777": ["TAO/USD", "SOL/USD", "BTC/USD"]}))
            with patch.object(scanner, "USER_WATCHLISTS_FILE", watchlist_path):
                keyboard = scanner.target_coin_picker_keyboard("whynot", user_id="777")

        first_buttons = [
            button["text"]
            for row in keyboard["inline_keyboard"]
            for button in row
            if button["callback_data"].startswith("coinpick:whynot:")
        ][:5]

        self.assertEqual(first_buttons[:3], ["TAO", "SOL", "BTC"])
        self.assertEqual(first_buttons[3:5], ["ETH", "XRP"])

    def test_coin_picker_uses_popular_list_without_watchlist(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "missing_user_watchlists.json"
        ):
            keyboard = scanner.target_coin_picker_keyboard("whynot", user_id="777")

        first_buttons = [
            button["text"]
            for row in keyboard["inline_keyboard"]
            for button in row
            if button["callback_data"].startswith("coinpick:whynot:")
        ][:4]

        self.assertEqual(first_buttons, ["BTC", "ETH", "SOL", "XRP"])

    def test_terminal_coin_picker_button_clears_keyboard(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
            "from": {"id": 777},
        }
        sent_messages = []

        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner, "clear_callback_message_keyboard"
        ) as clear_keyboard, patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            handled = scanner.handle_coin_pick_callback("TOKEN", callback_query, "whynot:__type__", exchange=object())

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        clear_keyboard.assert_called_once_with("TOKEN", callback_query)
        self.assertEqual(sent_messages, [("777", "Send /whynot <COIN> for any coin I track.", None)])

    def test_addcreator_rejects_non_owner_with_reply(self):
        sent_messages = []

        with patch.object(scanner, "configured_owner_ids", return_value={"777"}), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_addcreator_command(
                "TOKEN",
                "999",
                "/addcreator mike_knows | Mike Knows | The Inner Circle | telegram:@MikeKnows_Official",
                from_user={"id": 123},
            )

        self.assertEqual(sent_messages, [("999", "That command isn't available.")])

    def test_addcreator_without_args_replies_with_usage(self):
        sent_messages = []

        with patch.object(scanner, "configured_owner_ids", return_value={"777"}), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_addcreator_command("TOKEN", "999", "/addcreator", from_user={"id": 777})

        self.assertEqual(sent_messages, [("999", scanner.addcreator_usage_text())])

    def test_addcreator_too_few_pipe_fields_replies_with_usage_and_count(self):
        sent_messages = []

        with patch.object(scanner, "configured_owner_ids", return_value={"777"}), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_addcreator_command("TOKEN", "999", "/addcreator test_creator", from_user={"id": 777})

        self.assertIn(scanner.addcreator_usage_text(), sent_messages[0][1])
        self.assertIn("Received 1 field; expected 4.", sent_messages[0][1])

    def test_addcreator_empty_field_replies_with_missing_field_name(self):
        sent_messages = []

        with patch.object(scanner, "configured_owner_ids", return_value={"777"}), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_addcreator_command(
                "TOKEN",
                "999",
                "/addcreator mike_knows |  | The Inner Circle | @MikeKnows_Official",
                from_user={"id": 777},
            )

        self.assertIn("Missing: display_name.", sent_messages[0][1])

    def test_addcreator_bad_handle_replies_with_handle_error(self):
        sent_messages = []

        with patch.object(scanner, "configured_owner_ids", return_value={"777"}), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_addcreator_command(
                "TOKEN",
                "999",
                "/addcreator mike_knows | Mike Knows | The Inner Circle | telegram:",
                from_user={"id": 777},
            )

        self.assertIn("Malformed account: telegram:", sent_messages[0][1])

    def test_addcreator_unknown_platform_replies_with_valid_platforms(self):
        sent_messages = []

        with patch.object(scanner, "configured_owner_ids", return_value={"777"}), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_addcreator_command(
                "TOKEN",
                "999",
                "/addcreator mike_knows | Mike Knows | The Inner Circle | myspace:@MikeKnows",
                from_user={"id": 777},
            )

        self.assertIn("Unknown platform: myspace.", sent_messages[0][1])
        self.assertIn("Valid platforms: telegram, tiktok, youtube, x, instagram, discord, website", sent_messages[0][1])

    def test_addcreator_writes_creator_and_then_verifies(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "configured_owner_ids", return_value={"777"}
            ), patch.object(scanner, "EASTERN_TIME", scanner.ZoneInfo("America/New_York")), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_addcreator_command(
                    "TOKEN",
                    "999",
                    "/addcreator mike_knows | Mike Knows | The Inner Circle | telegram:@MikeKnows_Official",
                    from_user={"id": 777},
                )
                creators = scanner.load_creators()
                scanner.handle_verify_command("TOKEN", "999", "/verify mikeknows_official")

        self.assertEqual(creators["mike_knows"]["display_name"], "Mike Knows")
        self.assertEqual(creators["mike_knows"]["community"], "The Inner Circle")
        self.assertEqual(creators["mike_knows"]["accounts"], [{"platform": "telegram", "handle": "@MikeKnows_Official"}])
        self.assertRegex(creators["mike_knows"]["registered_at"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn("Added Mike Knows in the creator registry", sent_messages[0][1])
        self.assertIn("✅ <b>VERIFIED</b>", sent_messages[1][1])

    def test_removecreator_unknown_key_replies_with_registered_keys(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
                "registered_at": "2026-07-13",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "configured_owner_ids", return_value={"777"}
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_removecreator_command("TOKEN", "999", "/removecreator missing", from_user={"id": 777})

        self.assertIn("Unknown creator key: missing.", sent_messages[0][1])
        self.assertIn("Registered keys: mike_knows", sent_messages[0][1])

    def test_removecreator_success_removes_creator_and_confirms(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
                "registered_at": "2026-07-13",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "configured_owner_ids", return_value={"777"}
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_removecreator_command("TOKEN", "999", "/removecreator mike_knows", from_user={"id": 777})
                remaining_creators = scanner.load_creators()

        self.assertEqual(remaining_creators, {})
        self.assertEqual(sent_messages, [("999", "Removed Mike Knows from the creator registry.")])

    def test_addcreator_and_removecreator_paths_all_reply(self):
        creator_payload = "mike_knows | Mike Knows | The Inner Circle | telegram:@MikeKnows_Official"
        add_commands = [
            "/addcreator",
            "/addcreator test_creator",
            "/addcreator  | Mike Knows | The Inner Circle | @MikeKnows_Official",
            "/addcreator mike_knows |  | The Inner Circle | @MikeKnows_Official",
            "/addcreator mike_knows | Mike Knows |  | @MikeKnows_Official",
            "/addcreator mike_knows | Mike Knows | The Inner Circle | ",
            "/addcreator mike_knows | Mike Knows | The Inner Circle | telegram:",
            f"/addcreator {creator_payload}",
        ]
        remove_commands = [
            "/removecreator",
            "/removecreator missing",
            "/removecreator mike_knows",
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text("{}")
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "configured_owner_ids", return_value={"777"}
            ):
                for command in add_commands:
                    sent_messages = []
                    with patch.object(
                        scanner,
                        "send_telegram_message",
                        side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                            (str(chat_id), text)
                        ),
                    ):
                        scanner.handle_addcreator_command("TOKEN", "999", command, from_user={"id": 777})
                    self.assertEqual(len(sent_messages), 1, command)

                for command in remove_commands:
                    sent_messages = []
                    with patch.object(
                        scanner,
                        "send_telegram_message",
                        side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                            (str(chat_id), text)
                        ),
                    ):
                        scanner.handle_removecreator_command("TOKEN", "999", command, from_user={"id": 777})
                    self.assertEqual(len(sent_messages), 1, command)

    def test_process_telegram_commands_replies_on_first_poll(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 123,
                "message": {
                    "chat": {"id": "999"},
                    "text": "/snapshot BTC",
                },
            }
        ]

        def fake_handle(exchange, token, chat_id, text, source_chat=None, from_user=None):
            sent_messages.append(
                (
                    chat_id,
                    text,
                    scanner.normalize_symbol(text.split()[1]),
                    source_chat,
                    from_user,
                )
            )

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "handle_levels_command", side_effect=fake_handle
        ), patch.object(
            scanner, "command_allowed_by_active_mode", return_value=True
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(sent_messages[0][0:3], ("999", "/snapshot BTC", "BTC/USD"))
        self.assertEqual(state["__telegram_commands"]["last_update_id"], 123)

    def test_process_telegram_commands_routes_research_command(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 124,
                "message": {
                    "chat": {"id": "999"},
                    "text": "/research eth",
                },
            }
        ]

        def fake_handle(exchange, token, chat_id, text, source_chat=None, from_user=None):
            sent_messages.append(
                (
                    chat_id,
                    text,
                    scanner.normalize_symbol(text.split()[1]),
                    source_chat,
                )
            )

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "handle_research_command", side_effect=fake_handle
        ), patch.object(
            scanner, "command_allowed_by_active_mode", return_value=True
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(sent_messages[0][0:3], ("999", "/research eth", "ETH/USD"))
        self.assertEqual(state["__telegram_commands"]["last_update_id"], 124)

    def test_process_telegram_commands_routes_whatnow_to_refusal_card(self):
        class FakeExchange:
            def load_markets(self):
                return {"BTC/USD": {}}

        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 125,
                "message": {
                    "chat": {"id": "999", "type": "private"},
                    "from": {"id": 999},
                    "text": "/whatnow BTC",
                },
            }
        ]

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "scan_symbol", return_value=self.whynot_scan_result()
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
        ), patch.object(
            scanner, "handle_levels_command", side_effect=AssertionError("/whatnow must not route to snapshot")
        ), patch.object(
            scanner, "command_allowed_by_active_mode", return_value=True
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(FakeExchange(), "TOKEN", "999", state)

        self.assertEqual(sent_messages[0][0], "999")
        self.assertTrue(sent_messages[0][1].startswith("<b>I can't make that decision for you.</b>"))
        self.assertIn("Nearest support: 95.00  (5.0% below)", sent_messages[0][1])
        self.assertEqual(state["__telegram_commands"]["last_update_id"], 125)

    def test_process_telegram_commands_routes_scan_and_status_for_owner(self):
        cases = (
            ("/scan", "scan"),
            ("/status", "status"),
        )
        for index, (command, expected_handler) in enumerate(cases, start=224):
            state = {}
            updates = [
                {
                    "update_id": index,
                    "message": {
                        "chat": {"id": "999", "type": "private"},
                        "from": {"id": 999},
                        "text": command,
                    },
                }
            ]

            with self.subTest(command=command), patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
                scanner, "is_owner_user", return_value=True
            ), patch.object(scanner, "handle_scan_command") as scan_handler, patch.object(
                scanner, "handle_status_command"
            ) as status_handler, patch.object(
                scanner, "command_allowed_by_active_mode", return_value=True
            ), patch.object(scanner, "save_state"):
                scanner.process_telegram_commands(object(), "TOKEN", "999", state)

            if expected_handler == "scan":
                scan_handler.assert_called_once()
                status_handler.assert_not_called()
            else:
                status_handler.assert_called_once()
                scan_handler.assert_not_called()
            self.assertEqual(state["__telegram_commands"]["last_update_id"], index)

    def test_process_telegram_commands_hides_scan_and_status_from_non_owner(self):
        for index, command in enumerate(("/scan", "/status"), start=226):
            state = {}
            sent_messages = []
            updates = [
                {
                    "update_id": index,
                    "message": {
                        "message_id": index,
                        "chat": {"id": "999", "type": "private"},
                        "from": {"id": 999},
                        "text": command,
                    },
                }
            ]

            with self.subTest(command=command), patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
                scanner, "is_owner_user", return_value=False
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
            ), patch.object(
                scanner, "command_allowed_by_active_mode", return_value=True
            ), patch.object(scanner, "save_state"):
                scanner.process_telegram_commands(object(), "TOKEN", "999", state)

            self.assertEqual(sent_messages, [("999", scanner.start_orientation_text(), scanner.start_orientation_keyboard())])
            self.assertNotIn("owner", sent_messages[0][1].lower())
            self.assertEqual(state["__telegram_commands"]["last_update_id"], index)

    def test_skill_onboarding_message_sends_once_for_group_snapshot(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(
            scanner,
            "build_levels_command_message",
            return_value="BTC snapshot",
        ), patch.object(scanner, "send_levels_chart", return_value=False), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            for _ in range(2):
                scanner.handle_levels_command(
                    object(),
                    "TOKEN",
                    "-100",
                    "/snapshot BTC",
                    source_chat={"id": "-100", "type": "group"},
                    from_user={"id": 777},
                )

        prompts = [text for chat_id, text in sent_messages if chat_id == "777" and "quick one before we go further" in text]
        self.assertEqual(len(prompts), 1)
        self.assertIn("Still getting my bearings", prompts[0])
        self.assertIn("This already makes sense to me", prompts[0])

    def test_skill_level_reply_stores_profile(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 125,
                "message": {
                    "chat": {"id": "777", "type": "private"},
                    "from": {"id": 777},
                    "text": "Still getting my bearings",
                },
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)
            profiles = scanner.load_user_profiles()

        self.assertEqual(profiles["777"]["skill_level"], "beginner")
        self.assertEqual(sent_messages, [("777", "Got it. I’ll keep the chart notes a little more plain-language.")])

    def test_explain_concept_uses_skill_level_and_aliases(self):
        beginner = scanner.explain_concept("relative strength", "beginner")
        experienced = scanner.explain_concept("RSI", "experienced")

        self.assertIn("reading, not a signal", beginner)
        self.assertIn("momentum reading", experienced)
        self.assertEqual(scanner.normalize_concept_key("moving average"), "ema")
        self.assertIsNone(scanner.explain_concept("not-a-real-concept", "beginner"))

    def test_explain_concept_normalizes_case_whitespace_and_friendly_terms(self):
        self.assertEqual(scanner.normalize_concept_key("RSI"), "rsi")
        self.assertEqual(scanner.normalize_concept_key("Rsi"), "rsi")
        self.assertEqual(scanner.normalize_concept_key("rsi"), "rsi")
        self.assertEqual(scanner.normalize_concept_key(" ema "), "ema")
        self.assertEqual(scanner.normalize_concept_key("Support"), "support")
        self.assertEqual(scanner.normalize_concept_key("volume spike"), "volume_spike")
        self.assertIn("cannot fire an alert", scanner.explain_concept(" RSI ", "beginner"))
        self.assertIsNone(scanner.explain_concept("mystery term", "beginner"))

    def test_new_explanation_concepts_resolve_for_beginner_and_experienced(self):
        expected_phrases = {
            "confirmation": ("Real breakout or fakeout?", "Real breakout or fakeout?"),
            "candle": ("one chunk of time", "OHLC for one period"),
            "range": ("box", "price bounded between horizontal support and resistance"),
            "key_level": ("A price that matters", "price with a history of reaction"),
            "liquidity": ("lots of buyers and sellers", "depth of available buy/sell orders"),
        }

        for concept, (beginner_phrase, experienced_phrase) in expected_phrases.items():
            with self.subTest(concept=concept):
                self.assertIn(beginner_phrase, scanner.explain_concept(concept, "beginner"))
                self.assertIn(experienced_phrase, scanner.explain_concept(concept, "experienced"))

    def test_new_explanation_aliases_resolve(self):
        self.assertEqual(scanner.normalize_concept_key("confirmed break"), "confirmation")
        for alias in ("fakeout", "fake breakout", "real breakout", "false breakout"):
            with self.subTest(alias=alias):
                self.assertEqual(scanner.normalize_concept_key(alias), "confirmation")
        self.assertEqual(scanner.normalize_concept_key("candlestick"), "candle")
        self.assertEqual(scanner.normalize_concept_key("body"), "candle")
        self.assertEqual(scanner.normalize_concept_key("range bound"), "range")
        self.assertEqual(scanner.normalize_concept_key("key level"), "key_level")
        self.assertEqual(scanner.normalize_concept_key("zone"), "key_level")
        self.assertEqual(scanner.normalize_concept_key("illiquid"), "liquidity")

    def test_dominance_explanation_aliases_resolve(self):
        aliases = (
            "dominance",
            "btc.d",
            "btcd",
            "btc dominance",
            "bitcoin dominance",
            "usdt.d",
            "usdtd",
            "usdt dominance",
            "tether dominance",
            "market dominance",
            "alt season",
            "altseason",
        )

        for alias in aliases:
            with self.subTest(alias=alias):
                self.assertEqual(scanner.normalize_concept_key(alias), "dominance")

    def test_explain_dominance_returns_card_for_aliases(self):
        aliases = ("dominance", "btc.d", "btc dominance", "usdt.d", "altseason")

        with patch.object(scanner, "fetch_coingecko_global_data", return_value=None):
            for alias in aliases:
                with self.subTest(alias=alias):
                    message = scanner.build_explain_command_message(f"/explain {alias}")
                    self.assertIn("<b>Dominance</b>", message)
                    self.assertIn("<b>WHAT IT IS</b>", message)
                    self.assertIn("<b>HONEST LIMITS</b>", message)

    def test_double_top_explanation_aliases_resolve(self):
        aliases = ("double top", "doubletop", "double-top", "dt", "m top", "m-top")

        for alias in aliases:
            with self.subTest(alias=alias):
                self.assertEqual(scanner.normalize_concept_key(alias), "double_top")

    def test_double_bottom_explanation_aliases_resolve(self):
        aliases = ("double bottom", "doublebottom", "double-bottom", "db", "w bottom", "w-bottom")

        for alias in aliases:
            with self.subTest(alias=alias):
                self.assertEqual(scanner.normalize_concept_key(alias), "double_bottom")

    def test_neckline_explanation_aliases_resolve(self):
        aliases = ("neckline", "neck line", "neck-line")

        for alias in aliases:
            with self.subTest(alias=alias):
                self.assertEqual(scanner.normalize_concept_key(alias), "neckline")

    def test_flag_explanation_aliases_resolve(self):
        expected = {
            "bull_flag": ("bull flag", "bullflag", "bull-flag"),
            "bear_flag": ("bear flag", "bearflag", "bear-flag"),
        }

        for concept_key, aliases in expected.items():
            for alias in aliases:
                with self.subTest(alias=alias):
                    self.assertEqual(scanner.normalize_concept_key(alias), concept_key)

    def test_explain_double_top_returns_card_for_aliases(self):
        aliases = ("double top", "doubletop", "double-top", "dt", "m top", "m-top")

        for alias in aliases:
            with self.subTest(alias=alias):
                message = scanner.build_explain_command_message(f"/explain {alias}")
                self.assertIn("<b>Double Top</b>", message)
                self.assertIn("<b>WHAT IT IS</b>", message)
                self.assertIn("<b>WHAT CONFIRMS IT</b>", message)
                self.assertIn("<b>HONEST LIMIT</b>", message)

    def test_explain_double_bottom_returns_card_for_aliases(self):
        aliases = ("double bottom", "doublebottom", "double-bottom", "db", "w bottom", "w-bottom")

        for alias in aliases:
            with self.subTest(alias=alias):
                message = scanner.build_explain_command_message(f"/explain {alias}")
                self.assertIn("<b>Double Bottom</b>", message)
                self.assertIn("<b>WHAT IT IS</b>", message)
                self.assertIn("<b>WHAT CONFIRMS IT</b>", message)
                self.assertIn("<b>HONEST LIMIT</b>", message)

    def test_explain_neckline_returns_card_for_aliases(self):
        aliases = ("neckline", "neck line", "neck-line")

        for alias in aliases:
            with self.subTest(alias=alias):
                message = scanner.build_explain_command_message(f"/explain {alias}")
                self.assertIn("<b>Neckline</b>", message)
                self.assertIn("<b>WHAT IT IS</b>", message)
                self.assertIn("<b>WHAT CONFIRMS IT</b>", message)
                self.assertIn("<b>HONEST LIMIT</b>", message)

    def test_explain_flag_cards_return_for_aliases(self):
        expected = {
            "Bull Flag": ("bull flag", "bullflag", "bull-flag"),
            "Bear Flag": ("bear flag", "bearflag", "bear-flag"),
        }

        for display_name, aliases in expected.items():
            for alias in aliases:
                with self.subTest(alias=alias):
                    message = scanner.build_explain_command_message(f"/explain {alias}")
                    self.assertIn(f"<b>{display_name}</b>", message)
                    self.assertIn("<b>WHAT IT IS</b>", message)
                    self.assertIn("<b>WHAT CONFIRMS IT</b>", message)
                    self.assertIn("<b>HONEST LIMIT</b>", message)

    def test_double_top_card_avoids_pattern_banned_language(self):
        message = scanner.build_explain_command_message("/explain double top").lower()
        banned_phrases = (
            "will",
            "expect",
            "likely",
            "signals",
            "indicates",
            "means price",
            "going to",
            "continuation",
            "downside probability",
            "reversal",
            "bearish",
            "target",
        )

        for banned_phrase in banned_phrases:
            with self.subTest(banned_phrase=banned_phrase):
                self.assertNotIn(banned_phrase, message)
        for banned_word in ("buy", "sell", "enter", "exit", "long", "short"):
            with self.subTest(banned_word=banned_word):
                self.assertIsNone(re.search(rf"\b{banned_word}\b", message))
        self.assertIn("double top", message)
        self.assertNotIn("top", banned_phrases)
        self.assertNotIn("bottom", banned_phrases)

    def test_double_bottom_card_avoids_pattern_banned_language(self):
        message = scanner.build_explain_command_message("/explain double bottom").lower()
        banned_phrases = (
            "will",
            "expect",
            "likely",
            "signals",
            "indicates",
            "means price",
            "going to",
            "continuation",
            "upside probability",
            "reversal",
            "bullish",
            "target",
        )

        for banned_phrase in banned_phrases:
            with self.subTest(banned_phrase=banned_phrase):
                self.assertNotIn(banned_phrase, message)
        for banned_word in ("buy", "sell", "enter", "exit", "long", "short"):
            with self.subTest(banned_word=banned_word):
                self.assertIsNone(re.search(rf"\b{banned_word}\b", message))
        self.assertIn("double bottom", message)
        self.assertNotIn("top", banned_phrases)
        self.assertNotIn("bottom", banned_phrases)

    def test_neckline_card_avoids_pattern_banned_language(self):
        message = scanner.build_explain_command_message("/explain neckline").lower()
        banned_phrases = (
            "will",
            "expect",
            "likely",
            "signals",
            "indicates",
            "means price",
            "going to",
            "continuation",
            "probability",
            "reversal",
            "bullish",
            "bearish",
            "target",
        )

        for banned_phrase in banned_phrases:
            with self.subTest(banned_phrase=banned_phrase):
                self.assertNotIn(banned_phrase, message)
        for banned_word in ("buy", "sell", "enter", "exit", "long", "short"):
            with self.subTest(banned_word=banned_word):
                self.assertIsNone(re.search(rf"\b{banned_word}\b", message))
        self.assertIn("double top", message)
        self.assertIn("double bottom", message)
        self.assertNotIn("top", banned_phrases)
        self.assertNotIn("bottom", banned_phrases)

    def test_bull_flag_card_avoids_pattern_banned_language(self):
        message = scanner.build_explain_command_message("/explain bull flag").lower()
        banned_phrases = (
            "will",
            "expect",
            "likely",
            "signals",
            "indicates",
            "means price",
            "going to",
            "continuation",
            "continues higher",
            "continues lower",
            "measured move",
            "flagpole target",
            "target",
            "probability",
            "reversal",
            "bullish",
            "bearish",
        )

        for banned_phrase in banned_phrases:
            with self.subTest(banned_phrase=banned_phrase):
                self.assertNotIn(banned_phrase, message)
        for banned_word in ("buy", "sell", "enter", "exit", "long", "short"):
            with self.subTest(banned_word=banned_word):
                self.assertIsNone(re.search(rf"\b{banned_word}\b", message))
        self.assertIn("flag", message)
        self.assertIn("flagpole", message)
        self.assertNotIn("flag", banned_phrases)
        self.assertNotIn("flagpole", banned_phrases)
        self.assertIn("measured move", banned_phrases)
        self.assertIn("target", banned_phrases)

    def test_bear_flag_card_avoids_pattern_banned_language(self):
        message = scanner.build_explain_command_message("/explain bear flag").lower()
        banned_phrases = (
            "will",
            "expect",
            "likely",
            "signals",
            "indicates",
            "means price",
            "going to",
            "continuation",
            "continues higher",
            "continues lower",
            "measured move",
            "flagpole target",
            "target",
            "probability",
            "reversal",
            "bullish",
            "bearish",
        )

        for banned_phrase in banned_phrases:
            with self.subTest(banned_phrase=banned_phrase):
                self.assertNotIn(banned_phrase, message)
        for banned_word in ("buy", "sell", "enter", "exit", "long", "short"):
            with self.subTest(banned_word=banned_word):
                self.assertIsNone(re.search(rf"\b{banned_word}\b", message))
        self.assertIn("flag", message)
        self.assertIn("flagpole", message)
        self.assertNotIn("flag", banned_phrases)
        self.assertNotIn("flagpole", banned_phrases)
        self.assertIn("measured move", banned_phrases)
        self.assertIn("target", banned_phrases)

    def test_dominance_card_avoids_banned_language(self):
        with patch.object(scanner, "fetch_coingecko_global_data", return_value=None):
            message = scanner.build_explain_command_message("/explain dominance").lower()

        banned_phrases = (
            "will",
            "expect",
            "likely",
            "means alts",
            "alt season is",
            "rotate",
            "rotation into",
            "next leg",
            "signals that",
            "indicates that",
            "bullish",
            "bearish",
            "top",
            "bottom",
        )
        for banned_phrase in banned_phrases:
            with self.subTest(banned_phrase=banned_phrase):
                self.assertNotIn(banned_phrase, message)
        for banned_word in ("buy", "sell"):
            with self.subTest(banned_word=banned_word):
                self.assertIsNone(re.search(rf"\b{banned_word}\b", message))

    def test_dominance_live_block_renders_when_global_data_available(self):
        with patch.object(
            scanner,
            "fetch_coingecko_global_data",
            return_value={"btc_dominance": 62.345, "eth_dominance": 9.87, "usdt_dominance": 4.321},
        ):
            message = scanner.build_explain_command_message("/explain dominance")

        self.assertIn("<b>RIGHT NOW</b>", message)
        self.assertIn("BTC.D: 62.3%", message)
        self.assertIn("ETH.D: 9.9%", message)
        self.assertIn("USDT.D: 4.32%", message)

    def test_dominance_live_block_absent_when_global_data_missing(self):
        with patch.object(scanner, "fetch_coingecko_global_data", return_value=None):
            message = scanner.build_explain_command_message("/explain dominance")

        self.assertNotIn("<b>RIGHT NOW</b>", message)
        self.assertNotIn("0.0%", message)
        self.assertIn("<b>Dominance</b>", message)

    def test_coingecko_global_data_cache_uses_one_http_request_inside_ttl(self):
        payload = {
            "data": {
                "market_cap_percentage": {
                    "btc": 62.3,
                    "eth": 9.8,
                    "usdt": 4.2,
                }
            }
        }
        fake_session = FakeCoingeckoSession(payload)

        scanner.COINGECKO_GLOBAL_DATA_CACHE.clear()
        with patch.dict(os.environ, {"COINGECKO_API_KEY": "demo-key"}), patch.object(
            scanner, "requests", object()
        ), patch.object(scanner, "TELEGRAM_HTTP_SESSION", fake_session):
            first = scanner.fetch_coingecko_global_data()
            second = scanner.fetch_coingecko_global_data()
        scanner.COINGECKO_GLOBAL_DATA_CACHE.clear()

        self.assertEqual(first, second)
        self.assertEqual(first["btc_dominance"], 62.3)
        self.assertEqual(len(fake_session.gets), 1)
        self.assertTrue(fake_session.gets[0][0].endswith("/global"))
        self.assertEqual(fake_session.gets[0][1]["headers"], {"x-cg-demo-api-key": "demo-key"})

    def test_explain_dominance_uses_heavy_job_queue_without_live_chart_route(self):
        self.assertFalse(scanner.is_live_explain_command("/explain dominance"))
        self.assertEqual(scanner.heavy_command_action_for_text("/explain dominance"), "explain")
        self.assertTrue(scanner.should_enqueue_heavy_command("/explain dominance"))

    def test_explain_double_top_uses_heavy_job_queue_without_live_chart_route(self):
        self.assertFalse(scanner.is_live_explain_command("/explain double top"))
        self.assertEqual(scanner.heavy_command_action_for_text("/explain double top"), "explain")
        self.assertTrue(scanner.should_enqueue_heavy_command("/explain double top"))

    def test_explain_double_bottom_uses_heavy_job_queue_without_live_chart_route(self):
        self.assertFalse(scanner.is_live_explain_command("/explain double bottom"))
        self.assertEqual(scanner.heavy_command_action_for_text("/explain double bottom"), "explain")
        self.assertTrue(scanner.should_enqueue_heavy_command("/explain double bottom"))

    def test_explain_neckline_uses_heavy_job_queue_without_live_chart_route(self):
        self.assertFalse(scanner.is_live_explain_command("/explain neckline"))
        self.assertEqual(scanner.heavy_command_action_for_text("/explain neckline"), "explain")
        self.assertTrue(scanner.should_enqueue_heavy_command("/explain neckline"))

    def test_explain_flag_cards_use_heavy_job_queue_without_live_chart_route(self):
        for command in ("/explain bull flag", "/explain bear flag"):
            with self.subTest(command=command):
                self.assertFalse(scanner.is_live_explain_command(command))
                self.assertEqual(scanner.heavy_command_action_for_text(command), "explain")
                self.assertTrue(scanner.should_enqueue_heavy_command(command))

    def test_stage_three_explanation_concepts_resolve_for_beginner_and_experienced(self):
        expected_phrases = {
            "market_structure": ("overall shape of how price rises and falls", "sequence of swing highs/lows"),
            "accumulation": ("quietly stepping in over time", "building a position gradually"),
            "retest": ("comes back to test that level again", "price returns to a broken level"),
            "follow_through": ("What happens after a move or a break", "continuation after an initial move/break"),
        }

        for concept, (beginner_phrase, experienced_phrase) in expected_phrases.items():
            with self.subTest(concept=concept):
                self.assertIn(beginner_phrase, scanner.explain_concept(concept, "beginner"))
                self.assertIn(experienced_phrase, scanner.explain_concept(concept, "experienced"))

    def test_stage_three_explanation_aliases_resolve(self):
        self.assertEqual(scanner.normalize_concept_key("market structure"), "market_structure")
        self.assertEqual(scanner.normalize_concept_key("higher highs"), "market_structure")
        self.assertEqual(scanner.normalize_concept_key("accumulation zone"), "accumulation")
        self.assertEqual(scanner.normalize_concept_key("re-test"), "retest")
        self.assertEqual(scanner.normalize_concept_key("follow through"), "follow_through")
        self.assertIsNone(scanner.normalize_concept_key("trade plan"))
        self.assertIsNone(scanner.normalize_concept_key("stop loss"))

    def test_explain_command_sends_beginner_explanation_from_profile(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "user_profiles.json"
            profile_path.write_text(json.dumps({"777": {"skill_level": "beginner"}}))
            with patch.object(scanner, "USER_PROFILES_FILE", profile_path), patch.object(
                scanner, "ASSETS_DIR", Path(tmpdir) / "assets"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_explain_command(
                    "TOKEN",
                    "-100",
                    "/explain rsi",
                    source_chat={"id": "-100", "type": "group"},
                    from_user={"id": 777},
                )

        self.assertEqual(sent_messages[0][0], "-100")
        self.assertIn("<b>RSI</b>", sent_messages[0][1])
        self.assertIn("reading, not a signal", sent_messages[0][1])

    def test_explain_command_defaults_to_experienced_when_skill_missing(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain moving average",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )

        self.assertIn("<b>EMA</b>", sent_messages[0][1])
        self.assertIn("exponentially weighted moving average", sent_messages[0][1])

    def test_explain_command_sends_concept_card_with_caption_when_available(self):
        sent_photos = []
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = Path(tmpdir) / "assets"
            assets_dir.mkdir()
            card_path = assets_dir / "rsi.png"
            card_path.write_bytes(b"fake png")
            with patch.object(scanner, "ASSETS_DIR", assets_dir), patch.object(
                scanner,
                "send_telegram_photo",
                side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_explain_command(
                    "TOKEN",
                    "-100",
                    "/explain RSI",
                    source_chat={"id": "-100", "type": "group"},
                    from_user={"id": 777},
                )

        self.assertEqual(len(sent_photos), 1)
        self.assertEqual(sent_photos[0][0:2], ("-100", str(card_path)))
        self.assertIn("<b>RSI</b>", sent_photos[0][2])
        self.assertIn("momentum reading", sent_photos[0][2])
        self.assertEqual(sent_messages, [])

    def test_explain_command_sends_image_then_text_when_caption_is_too_long(self):
        sent_photos = []
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = Path(tmpdir) / "assets"
            assets_dir.mkdir()
            card_path = assets_dir / "rsi.png"
            card_path.write_bytes(b"fake png")
            long_message = "<b>RSI</b>\n\n" + ("Long explanation. " * 120)
            with patch.object(scanner, "ASSETS_DIR", assets_dir), patch.object(
                scanner, "build_explain_command_message", return_value=long_message
            ), patch.object(
                scanner,
                "send_telegram_photo",
                side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_explain_command(
                    "TOKEN",
                    "777",
                    "/explain rsi",
                    source_chat={"id": "777", "type": "private"},
                    from_user={"id": 777},
                )

        self.assertEqual(sent_photos, [("777", str(card_path), "")])
        self.assertEqual(sent_messages, [("777", long_message)])

    def test_concept_teaching_card_path_uses_short_filename_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = Path(tmpdir) / "assets"
            assets_dir.mkdir()
            for filename in ["rsi.png", "resist.png", "con.png", "volume.png"]:
                (assets_dir / filename).write_bytes(b"fake png")

            with patch.object(scanner, "ASSETS_DIR", assets_dir):
                self.assertEqual(scanner.concept_teaching_card_path("rsi"), assets_dir / "rsi.png")
                self.assertEqual(scanner.concept_teaching_card_path("resistance"), assets_dir / "resist.png")
                self.assertEqual(scanner.concept_teaching_card_path("confluence"), assets_dir / "con.png")
                self.assertEqual(scanner.concept_teaching_card_path("volume"), assets_dir / "volume.png")
                self.assertIsNone(scanner.concept_teaching_card_path("candle"))

    def test_explain_command_falls_back_to_text_when_no_concept_card_exists(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "ASSETS_DIR", Path(tmpdir) / "assets"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ), patch.object(
            scanner, "send_telegram_photo", side_effect=AssertionError("missing card should not send photo")
        ):
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain support",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )

        self.assertEqual(sent_messages[0][0], "777")
        self.assertIn("<b>Support</b>", sent_messages[0][1])

    def test_explain_command_lists_concepts_for_empty_or_unknown_term(self):
        menu = scanner.build_explain_command_message("/explain")
        unknown = scanner.build_explain_command_message("/explain mystery term")

        self.assertIn("Poinkle can explain these market concepts", menu)
        self.assertIn("Try: /explain rsi", menu)
        self.assertIn("I don't have that one yet", unknown)
        self.assertIn("breakout", unknown)

    def test_bare_explain_command_sends_group_picker(self):
        sent_messages = []

        with patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )

        self.assertEqual(sent_messages[0][0], "777")
        self.assertIn("What do you want to understand?", sent_messages[0][1])
        rows = sent_messages[0][2]["inline_keyboard"]
        self.assertEqual(len(rows), 8)
        self.assertEqual([len(row) for row in rows], [1, 1, 1, 1, 1, 1, 1, 1])
        self.assertEqual(rows[0][0]["callback_data"], "xgroup:0")
        self.assertEqual(rows[1][0]["text"], "📐 Chart Patterns")
        self.assertEqual(rows[1][0]["callback_data"], "xgroup:1")
        self.assertEqual(rows[-2][0]["callback_data"], "xgroup:6")
        self.assertEqual(rows[-1][0]["callback_data"], "panel:open")

    def test_explain_group_callback_sends_concepts_three_per_row(self):
        sent_messages = []
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ), patch.object(scanner, "clear_callback_message_keyboard") as clear_keyboard:
            handled = scanner.handle_explain_group_callback("TOKEN", callback_query, "0")

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        clear_keyboard.assert_not_called()
        rows = sent_messages[0][2]["inline_keyboard"]
        self.assertEqual([len(row) for row in rows], [3, 3, 1, 1])
        self.assertEqual(rows[0][0]["text"], "Candle")
        self.assertEqual(rows[0][0]["callback_data"], "xconcept:candle")
        self.assertEqual(rows[-2][0]["callback_data"], "xconcept:market_structure")
        self.assertEqual(rows[-1][0]["callback_data"], "xgroup:0")

    def test_explain_concept_callback_sends_existing_concept_response(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner, "send_explain_command_response"
        ) as send_response, patch.object(scanner, "clear_callback_message_keyboard") as clear_keyboard:
            handled = scanner.handle_explain_concept_callback("TOKEN", callback_query, "volume_spike")

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        clear_keyboard.assert_called_once_with("TOKEN", callback_query)
        self.assertEqual(send_response.call_args.args[0:2], ("TOKEN", "777"))
        self.assertIn("<b>Volume Spike</b>", send_response.call_args.args[2])
        self.assertEqual(send_response.call_args.kwargs["concept_key"], "volume_spike")

    def test_explain_dominance_callback_queues_heavy_job(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        scanner.TELEGRAM_COMMAND_JOB_QUEUE.clear()
        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner, "send_heavy_job_acknowledgment"
        ) as ack_job, patch.object(scanner, "send_explain_command_response") as send_response, patch.object(
            scanner, "clear_callback_message_keyboard"
        ) as clear_keyboard:
            handled = scanner.handle_explain_concept_callback("TOKEN", callback_query, "dominance")
        queued_job = scanner.TELEGRAM_COMMAND_JOB_QUEUE.popleft()

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        clear_keyboard.assert_called_once_with("TOKEN", callback_query)
        self.assertEqual(queued_job["action"], "explain")
        self.assertEqual(queued_job["message_text"], "/explain dominance")
        ack_job.assert_called_once_with("TOKEN", "777", "explain", "/explain dominance")
        send_response.assert_not_called()

    def test_explain_double_top_callback_queues_heavy_job(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        scanner.TELEGRAM_COMMAND_JOB_QUEUE.clear()
        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner, "send_heavy_job_acknowledgment"
        ) as ack_job, patch.object(scanner, "send_explain_command_response") as send_response, patch.object(
            scanner, "clear_callback_message_keyboard"
        ) as clear_keyboard:
            handled = scanner.handle_explain_concept_callback("TOKEN", callback_query, "double_top")
        queued_job = scanner.TELEGRAM_COMMAND_JOB_QUEUE.popleft()

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        clear_keyboard.assert_called_once_with("TOKEN", callback_query)
        self.assertEqual(queued_job["action"], "explain")
        self.assertEqual(queued_job["message_text"], "/explain double_top")
        ack_job.assert_called_once_with("TOKEN", "777", "explain", "/explain double_top")
        send_response.assert_not_called()

    def test_explain_double_bottom_callback_queues_heavy_job(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        scanner.TELEGRAM_COMMAND_JOB_QUEUE.clear()
        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner, "send_heavy_job_acknowledgment"
        ) as ack_job, patch.object(scanner, "send_explain_command_response") as send_response, patch.object(
            scanner, "clear_callback_message_keyboard"
        ) as clear_keyboard:
            handled = scanner.handle_explain_concept_callback("TOKEN", callback_query, "double_bottom")
        queued_job = scanner.TELEGRAM_COMMAND_JOB_QUEUE.popleft()

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        clear_keyboard.assert_called_once_with("TOKEN", callback_query)
        self.assertEqual(queued_job["action"], "explain")
        self.assertEqual(queued_job["message_text"], "/explain double_bottom")
        ack_job.assert_called_once_with("TOKEN", "777", "explain", "/explain double_bottom")
        send_response.assert_not_called()

    def test_explain_neckline_callback_queues_heavy_job(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        scanner.TELEGRAM_COMMAND_JOB_QUEUE.clear()
        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner, "send_heavy_job_acknowledgment"
        ) as ack_job, patch.object(scanner, "send_explain_command_response") as send_response, patch.object(
            scanner, "clear_callback_message_keyboard"
        ) as clear_keyboard:
            handled = scanner.handle_explain_concept_callback("TOKEN", callback_query, "neckline")
        queued_job = scanner.TELEGRAM_COMMAND_JOB_QUEUE.popleft()

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        clear_keyboard.assert_called_once_with("TOKEN", callback_query)
        self.assertEqual(queued_job["action"], "explain")
        self.assertEqual(queued_job["message_text"], "/explain neckline")
        ack_job.assert_called_once_with("TOKEN", "777", "explain", "/explain neckline")
        send_response.assert_not_called()

    def test_explain_flag_callbacks_queue_heavy_job(self):
        callback_query = {
            "id": "callback-1",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        for concept_key in ("bull_flag", "bear_flag"):
            with self.subTest(concept_key=concept_key):
                scanner.TELEGRAM_COMMAND_JOB_QUEUE.clear()
                with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
                    scanner, "send_heavy_job_acknowledgment"
                ) as ack_job, patch.object(scanner, "send_explain_command_response") as send_response, patch.object(
                    scanner, "clear_callback_message_keyboard"
                ) as clear_keyboard:
                    handled = scanner.handle_explain_concept_callback("TOKEN", callback_query, concept_key)
                queued_job = scanner.TELEGRAM_COMMAND_JOB_QUEUE.popleft()

                self.assertTrue(handled)
                answer_callback.assert_called_once_with("TOKEN", "callback-1")
                clear_keyboard.assert_called_once_with("TOKEN", callback_query)
                self.assertEqual(queued_job["action"], "explain")
                self.assertEqual(queued_job["message_text"], f"/explain {concept_key}")
                ack_job.assert_called_once_with("TOKEN", "777", "explain", f"/explain {concept_key}")
                send_response.assert_not_called()

    def test_same_picker_button_double_tap_sends_once_and_acks_second_tap(self):
        state = {}
        sent_messages = []
        acked_callbacks = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
                "registered_at": "2026-07-13",
            }
        }
        updates = [
            {
                "update_id": 201,
                "callback_query": {
                    "id": "callback-1",
                    "data": "verifycreator:mike_knows",
                    "message": {"chat": {"id": "777"}, "message_id": 44},
                    "from": {"id": 777},
                },
            },
            {
                "update_id": 202,
                "callback_query": {
                    "id": "callback-2",
                    "data": "verifycreator:mike_knows",
                    "message": {"chat": {"id": "777"}, "message_id": 44},
                    "from": {"id": 777},
                },
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "get_telegram_updates", return_value=updates
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((chat_id, text)),
            ), patch.object(
                scanner,
                "answer_telegram_callback",
                side_effect=lambda token, callback_id, text="": acked_callbacks.append((callback_id, text)),
            ), patch.object(scanner, "clear_callback_message_keyboard", return_value=True), patch.object(
                scanner, "save_state"
            ):
                scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(acked_callbacks, [("callback-1", ""), ("callback-2", "")])

    def test_terminal_callback_keyboard_clears_before_card_is_sent(self):
        events = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
                "registered_at": "2026-07-13",
            }
        }
        callback_query = {
            "id": "callback-1",
            "data": "verifyhandle:mike_knows:0",
            "message": {"chat": {"id": "777"}, "message_id": 44},
            "from": {"id": 777},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "answer_telegram_callback", side_effect=lambda *args, **kwargs: events.append("ack")
            ), patch.object(
                scanner, "clear_callback_message_keyboard", side_effect=lambda *args, **kwargs: events.append("clear")
            ), patch.object(
                scanner, "send_telegram_message", side_effect=lambda *args, **kwargs: events.append("send")
            ):
                handled = scanner.handle_verify_handle_callback("TOKEN", callback_query, "mike_knows:0")

        self.assertTrue(handled)
        self.assertEqual(events, ["ack", "clear", "send"])

    def test_different_buttons_on_same_message_are_independently_tappable(self):
        state = {}
        updates = [
            {
                "update_id": 211,
                "callback_query": {
                    "id": "callback-1",
                    "data": "xconcept:rsi",
                    "message": {"chat": {"id": "777"}, "message_id": 44},
                    "from": {"id": 777},
                },
            },
            {
                "update_id": 212,
                "callback_query": {
                    "id": "callback-2",
                    "data": "xconcept:ema",
                    "message": {"chat": {"id": "777"}, "message_id": 44},
                    "from": {"id": 777},
                },
            },
        ]

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "handle_telegram_callback_query", return_value=True
        ) as handle_callback, patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(handle_callback.call_count, 2)

    def test_same_button_on_new_picker_message_works_normally(self):
        state = {}
        updates = [
            {
                "update_id": 221,
                "callback_query": {
                    "id": "callback-1",
                    "data": "verifycreator:mike_knows",
                    "message": {"chat": {"id": "777"}, "message_id": 44},
                    "from": {"id": 777},
                },
            },
            {
                "update_id": 222,
                "callback_query": {
                    "id": "callback-2",
                    "data": "verifycreator:mike_knows",
                    "message": {"chat": {"id": "777"}, "message_id": 45},
                    "from": {"id": 777},
                },
            },
        ]

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "handle_telegram_callback_query", return_value=True
        ) as handle_callback, patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(handle_callback.call_count, 2)

    def test_double_tapping_new_onboard_button_dispatches_once(self):
        state = {}
        updates = [
            {
                "update_id": 231,
                "callback_query": {
                    "id": "callback-1",
                    "data": "onboard:beginner",
                    "message": {"chat": {"id": "777"}, "message_id": 44},
                    "from": {"id": 777},
                },
            },
            {
                "update_id": 232,
                "callback_query": {
                    "id": "callback-2",
                    "data": "onboard:beginner",
                    "message": {"chat": {"id": "777"}, "message_id": 44},
                    "from": {"id": 777},
                },
            },
        ]
        acked_callbacks = []

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "answer_telegram_callback", side_effect=lambda token, callback_id, text="": acked_callbacks.append(callback_id)
        ), patch.object(scanner, "handle_telegram_callback_query", return_value=True) as handle_callback, patch.object(
            scanner, "save_state"
        ):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(handle_callback.call_count, 1)
        self.assertEqual(acked_callbacks, ["callback-2"])

    def test_different_navigation_buttons_on_same_menu_all_work(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 241,
                "callback_query": {
                    "id": "callback-1",
                    "data": "panel:watch",
                    "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
                    "from": {"id": 777},
                },
            },
            {
                "update_id": 242,
                "callback_query": {
                    "id": "callback-2",
                    "data": "panel:open",
                    "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
                    "from": {"id": 777},
                },
            },
            {
                "update_id": 243,
                "callback_query": {
                    "id": "callback-3",
                    "data": "panel:explain",
                    "message": {"chat": {"id": "777", "type": "private"}, "message_id": 44},
                    "from": {"id": 777},
                },
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_WATCHLISTS_FILE", Path(tmpdir) / "missing_user_watchlists.json"
        ), patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "answer_telegram_callback"
        ), patch.object(scanner, "clear_callback_message_keyboard") as clear_keyboard, patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        clear_keyboard.assert_not_called()
        self.assertEqual(sent_messages[0][1], scanner.watch_toggle_picker_text())
        self.assertEqual(sent_messages[0][2]["inline_keyboard"][-1][0]["callback_data"], "panel:open")
        self.assertEqual(sent_messages[1], ("777", scanner.command_panel_text(), scanner.command_panel_keyboard()))
        self.assertEqual(sent_messages[2][1], scanner.explain_group_prompt())

    def test_every_explanation_registry_key_is_grouped_exactly_once(self):
        grouped_keys = [
            concept_key
            for _group_label, concept_keys in scanner.CONCEPT_GROUPS
            for concept_key in concept_keys
        ]

        self.assertEqual(set(grouped_keys), set(scanner.available_concepts()))
        self.assertEqual(len(grouped_keys), len(set(grouped_keys)))

    def test_double_top_appears_in_chart_patterns_picker_group(self):
        self.assertIn(
            ("📐 Chart Patterns", ("double_top", "double_bottom", "neckline", "bull_flag", "bear_flag")),
            scanner.CONCEPT_GROUPS,
        )

    def test_deweaponized_concepts_are_removed_from_registry_and_groups(self):
        grouped_keys = [
            concept_key
            for _group_label, concept_keys in scanner.CONCEPT_GROUPS
            for concept_key in concept_keys
        ]

        self.assertEqual(len(scanner.available_concepts()), 27)
        self.assertNotIn("trade_plan", scanner.available_concepts())
        self.assertNotIn("market_score", scanner.available_concepts())
        self.assertNotIn("trade_plan", grouped_keys)
        self.assertNotIn("market_score", grouped_keys)

    def test_all_explanation_concepts_include_honest_limit(self):
        for concept_key in scanner.available_concepts():
            for skill_level in ("beginner", "experienced"):
                with self.subTest(concept_key=concept_key, skill_level=skill_level):
                    explanation = scanner.explain_concept(concept_key, skill_level)
                    self.assertTrue(
                        "Honest limit" in explanation or "HONEST LIMIT" in explanation,
                        explanation,
                    )

    def test_indicator_explanations_do_not_imply_they_trigger_alerts(self):
        for concept_key in ("rsi", "ema", "volume_spike"):
            combined_text = " ".join(
                (
                    scanner.explain_concept(concept_key, "beginner"),
                    scanner.explain_concept(concept_key, "experienced"),
                )
            ).lower()
            with self.subTest(concept_key=concept_key):
                self.assertNotIn("trigger", combined_text)
                self.assertNotIn("can fire an alert", combined_text)
                self.assertIn("cannot fire an alert", combined_text)

    def test_typed_explain_concept_still_uses_existing_response_path(self):
        with patch.object(scanner, "send_explain_command_response") as send_response:
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain rsi",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )

        self.assertIn("<b>RSI</b>", send_response.call_args.args[2])
        self.assertEqual(send_response.call_args.kwargs["concept_key"], "rsi")

    def test_explain_fakeout_sends_confirmation_card(self):
        with patch.object(scanner, "send_explain_command_response") as send_response:
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain fakeout",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )

        self.assertIn("<b>Confirmation</b>", send_response.call_args.args[2])
        self.assertIn("Real breakout or fakeout?", send_response.call_args.args[2])
        self.assertIn("A fakeout is a break that never got its second close", send_response.call_args.args[2])
        self.assertEqual(send_response.call_args.kwargs["concept_key"], "confirmation")

    def test_live_explain_support_coin_sends_chart_and_support_caption(self):
        sent_photos = []
        snapshot = self.live_explain_snapshot(current_price=110)

        with patch.object(scanner, "validate_tradeable_symbol", return_value="BTC/USD") as validate_symbol, patch.object(
            scanner, "build_levels_scan_snapshot", return_value=snapshot
        ) as build_snapshot, patch.object(
            scanner, "live_explain_chart_path", return_value="/tmp/btc-support.png"
        ) as chart_path, patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
        ), patch.object(scanner, "send_explain_command_response") as static_response:
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain support BTC",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
                exchange=object(),
                state={},
            )

        validate_symbol.assert_called_once()
        build_snapshot.assert_called_once()
        chart_path.assert_called_once()
        self.assertEqual(chart_path.call_args.kwargs["teaching_zone"], "support")
        self.assertEqual(sent_photos[0][0:2], ("777", "/tmp/btc-support.png"))
        self.assertIn("<b>SUPPORT — on BTC, right now</b>", sent_photos[0][2])
        self.assertIn("nearest support zone", sent_photos[0][2])
        self.assertIn("Honest limit", sent_photos[0][2])
        static_response.assert_not_called()

    def test_live_explain_support_chart_uses_teaching_mode(self):
        snapshot = self.live_explain_snapshot(current_price=110)

        with patch.object(scanner, "generate_levels_chart", return_value="/tmp/live-teaching.png") as generate_chart:
            path = scanner.live_explain_chart_path(
                "BTC/USD",
                snapshot["chart_data"],
                "BTC / USD — SUPPORT",
                support_label="Nearest support",
                teaching_zone="support",
            )

        self.assertEqual(path, "/tmp/live-teaching.png")
        self.assertTrue(generate_chart.call_args.kwargs["teaching_mode"])
        self.assertEqual(generate_chart.call_args.kwargs["teaching_zone"], "support")
        self.assertEqual(generate_chart.call_args.kwargs["support_label"], "Nearest support")

    def test_live_explain_resistance_coin_sends_chart_and_resistance_caption(self):
        sent_photos = []
        snapshot = self.live_explain_snapshot(current_price=110)

        with patch.object(scanner, "validate_tradeable_symbol", return_value="BTC/USD"), patch.object(
            scanner, "build_levels_scan_snapshot", return_value=snapshot
        ), patch.object(
            scanner, "live_explain_chart_path", return_value="/tmp/btc-resistance.png"
        ) as chart_path, patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
        ):
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain resistance BTC",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
                exchange=object(),
                state={},
            )

        self.assertEqual(chart_path.call_args.kwargs["resistance_label"], "Nearest resistance")
        self.assertEqual(chart_path.call_args.kwargs["teaching_zone"], "resistance")
        self.assertEqual(sent_photos[0][0:2], ("777", "/tmp/btc-resistance.png"))
        self.assertIn("<b>RESISTANCE — on BTC, right now</b>", sent_photos[0][2])
        self.assertIn("nearest resistance zone", sent_photos[0][2])
        self.assertIn("Honest limit", sent_photos[0][2])

    def test_live_explain_confirmation_with_pending_setup_marks_attempt_caption(self):
        sent_photos = []
        snapshot = self.live_explain_snapshot(current_price=94)
        pending_setup = {
            "direction": "breakdown",
            "level": 95,
            "first_candle": snapshot["chart_data"]["candles"][3]["time"],
            "first_candle_close": 94,
            "expected_confirmation_candle": snapshot["chart_data"]["candles"][4]["time"],
        }
        state = {"BTC/USD": {"pending_setups": {"breakdown:95": pending_setup}}}

        with patch.object(scanner, "validate_tradeable_symbol", return_value="BTC/USD"), patch.object(
            scanner, "build_levels_scan_snapshot", return_value=snapshot
        ), patch.object(
            scanner, "live_explain_chart_path", return_value="/tmp/btc-confirmation.png"
        ) as chart_path, patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
        ):
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain confirmation BTC",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
                exchange=object(),
                state=state,
            )

        self.assertEqual(chart_path.call_args.kwargs["support_label"], "Attempt zone")
        self.assertEqual(chart_path.call_args.kwargs["chart_annotations"][0]["label"], "First close — attempt")
        self.assertEqual(chart_path.call_args.kwargs["teaching_zone"], "support")
        self.assertIn("BTC closed below the 95.00 zone once", sent_photos[0][2])
        self.assertIn("That's an ATTEMPT", sent_photos[0][2])
        self.assertIn("SECOND consecutive daily close", sent_photos[0][2])

    def test_live_explain_fakeout_alias_sends_confirmation_chart(self):
        sent_photos = []
        snapshot = self.live_explain_snapshot(current_price=94)
        pending_setup = {
            "direction": "breakdown",
            "level": 95,
            "first_candle": snapshot["chart_data"]["candles"][3]["time"],
            "first_candle_close": 94,
            "expected_confirmation_candle": snapshot["chart_data"]["candles"][4]["time"],
        }
        state = {"BTC/USD": {"pending_setups": {"breakdown:95": pending_setup}}}

        with patch.object(scanner, "validate_tradeable_symbol", return_value="BTC/USD"), patch.object(
            scanner, "build_levels_scan_snapshot", return_value=snapshot
        ), patch.object(
            scanner, "live_explain_chart_path", return_value="/tmp/btc-confirmation.png"
        ) as chart_path, patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
        ):
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain fakeout BTC",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
                exchange=object(),
                state=state,
            )

        self.assertEqual(chart_path.call_args.kwargs["chart_annotations"][0]["label"], "First close — attempt")
        self.assertEqual(chart_path.call_args.kwargs["teaching_zone"], "support")
        self.assertIn("BTC closed below the 95.00 zone once", sent_photos[0][2])
        self.assertIn("That's an ATTEMPT", sent_photos[0][2])

    def test_live_explain_confirmation_without_pending_setup_sends_no_setup_caption(self):
        sent_photos = []
        snapshot = self.live_explain_snapshot(current_price=110)

        with patch.object(scanner, "validate_tradeable_symbol", return_value="BTC/USD"), patch.object(
            scanner, "build_levels_scan_snapshot", return_value=snapshot
        ), patch.object(
            scanner, "live_explain_chart_path", return_value="/tmp/btc-confirmation.png"
        ) as chart_path, patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
        ):
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain confirmation BTC",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
                exchange=object(),
                state={},
            )

        self.assertEqual(chart_path.call_args.kwargs["chart_annotations"], [])
        self.assertIn("REAL BREAKOUT OR FAKEOUT", sent_photos[0][2])
        self.assertIn("BTC hasn't closed beyond a zone. There's nothing to confirm and nothing to fake.", sent_photos[0][2])
        self.assertIn("Nearest support", sent_photos[0][2])
        self.assertIn("Nearest resistance", sent_photos[0][2])
        self.assertIn("A break that never gets its second close is a FAKEOUT.", sent_photos[0][2])

    def test_teaching_reference_chart_keeps_prices_and_context_without_dashboard_footer(self):
        source = (PROJECT_DIR / "chart_generator_reference.py").read_text()

        self.assertIn("teaching_mode=False", source)
        self.assertIn("teaching_zone=None", source)
        self.assertIn("candle_limit = 70 if teaching_mode else 104", source)
        self.assertIn("if teaching_mode:\n        teaching_levels = near_supports[:2] + near_resistances[:2] + [current_price]", source)
        self.assertIn("y_min = max(visible_low - span * 0.045, 0)", source)
        self.assertIn("y_max = visible_high + span * 0.060", source)
        self.assertIn("[0.025, 0.095, 0.895, 0.805] if teaching_mode else [0.030, 0.330, 0.890, 0.420]", source)
        self.assertIn('chart_ax.yaxis.tick_right()', source)
        self.assertIn('labelsize=15.0', source)
        self.assertIn("x_right = len(recent) * 1.16 if teaching_mode else len(recent) * 1.12", source)
        self.assertIn("future_label_x", source)
        self.assertIn("if teaching_mode:\n        watermark_drawn = add_logo_watermark(chart_ax, opacity=0.06)", source)
        self.assertIn("else:\n        watermark_drawn = add_logo_watermark(chart_ax, opacity=0.05)", source)
        self.assertIn("image_height, image_width = image.shape[:2]", source)
        self.assertIn("image_aspect = image_width / max(image_height, 1)", source)
        self.assertIn("fig_w, fig_h = ax.figure.get_size_inches()", source)
        self.assertIn("ax_bbox = ax.get_position()", source)
        self.assertIn("axes_aspect = ax_w_in / max(ax_h_in, 0.0001)", source)
        self.assertIn("watermark_height = 0.68", source)
        self.assertIn("x_center, y_center = 0.50, 0.50", source)
        self.assertIn("extent=[x0, x1, y0, y1]", source)
        self.assertIn('aspect="auto"', source)
        self.assertIn("if not watermark_drawn:", source)
        self.assertIn("def level_bar(", source)
        self.assertIn('zorder=1', source)
        self.assertIn('label_x = start + max(1.0, len(recent) * 0.018) if taught else future_label_x', source)
        self.assertIn("level,\n                str(label),", source)
        self.assertIn('level_bar(level, resistance_thickness * 0.72, "#ff4d5a", 0.28', source)
        self.assertIn('level_bar(level, support_thickness * 0.72, "#34d978", 0.24', source)
        self.assertIn('level_bar(resistance_level, resistance_thickness, "#ff5260", 0.34', source)
        self.assertIn('level_bar(support_level, support_thickness, "#36e27b", 0.34', source)
        self.assertIn("chart_ax.set_yticks(teaching_ticks)", source)
        self.assertIn("format_price(current_price)", source)
        self.assertIn("chart_ax.hlines(current_price", source)
        self.assertIn('bbox={"boxstyle": "round,pad=0.22,rounding_size=0.08"', source)
        self.assertIn("wick_width = 1.15 if teaching_mode else 0.82", source)
        self.assertIn("body_width = 0.76 if teaching_mode else 0.54", source)
        footer_guard_index = source.index("if not teaching_mode:\n        arrows =")
        self.assertGreater(source.index("footer = fig.add_axes", footer_guard_index), footer_guard_index)
        self.assertGreater(source.index('"WHAT WOULD CHANGE THE PICTURE"', footer_guard_index), footer_guard_index)
        self.assertIn("One close is a hypothesis. Two is an answer.", source)
        self.assertIn("if not teaching_mode:\n        volume_ax = fig.add_axes", source)
        self.assertIn("if ema21_values and not teaching_mode:", source)
        self.assertIn("if teaching_mode:", source)
        self.assertIn("if teaching_zone == \"resistance\":", source)
        self.assertIn("def zone(level, thickness, color, alpha, start, end, label=None):", source)

    def test_snapshot_footer_uses_conditions_not_predictions(self):
        sources = {
            "chart_generator.py": (PROJECT_DIR / "chart_generator.py").read_text(),
            "chart_generator_reference.py": (PROJECT_DIR / "chart_generator_reference.py").read_text(),
        }

        for filename, source in sources.items():
            with self.subTest(filename=filename):
                self.assertIn("WHAT WOULD CHANGE THE PICTURE", source)
                self.assertIn("Close above", source)
                self.assertIn("A second close", source)
                self.assertIn("Close below", source)
                self.assertIn("One close is a hypothesis. Two is an answer.", source)
                self.assertIn('("WAIT", "Nothing here is a signal. You decide.")', source)
                self.assertNotIn('"EXECUTE PLAN"', source)
                self.assertIn("Keep Watching The Zones", source)
                for banned_phrase in (
                    "buyers step back in",
                    "next leg",
                    "trend stays healthy",
                    "step back in",
                    "can start",
                    "healthy",
                    "execute",
                    "demand",
                    "ready for next level",
                    "manage risk",
                    "see sweeps",
                ):
                    self.assertNotIn(banned_phrase, source.lower())

    def test_snapshot_reference_chart_draws_price_axis_and_current_price_tag(self):
        source = (PROJECT_DIR / "chart_generator_reference.py").read_text()

        self.assertIn("chart_ax.yaxis.tick_right()", source)
        self.assertIn("labelsize=15.0 if teaching_mode else 13.5", source)
        self.assertIn("raw_snapshot_ticks = sorted", source)
        self.assertIn("separated_snapshot_ticks(raw_snapshot_ticks, current_price, y_max - y_min)", source)
        self.assertIn("chart_ax.set_yticks(snapshot_ticks)", source)
        self.assertIn("chart_ax.set_yticklabels([format_price(value) for value in snapshot_ticks])", source)
        self.assertIn("for value in [support_level, mid_zone, resistance_level, current_price] + liq_levels[:4]", source)
        self.assertIn("chart_ax.hlines(\n            current_price,", source)
        self.assertIn("bbox={\"boxstyle\": \"round,pad=0.20,rounding_size=0.08\"", source)
        self.assertNotIn('if teaching_mode:\n        chart_ax.spines["left"].set_visible(False)', source)

    def test_snapshot_tick_filter_keeps_current_price_and_drops_close_levels(self):
        source = (PROJECT_DIR / "chart_generator_reference.py").read_text()

        self.assertIn("def separated_snapshot_ticks(values, current_price, y_span, min_fraction=0.035):", source)
        self.assertIn("min_gap = max(abs(y_span) * min_fraction", source)
        self.assertIn("0 if math.isclose(value, current_price", source)
        self.assertIn("if any(abs(value - existing) < min_gap for existing in kept):", source)
        self.assertIn("return sorted(kept), min_gap, len(values) - len(kept)", source)

    def test_snapshot_logo_watermark_uses_logo_with_text_fallback(self):
        source = (PROJECT_DIR / "chart_generator_reference.py").read_text()
        snapshot_branch = source[source.index("else:\n        watermark_drawn = add_logo_watermark(chart_ax, opacity=0.05)") :]
        snapshot_branch = snapshot_branch[: snapshot_branch.index("\n\n    level_ticks = []")]

        self.assertIn("watermark_drawn = add_logo_watermark(chart_ax, opacity=0.05)", snapshot_branch)
        self.assertIn("if not watermark_drawn:", snapshot_branch)
        self.assertIn('"POINKLE"', snapshot_branch)
        self.assertNotIn("add_ghost_watermark(chart_ax)", snapshot_branch)

    def test_snapshot_ema_labels_are_fixed_legend_not_price_tag_lane(self):
        source = (PROJECT_DIR / "chart_generator_reference.py").read_text()

        self.assertIn("def draw_ema_legend(ax, ema_specs):", source)
        self.assertIn("legend_x = 0.030", source)
        self.assertIn("legend_y = 0.925", source)
        self.assertIn("transform=ax.transAxes", source)
        self.assertIn("ema_label_specs.append((\"EMA 200\", \"#93c5fd\", ema200_values[-1]))", source)
        self.assertIn("ema_label_specs.append((\"EMA 55\", \"#e8c76a\", ema55_values[-1]))", source)
        self.assertIn("ema_label_specs.append((\"EMA 21\", \"#edf6fa\", ema21_values[-1]))", source)
        self.assertIn("draw_ema_legend(chart_ax, ema_label_specs)", source)
        self.assertNotIn("len(recent) + max(2.0, len(recent) * 0.025)", source)

    def test_pending_one_close_footer_copy_is_attempt_not_prediction(self):
        source = (PROJECT_DIR / "chart_generator_reference.py").read_text()

        self.assertIn("an attempt", source.lower())
        self.assertIn("confirmation", source.lower())
        for banned_word in ("buy", "sell", "enter", "exit", "long", "short", "target"):
            self.assertIsNone(re.search(rf"\b{banned_word}\b", source[source.index("items = footer_items or [") : source.index("canvas.text(0.50, 0.062")].lower()))

    def test_teaching_logo_watermark_success_skips_text_fallback(self):
        source = (PROJECT_DIR / "chart_generator_reference.py").read_text()

        logo_branch = source[source.index("if teaching_mode:\n        watermark_drawn = add_logo_watermark"):]
        logo_branch = logo_branch[:logo_branch.index("\n\n    level_ticks = []")]

        self.assertIn("watermark_drawn = add_logo_watermark(chart_ax, opacity=0.06)", logo_branch)
        self.assertIn("if not watermark_drawn:", logo_branch)
        self.assertIn('"POINKLE"', logo_branch)
        self.assertNotIn("chart_ax.text", logo_branch.split("if not watermark_drawn:", 1)[0])

    def test_teaching_logo_watermark_failure_uses_text_fallback(self):
        source = (PROJECT_DIR / "chart_generator_reference.py").read_text()

        self.assertIn("if teaching_mode:\n        watermark_drawn = add_logo_watermark(chart_ax, opacity=0.06)\n        if not watermark_drawn:\n            chart_ax.text", source)
        self.assertIn("fontsize=96", source)
        self.assertIn("alpha=0.055", source)

    def test_explain_rsi_with_symbol_still_uses_static_card(self):
        with patch.object(scanner, "handle_live_explain_command", side_effect=AssertionError("RSI must stay static")), patch.object(
            scanner, "send_explain_command_response"
        ) as send_response:
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain rsi BTC",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
                exchange=object(),
                state={},
            )

        self.assertIn("<b>RSI</b>", send_response.call_args.args[2])
        self.assertEqual(send_response.call_args.kwargs["concept_key"], "rsi")

    def test_bare_explain_support_stays_static_and_does_not_fetch(self):
        with patch.object(scanner, "build_levels_scan_snapshot", side_effect=AssertionError("bare static explain should not fetch")), patch.object(
            scanner, "send_explain_command_response"
        ) as send_response:
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain support",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
                exchange=object(),
                state={},
            )

        self.assertIn("<b>Support</b>", send_response.call_args.args[2])
        self.assertEqual(send_response.call_args.kwargs["concept_key"], "support")

    def test_live_explain_unknown_symbol_replies_instead_of_dropping(self):
        sent_messages = []

        with patch.object(scanner, "validate_tradeable_symbol", return_value=None), patch.object(
            scanner, "handle_live_explain_command", side_effect=AssertionError("unknown symbol should not render live chart")
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_explain_command(
                "TOKEN",
                "777",
                "/explain support NOTREAL",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
                exchange=object(),
                state={},
            )

        self.assertEqual(sent_messages[0][0], "777")
        self.assertIn("I don't have NOTREAL in my list yet", sent_messages[0][1])

    def test_unknown_private_command_sends_orientation_card(self):
        deleted_commands = (
            "/levels BTC",
            "/guide",
            "/coins",
            "/clearwatch",
            "/mywatch",
            "/commands",
            "/banana",
        )
        for index, command in enumerate(deleted_commands, start=126):
            state = {}
            sent_messages = []
            updates = [
                {
                    "update_id": index,
                    "message": {
                        "message_id": index,
                        "chat": {"id": "999", "type": "private"},
                        "from": {"id": 999},
                        "text": command,
                    },
                }
            ]

            with self.subTest(command=command), patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
                scanner, "USER_PROFILES_FILE", Path(tempfile.mkdtemp()) / f"user_profiles_{index}.json"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
            ), patch.object(
                scanner, "command_allowed_by_active_mode", return_value=True
            ), patch.object(scanner, "save_state"):
                scanner.process_telegram_commands(object(), "TOKEN", "999", state)

            self.assertEqual(sent_messages, [("999", scanner.start_orientation_text(), scanner.start_orientation_keyboard())])
            self.assertEqual(state["__telegram_commands"]["last_update_id"], index)

    def test_unknown_private_command_orientation_is_not_rate_limited(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 136 + index,
                "message": {
                    "message_id": 236 + index,
                    "chat": {"id": "999", "type": "private"},
                    "from": {"id": 999},
                    "text": "/banana",
                },
            }
            for index in range(2)
        ]

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(scanner.time, "time", return_value=1_000.0), patch.object(
            scanner, "get_telegram_updates", return_value=updates
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
        ), patch.object(
            scanner, "command_allowed_by_active_mode", return_value=True
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(
            sent_messages,
            [
                ("999", scanner.start_orientation_text(), scanner.start_orientation_keyboard()),
                ("999", scanner.start_orientation_text(), scanner.start_orientation_keyboard()),
            ],
        )

    def test_unknown_group_command_sends_nothing(self):
        deleted_commands = (
            "/levels BTC",
            "/guide",
            "/coins",
            "/clearwatch",
            "/mywatch",
            "/commands",
            "/banana",
        )
        for index, command in enumerate(deleted_commands, start=140):
            state = {}
            updates = [
                {
                    "update_id": index,
                    "message": {
                        "message_id": index,
                        "chat": {"id": "-100", "type": "group"},
                        "from": {"id": 999},
                        "text": command,
                    },
                }
            ]

            with self.subTest(command=command), patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
                scanner, "send_telegram_message"
            ) as send_message, patch.object(
                scanner, "command_allowed_by_active_mode", return_value=True
            ), patch.object(scanner, "save_state"):
                scanner.process_telegram_commands(object(), "TOKEN", "999", state)

            send_message.assert_not_called()
            self.assertEqual(state["__telegram_commands"]["last_update_id"], index)

    def test_non_command_private_message_sends_orientation_card(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 127,
                "message": {
                    "chat": {"id": "777", "type": "private"},
                    "from": {"id": 777},
                    "text": "hi",
                },
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(sent_messages, [("777", scanner.start_orientation_text(), scanner.start_orientation_keyboard())])

    def test_non_command_group_message_sends_nothing(self):
        state = {}
        updates = [
            {
                "update_id": 128,
                "message": {
                    "chat": {"id": "-100", "type": "group"},
                    "from": {"id": 777},
                    "text": "hello poinkle",
                },
            }
        ]

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "send_telegram_message"
        ) as send_message, patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        send_message.assert_not_called()

    def test_non_command_private_message_orientation_is_rate_limited(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 129 + index,
                "message": {
                    "chat": {"id": "777", "type": "private"},
                    "from": {"id": 777},
                    "text": text,
                },
            }
            for index, text in enumerate(["hi", "hello", "are you there"])
        ]

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(scanner.time, "time", return_value=1_000.0), patch.object(
            scanner, "get_telegram_updates", return_value=updates
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(sent_messages, [("777", scanner.start_orientation_text(), scanner.start_orientation_keyboard())])

    def test_command_private_message_does_not_send_orientation_card(self):
        state = {}
        updates = [
            {
                "update_id": 132,
                "message": {
                    "chat": {"id": "777", "type": "private"},
                    "from": {"id": 777},
                    "text": "/help",
                },
            }
        ]

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "handle_help_command"
        ) as handle_help, patch.object(scanner, "send_start_orientation_card") as send_orientation, patch.object(
            scanner, "save_state"
        ):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        handle_help.assert_called_once_with("TOKEN", "777")
        send_orientation.assert_not_called()

    def test_process_telegram_commands_ignores_edited_command_updates(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 126,
                "message": {
                    "message_id": 10,
                    "chat": {"id": "999", "type": "group"},
                    "from": {"id": 777},
                    "text": "/explain support",
                },
            },
            {
                "update_id": 127,
                "edited_message": {
                    "message_id": 10,
                    "chat": {"id": "999", "type": "group"},
                    "from": {"id": 777},
                    "text": "/explain support",
                },
            },
        ]

        def fake_handle(token, chat_id, text, source_chat=None, from_user=None, **kwargs):
            sent_messages.append((chat_id, text, source_chat, from_user))

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "handle_explain_command", side_effect=fake_handle
        ), patch.object(
            scanner, "command_allowed_by_active_mode", return_value=True
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0][0:2], ("999", "/explain support"))
        self.assertEqual(state["__telegram_commands"]["last_update_id"], 127)

    def test_snapshot_caption_skill_level_wording(self):
        accumulation = {"grade": "B", "label": "Good accumulation"}

        beginner = scanner.build_levels_snapshot_caption(
            "BTC/USD",
            100,
            "Near Support",
            "Bullish",
            72,
            accumulation,
            58.2,
            skill_level="beginner",
        )
        experienced = scanner.build_levels_snapshot_caption(
            "BTC/USD",
            100,
            "Near Support",
            "Bullish",
            72,
            accumulation,
            58.2,
            skill_level="experienced",
        )
        no_preference = scanner.build_levels_snapshot_caption(
            "BTC/USD",
            100,
            "Near Support",
            "Bullish",
            72,
            accumulation,
            58.2,
        )

        self.assertIn("Bullish (price is leaning above key moving averages)", beginner)
        self.assertIn("58.20 (", beginner)
        self.assertIn("Bullish\n\n", experienced)
        self.assertIn("📊 RSI\n58.20\n\n", experienced)
        self.assertIn("Bullish\n\n", no_preference)
        self.assertIn("📊 RSI\n58.20\n\n", no_preference)

    def test_alert_takeaway_skill_level_wording(self):
        alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }

        beginner = scanner.alert_card_data(
            "BTC/USD",
            candle(0, 100, 105, 99, 104, 250),
            alert,
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
            skill_level="beginner",
        )
        experienced = scanner.alert_card_data(
            "BTC/USD",
            candle(0, 100, 105, 99, 104, 250),
            alert,
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
            skill_level="experienced",
        )
        no_preference = scanner.alert_card_data(
            "BTC/USD",
            candle(0, 100, 105, 99, 104, 250),
            alert,
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
        )

        self.assertIn("Unusual buying volume", beginner["takeaway"])
        self.assertEqual(experienced["takeaway"], "High volume detected. Watch for breakout confirmation.")
        self.assertEqual(no_preference["takeaway"], "High volume detected. Watch for breakout confirmation.")

    def test_official_coin_links_are_curated_for_top_majors_only(self):
        self.assertEqual(len(scanner.OFFICIAL_COIN_LINKS), 15)
        self.assertEqual(scanner.official_coin_link("BTC/USD"), "https://bitcoin.org")
        self.assertEqual(scanner.official_coin_link("btc"), "https://bitcoin.org")
        self.assertEqual(scanner.official_coin_link("ETH/USD"), "https://ethereum.org")
        self.assertEqual(scanner.official_coin_link("TRX/USD"), "https://tron.network")
        self.assertIsNone(scanner.official_coin_link("PEPE/USD"))

    def test_official_link_appears_for_supported_alerts_and_omits_otherwise(self):
        alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }

        btc_card = scanner.alert_card_data(
            "BTC/USD",
            candle(0, 100, 105, 99, 104, 250),
            alert,
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
        )
        pepe_card = scanner.alert_card_data(
            "PEPE/USD",
            candle(0, 100, 105, 99, 104, 250),
            alert,
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
        )
        btc_text = scanner.build_alert(
            "BTC/USD",
            candle(0, 100, 105, 99, 104, 250),
            alert,
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
        )
        pepe_text = scanner.build_alert(
            "PEPE/USD",
            candle(0, 100, 105, 99, 104, 250),
            alert,
            ema_21=101,
            ema_55=99,
            current_rsi=58,
            volume_avg=100,
        )

        self.assertEqual(btc_card["official_link"], "https://bitcoin.org")
        self.assertIsNone(pepe_card["official_link"])
        self.assertIn("<b>Learn more:</b> https://bitcoin.org", btc_text)
        self.assertNotIn("Learn more", pepe_text)

    def test_alert_card_draws_official_link_when_present(self):
        drawn_text = []
        alert_data = {
            "symbol": "BTC/USD",
            "label": "Bullish Volume Spike",
            "direction": "bullish",
            "timeframe": "15M",
            "timestamp": "10:35 AM ET",
            "stats": [("PRICE", "100"), ("VOLUME", "2.50x avg")],
            "takeaway": "Watch confirmation.",
            "official_link": "https://bitcoin.org",
        }

        def capture_text(pixels, width, height, y, text, color=prb_card_renderer.TEXT, scale=prb_card_renderer.BODY_SCALE):
            drawn_text.append((y, text, color, scale))

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            prb_card_renderer,
            "draw_centered_text",
            side_effect=capture_text,
        ):
            prb_card_renderer.render_alert_card(alert_data, output_dir=tmpdir)

        self.assertIn(
            (prb_card_renderer.HEIGHT - 134, "LEARN MORE: https://bitcoin.org", prb_card_renderer.MUTED, prb_card_renderer.SMALL_SCALE),
            drawn_text,
        )

    def test_research_command_builds_standard_prb_for_supported_asset(self):
        current_price = 100
        fifteen_minute_closes = [95 + (index % 20) * 0.5 for index in range(119)] + [current_price]
        four_hour_closes = [90 + (index % 16) * 1.2 for index in range(179)] + [current_price]
        daily_closes = [82 + (index % 30) * 1.1 for index in range(179)] + [current_price]
        weekly_closes = [60 + (index % 18) * 3 for index in range(103)] + [current_price]
        fake_exchange = FakeExchange(
            {
                "15m": make_ohlcv_series(fifteen_minute_closes),
                "1h": make_ohlcv_series(four_hour_closes, step=3_600_000),
                "1d": make_ohlcv_series(daily_closes, step=86_400_000),
                "1w": make_ohlcv_series(weekly_closes, step=604_800_000),
            },
            ticker_price=current_price,
        )

        message = scanner.build_research_command_message(fake_exchange, "ETH/USD")

        self.assertTrue(message.startswith("🐷 POINKLE RESEARCH BRIEF\n━━━━━━━━━━━━━━━━━━"))
        self.assertIn("PRB: PRB-0002", message)
        self.assertIn("Title: ETH Market-Structure Research Brief", message)
        self.assertIn("Status: Market-Structure Brief", message)
        self.assertIn("Overall Rating:", message)
        self.assertIn("Long-Term Thesis:", message)
        self.assertIn("Short-Term Thesis:", message)
        self.assertIn("✅ WHAT WE KNOW", message)
        self.assertIn("📈 HISTORICAL PATTERN", message)
        self.assertIn("🐂 BULL CASE", message)
        self.assertIn("🐻 BEAR CASE", message)
        self.assertIn("❓ BIGGEST UNKNOWNS", message)
        self.assertIn("🔍 WHAT WOULD STRENGTHEN THIS THESIS?", message)
        self.assertIn("⚠️ WHAT WOULD WEAKEN THIS THESIS?", message)
        self.assertIn("📊 POINKLE SCORECARD", message)
        self.assertIn("📌 RESEARCH CONCLUSION", message)
        self.assertIn("━━━━━━━━━━━━━━━━━━", message)
        self.assertNotIn("Full Research Pending", message)
        self.assertIn("⚠️ Not Financial Advice", message)
        self.assertIn("🐷 Poinkle did the research.", message)
        self.assertIn("🎓 The decision is yours.", message)
        self.assertTrue(message.rstrip().endswith("━━━━━━━━━━━━━━━━━━"))
        self.assertNotIn("Educational research only. Not financial advice.", message)
        self.assertIn("ETH/USD", scanner.LAST_RESEARCH_CHART_DATA)
        self.assertEqual(scanner.LAST_RESEARCH_CHART_DATA["ETH/USD"]["current_price"], current_price)

    def test_research_command_uses_saved_asset_specific_research(self):
        current_price = 100
        fake_exchange = FakeExchange(
            {
                "15m": make_ohlcv_series([95 + (index % 20) * 0.5 for index in range(119)] + [current_price]),
                "1h": make_ohlcv_series([90 + (index % 16) * 1.2 for index in range(179)] + [current_price], step=3_600_000),
                "1d": make_ohlcv_series([82 + (index % 30) * 1.1 for index in range(179)] + [current_price], step=86_400_000),
                "1w": make_ohlcv_series([60 + (index % 18) * 3 for index in range(103)] + [current_price], step=604_800_000),
            },
            ticker_price=current_price,
        )

        message = scanner.build_research_command_message(fake_exchange, "AAVE/USD")

        self.assertTrue(message.startswith("🐷 POINKLE RESEARCH BRIEF\n━━━━━━━━━━━━━━━━━━"))
        self.assertIn("PRB: PRB-", message)
        self.assertIn("Title: AAVE Long-Term Investment Thesis", message)
        self.assertIn("Status: Active Research", message)
        self.assertIn("Overall Rating: 7.4 / 10", message)
        self.assertIn("Kraken", message)
        self.assertIn("DeFi TVL", message)
        self.assertIn("📊 POINKLE SCORECARD", message)
        self.assertIn("Fundamentals: 8.5/10", message)
        self.assertNotIn("Status: Market-Structure Brief — Full Research Pending", message)

    def test_standard_educational_footer_is_exact(self):
        self.assertEqual(
            scanner.poinkle_educational_footer(),
            "━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ Not Financial Advice\n\n"
            "🐷 Poinkle did the research.\n\n"
            "🎓 The decision is yours.\n\n"
            "━━━━━━━━━━━━━━━━━━",
        )

    def test_levels_btc_uses_standard_footer(self):
        current_price = 100
        fake_exchange = FakeExchange(
            {
                "15m": make_ohlcv_series([95 + (index % 20) * 0.5 for index in range(119)] + [current_price]),
                "1h": make_ohlcv_series([90 + (index % 16) * 1.2 for index in range(179)] + [current_price], step=3_600_000),
                "1d": make_ohlcv_series([82 + (index % 30) * 1.1 for index in range(179)] + [current_price], step=86_400_000),
                "1w": make_ohlcv_series([60 + (index % 18) * 3 for index in range(103)] + [current_price], step=604_800_000),
            },
            ticker_price=current_price,
        )

        message = scanner.build_levels_command_message(fake_exchange, "BTC/USD")

        self.assertIn(scanner.poinkle_educational_footer(), message)
        self.assertNotIn("Educational Market Structure Only", message)
        self.assertNotIn("Patience Compounds", message)

    def test_snapshot_commands_send_standard_footer(self):
        sent_messages = []

        with patch.object(
            scanner,
            "build_levels_command_message",
            return_value=f"BTC snapshot\n{scanner.poinkle_educational_footer()}",
        ), patch.object(scanner, "send_levels_chart", return_value=False), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_levels_command(
                object(),
                "TOKEN",
                "999",
                "/snapshot BTC",
                source_chat={"id": "999", "type": "private"},
                from_user={"id": 999},
            )

        self.assertEqual(len(sent_messages), 1)
        for _, text in sent_messages:
            self.assertIn(scanner.poinkle_educational_footer(), text)

    def test_snapshot_chart_still_uses_full_renderer(self):
        snapshot = self.live_explain_snapshot(current_price=110)
        scanner.LAST_LEVELS_CHART_DATA["BTC/USD"] = snapshot["chart_data"]
        captured = {}

        def fake_generate(symbol, candles, current_price, supports, resistances, **kwargs):
            captured.update(kwargs)
            return "/tmp/full-snapshot.png"

        with patch.object(scanner, "generate_levels_chart", side_effect=fake_generate), patch.object(
            scanner, "send_telegram_photo", return_value=True
        ):
            sent = scanner.send_levels_chart("TOKEN", "999", "BTC/USD", "caption")

        self.assertTrue(sent)
        self.assertNotIn("teaching_mode", captured)
        self.assertNotIn("teaching_zone", captured)

    def test_research_btc_uses_standard_footer(self):
        current_price = 100
        fake_exchange = FakeExchange(
            {
                "15m": make_ohlcv_series([95 + (index % 20) * 0.5 for index in range(119)] + [current_price]),
                "1h": make_ohlcv_series([90 + (index % 16) * 1.2 for index in range(179)] + [current_price], step=3_600_000),
                "1d": make_ohlcv_series([82 + (index % 30) * 1.1 for index in range(179)] + [current_price], step=86_400_000),
                "1w": make_ohlcv_series([60 + (index % 18) * 3 for index in range(103)] + [current_price], step=604_800_000),
            },
            ticker_price=current_price,
        )

        message = scanner.build_research_command_message(fake_exchange, "BTC/USD")

        self.assertIn(scanner.poinkle_educational_footer(), message)

    def test_research_prb_numbering_uses_supported_asset_order(self):
        self.assertEqual(scanner.prb_number(scanner.WATCHLIST[0]), "PRB-0001")
        self.assertEqual(scanner.prb_number(scanner.WATCHLIST[-1]), f"PRB-{len(scanner.WATCHLIST):04d}")

    def test_research_brief_uses_future_source_pipeline(self):
        snapshot = {
            "symbol": "ETH/USD",
            "current_price": 100,
            "support_zones": [(90, 95)],
            "resistance_zones": [(110, 115)],
            "patience_grade": "B",
            "patience_label": "Good accumulation",
            "bias": "Neutral",
            "location": "Between Major Zones",
            "market_structure_label": "Range Bound",
            "rsi": 50,
            "strategy": ["watch"],
            "market_score": 70,
        }

        with patch.object(scanner, "collect_market_data", return_value=snapshot) as market, patch.object(
            scanner, "collect_future_news", return_value={"timeline": "Pending Evidence", "historical_comparison": "Pending Evidence"}
        ) as news, patch.object(
            scanner,
            "collect_future_fundamentals",
            return_value={
                "fundamentals": "Pending Evidence",
                "on_chain": "Pending Evidence",
                "macro": "Pending Evidence",
                "institutional_adoption": "Pending Evidence",
                "historical_pattern": "Pending Evidence",
            },
        ) as fundamentals:
            message = scanner.build_research_brief(object(), "ETH/USD")

        market.assert_called_once()
        news.assert_called_once_with("ETH/USD")
        fundamentals.assert_called_once_with("ETH/USD")
        self.assertIn("🐷 POINKLE RESEARCH BRIEF", message)

    def test_research_command_rejects_unsupported_asset(self):
        sent_messages = []

        with patch.object(scanner, "send_telegram_message", side_effect=lambda token, chat_id, text: sent_messages.append(text)):
            scanner.handle_research_command(object(), "TOKEN", "999", "/research NOTREAL")

        self.assertEqual(
            sent_messages[-1],
            (
                "I don't have NOTREAL in my list yet. Try /research with one of the coins "
                "I track — or type /research on its own to pick from a list."
            ),
        )

    def test_research_command_replies_when_card_generation_fails(self):
        sent_messages = []

        with patch.object(
            scanner,
            "build_research_command_message",
            side_effect=RuntimeError("chart boom"),
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_research_command(object(), "TOKEN", "999", "/research BTC")

        self.assertEqual(
            sent_messages,
            [("999", "I couldn't build that card just now. Try again in a moment.")],
        )

    def test_research_command_valid_symbol_still_sends_cards(self):
        with patch.object(scanner, "build_research_command_message", return_value="BTC PRB") as build_message, patch.object(
            scanner,
            "send_research_cards",
            return_value=True,
        ) as send_cards, patch.object(
            scanner,
            "send_telegram_message",
            side_effect=AssertionError("valid card path should not send fallback text"),
        ):
            scanner.handle_research_command(object(), "TOKEN", "999", "/research BTC")

        build_message.assert_called_once()
        send_cards.assert_called_once()

    def test_alerts_command_replies_for_unknown_symbol(self):
        sent_messages = []

        with patch.object(scanner, "send_telegram_message", side_effect=lambda token, chat_id, text: sent_messages.append(text)):
            scanner.handle_alerts_command("TOKEN", "999", "/alerts NOTREAL support")

        self.assertEqual(
            sent_messages[-1],
            "I don't have NOTREAL in my list yet. Try /alerts with one of the coins I track.",
        )

    def test_prb_card_renderer_produces_image_path(self):
        prb_text = (
            "🐷 POINKLE RESEARCH BRIEF\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "PRB: PRB-0001\n"
            "Title: AAVE Long-Term Investment Thesis\n"
            "Status: Active Research\n\n"
            "✅ WHAT WE KNOW\n\n"
            "• AAVE has saved research content.\n\n"
            "📌 RESEARCH CONCLUSION\n\n"
            "This is a test brief."
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = prb_card_renderer.render_prb_cards(prb_text, output_dir=tmpdir)

            self.assertTrue(paths)
            self.assertTrue(Path(paths[0]).exists())
            self.assertEqual(Path(paths[0]).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_prb_card_renderer_missing_logo_does_not_crash(self):
        prb_text = (
            "🐷 POINKLE RESEARCH BRIEF\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "PRB: PRB-0002\n"
            "Title: ETH Market-Structure Research Brief\n"
            "Status: Market-Structure Brief — Full Research Pending\n\n"
            "📌 RESEARCH CONCLUSION\n\n"
            "Renderer should skip a missing logo."
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = prb_card_renderer.render_prb_cards(
                prb_text,
                logo_path=Path(tmpdir) / "missing-logo.png",
                output_dir=tmpdir,
            )

            self.assertTrue(paths)
            self.assertTrue(Path(paths[0]).exists())

    def test_prb_card_renderer_embeds_chart_on_first_card(self):
        prb_text = (
            "🐷 POINKLE RESEARCH BRIEF\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "PRB: PRB-0003\n"
            "Title: BTC Market-Structure Research Brief\n"
            "Status: Market-Structure Brief — Full Research Pending\n\n"
            "✅ WHAT WE KNOW\n\n"
            "• Current Price: 100\n"
            "• Trend: Bullish\n"
            "• RSI: 58.20\n"
            "• Nearest Support: 95\n"
            "• Nearest Resistance: 110\n\n"
            "📌 RESEARCH CONCLUSION\n\n"
            "This is a test brief."
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            chart_path = Path(tmpdir) / "chart.png"
            red_pixel = (255, 0, 0)
            prb_card_renderer.write_png(chart_path, [[red_pixel for _ in range(12)] for _ in range(12)])

            paths = prb_card_renderer.render_prb_cards(
                prb_text,
                output_dir=tmpdir,
                chart_path=chart_path,
            )
            _width, _height, pixels = prb_card_renderer.read_png(paths[0])

        self.assertGreaterEqual(len(paths), 1)
        self.assertTrue(any(pixel[:3] == red_pixel for row in pixels for pixel in row))

    def test_prb_text_card_renders_ghost_watermark_at_low_opacity(self):
        prb_text = (
            "🐷 POINKLE RESEARCH BRIEF\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "PRB: PRB-0004\n"
            "Title: BTC Market-Structure Research Brief\n"
            "Status: Market-Structure Brief — Full Research Pending\n\n"
            "✅ WHAT WE KNOW\n\n"
            "• Text-only cards should keep readable text over subtle branding.\n\n"
            "📌 RESEARCH CONCLUSION\n\n"
            "This is a test brief."
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            watermark_path = Path(tmpdir) / "poinkle_ghost_watermark.png"
            prb_card_renderer.write_png(
                watermark_path,
                [[(255, 255, 255) for _ in range(24)] for _ in range(24)],
            )
            with patch.object(prb_card_renderer, "GHOST_WATERMARK_PATHS", (watermark_path,)):
                paths = prb_card_renderer.render_prb_cards(prb_text, output_dir=tmpdir)
            _width, _height, pixels = prb_card_renderer.read_png(paths[0])

        center_pixel = pixels[prb_card_renderer.HEIGHT // 2][prb_card_renderer.WIDTH // 2][:3]
        expected_low_opacity = tuple(
            int(prb_card_renderer.CARD[i] * 0.95 + 255 * 0.05)
            for i in range(3)
        )
        self.assertEqual(center_pixel, expected_low_opacity)
        self.assertLess(max(center_pixel[i] - prb_card_renderer.CARD[i] for i in range(3)), 14)
        self.assertTrue(any(pixel[:3] == prb_card_renderer.TEXT for row in pixels for pixel in row))

    def test_prb_card_text_starts_inside_safe_left_margin(self):
        prb_text = (
            "🐷 POINKLE RESEARCH BRIEF\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "PRB: PRB-0005\n"
            "Title: BTC Market-Structure Research Brief\n"
            "Status: Market-Structure Brief — Full Research Pending\n"
            "Overall Rating: 3 / 10 (Market Snapshot)\n"
            "Long-Term Thesis: Full long-term thesis pending.\n"
            "Short-Term Thesis: Price is showing bullish bias.\n\n"
            "✅ WHAT WE KNOW\n\n"
            "• POINKLE should keep every body line inside the safe margin.\n"
            "• STATUS and OVERALL RATING should not lose their first letters.\n\n"
            "📌 RESEARCH CONCLUSION\n\n"
            "All text should render with breathing room."
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = prb_card_renderer.render_prb_cards(prb_text, output_dir=tmpdir)
            _width, _height, pixels = prb_card_renderer.read_png(paths[0])

        text_colors = {
            prb_card_renderer.TEXT,
            prb_card_renderer.CYAN,
            (204, 222, 228),
        }
        body_text_x = [
            x
            for y, row in enumerate(pixels)
            if 330 <= y <= prb_card_renderer.HEIGHT - 130
            for x, pixel in enumerate(row)
            if pixel[:3] in text_colors
        ]
        header_text_x = [
            x
            for y, row in enumerate(pixels)
            if 130 <= y <= 270
            for x, pixel in enumerate(row)
            if pixel[:3] in {prb_card_renderer.TEXT, prb_card_renderer.CYAN, prb_card_renderer.GOLD}
        ]

        self.assertTrue(body_text_x)
        self.assertGreaterEqual(min(body_text_x), prb_card_renderer.PRB_TEXT_LEFT)
        self.assertTrue(header_text_x)
        self.assertGreater(min(header_text_x), 32 + 48)

    def test_welcome_card_renderer_produces_image_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = prb_card_renderer.render_welcome_card(
                ["BTC/USD", "ETH/USD", "SOL/USD"],
                output_dir=tmpdir,
            )

            self.assertTrue(Path(path).exists())
            self.assertEqual(Path(path).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_start_command_sends_orientation_card_and_captures_new_profile(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(scanner, "iso_utc_now", return_value="2026-07-08T12:00:00+00:00"), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_start_command(
                "TOKEN",
                "999",
                from_user={"id": 777, "username": "poinkle_user", "first_name": "Pat", "last_name": "Learner"},
            )
            profiles = scanner.load_user_profiles()

        self.assertEqual(sent_messages[0][0], "777")
        self.assertEqual(sent_messages[0][1], scanner.start_orientation_text())
        self.assertEqual(sent_messages[0][2], scanner.start_orientation_keyboard())
        self.assertIn("Hi — I'm Poinkle.", sent_messages[0][1])
        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(profiles["777"]["telegram_user_id"], "777")
        self.assertEqual(profiles["777"]["username"], "poinkle_user")
        self.assertEqual(profiles["777"]["first_name"], "Pat")
        self.assertEqual(profiles["777"]["last_name"], "Learner")
        self.assertEqual(profiles["777"]["first_seen"], "2026-07-08T12:00:00+00:00")
        self.assertEqual(profiles["777"]["last_start"], "2026-07-08T12:00:00+00:00")
        self.assertTrue(profiles["777"]["onboarded"])

    def test_start_verify_payload_opens_creator_picker_not_orientation(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
                "registered_at": "2026-07-13",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_start_command("TOKEN", "999", "/start verify", from_user={"id": 777})

        self.assertEqual(sent_messages[0][0], "777")
        self.assertIn("Checking whether an account is really who it says it is? Tap a creator.", sent_messages[0][1])
        self.assertIn("Which creator's accounts do you want to check?", sent_messages[0][1])
        self.assertEqual(sent_messages[0][2], scanner.creator_picker_keyboard(creators))
        self.assertNotEqual(sent_messages[0][1], scanner.start_orientation_text())

    def test_start_verify_creator_payload_opens_creator_account_list(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [
                    {"platform": "telegram", "handle": "@MikeKnows_Official"},
                    {"platform": "tiktok", "handle": "@mikeknows"},
                ],
                "registered_at": "2026-07-13",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_start_command("TOKEN", "999", "/start verify_mike_knows", from_user={"id": 777})

        self.assertEqual(sent_messages[0][1], scanner.render_creator_handle_list_message(creators["mike_knows"]))
        self.assertEqual(sent_messages[0][2], scanner.creator_account_keyboard("mike_knows", creators["mike_knows"]))

    def test_start_verify_unknown_creator_falls_back_to_picker(self):
        sent_messages = []
        creators = {
            "mike_knows": {
                "display_name": "Mike Knows",
                "community": "The Inner Circle",
                "accounts": [{"platform": "telegram", "handle": "@MikeKnows_Official"}],
                "registered_at": "2026-07-13",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            creators_path = Path(tmpdir) / "creators.json"
            creators_path.write_text(json.dumps(creators))
            with patch.object(scanner, "CREATORS_FILE", creators_path), patch.object(
                scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_start_command("TOKEN", "999", "/start verify_nonexistent", from_user={"id": 777})

        self.assertEqual(sent_messages[0][1], "Which creator's accounts do you want to check?")
        self.assertEqual(sent_messages[0][2], scanner.creator_picker_keyboard(creators))

    def test_start_learn_payload_opens_explain_picker(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_start_command("TOKEN", "999", "/start learn", from_user={"id": 777})

        self.assertEqual(sent_messages[0], ("777", scanner.explain_group_prompt(), scanner.explain_group_keyboard()))

    def test_start_commands_payload_opens_command_panel(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_start_command("TOKEN", "999", "/start commands", from_user={"id": 777})

        self.assertEqual(sent_messages[0], ("777", scanner.command_panel_text(), scanner.command_panel_keyboard()))

    def test_start_unknown_payload_shows_orientation_card(self):
        sent_messages = []
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_start_command("TOKEN", "999", "/start nonsense", from_user={"id": 777})

        self.assertEqual(sent_messages, [("777", scanner.start_orientation_text(), scanner.start_orientation_keyboard())])

    def test_start_command_sends_orientation_card_without_banner(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "user_profiles.json"
            banner_path = Path(tmpdir) / "welcome_banner.jpg"
            banner_path.write_bytes(b"fake jpg")
            with patch.object(scanner, "USER_PROFILES_FILE", profile_path), patch.object(
                scanner, "WELCOME_BANNER_PATH", banner_path
            ), patch.object(scanner, "iso_utc_now", return_value="2026-07-08T12:00:00+00:00"), patch.object(
                scanner,
                "send_telegram_photo",
                side_effect=AssertionError("/start should not send the old welcome banner"),
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_start_command("TOKEN", "999", from_user={"id": 777})

        self.assertEqual(sent_messages, [("777", scanner.start_orientation_text(), scanner.start_orientation_keyboard())])

    def test_start_welcome_falls_back_to_text_when_banner_missing(self):
        sent_messages = []
        warnings = []

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "WELCOME_BANNER_PATH", Path(tmpdir) / "missing-welcome-banner.jpg"
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ), patch.object(scanner, "log_warn", side_effect=lambda text: warnings.append(text)), patch.object(
            scanner, "send_telegram_photo", side_effect=AssertionError("missing banner should not send photo")
        ):
            scanner.send_start_welcome("TOKEN", "777", scanner.build_welcome_message())

        self.assertEqual(sent_messages, [("777", scanner.build_welcome_message())])
        self.assertIn("Welcome banner image missing", warnings[0])

    def test_start_command_preserves_existing_profile_first_seen(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "user_profiles.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "777": {
                            "telegram_user_id": "777",
                            "first_seen": "2026-07-01T12:00:00+00:00",
                            "skill_level": "beginner",
                        }
                    }
                )
            )
            with patch.object(scanner, "USER_PROFILES_FILE", profile_path), patch.object(
                scanner, "iso_utc_now", return_value="2026-07-08T12:00:00+00:00"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_start_command("TOKEN", "999", from_user={"id": 777, "first_name": "Pat"})
                profiles = scanner.load_user_profiles()

        self.assertEqual(sent_messages, [("777", scanner.start_orientation_text(), scanner.start_orientation_keyboard())])
        self.assertEqual(profiles["777"]["first_seen"], "2026-07-01T12:00:00+00:00")
        self.assertEqual(profiles["777"]["last_start"], "2026-07-08T12:00:00+00:00")
        self.assertEqual(profiles["777"]["skill_level"], "beginner")
        self.assertEqual(profiles["777"]["first_name"], "Pat")

    def test_start_command_still_orients_when_profile_write_fails(self):
        sent_messages = []

        with patch.object(scanner, "save_user_profiles", side_effect=OSError("disk full")), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                (str(chat_id), text, reply_markup)
            ),
        ):
            scanner.handle_start_command("TOKEN", "999", from_user={"id": 777})

        self.assertEqual(sent_messages[0][0], "777")
        self.assertEqual(sent_messages[0][1], scanner.start_orientation_text())
        self.assertEqual(sent_messages[0][2], scanner.start_orientation_keyboard())

    def test_start_command_does_not_send_skill_prompt_when_already_prompted(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "user_profiles.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "777": {
                            "telegram_user_id": "777",
                            "first_seen": "2026-07-01T12:00:00+00:00",
                            "skill_onboarding_prompted": True,
                        }
                    }
                )
            )
            with patch.object(scanner, "USER_PROFILES_FILE", profile_path), patch.object(
                scanner, "iso_utc_now", return_value="2026-07-08T12:00:00+00:00"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(
                    (str(chat_id), text, reply_markup)
                ),
            ):
                scanner.handle_start_command("TOKEN", "999", from_user={"id": 777})

        self.assertEqual(sent_messages, [("777", scanner.start_orientation_text(), scanner.start_orientation_keyboard())])

    def test_card_renderers_use_shared_emblem_path(self):
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        sent_photos = []

        with patch.object(scanner, "render_alert_card", return_value="/tmp/alert.png") as alert_render:
            scanner.render_lightweight_alert_card(
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                volume_alert,
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
            )

        with patch.dict(scanner.LAST_RESEARCH_CARD_DATA, {"BTC/USD": [{"title": "The Read"}]}), patch.object(
            scanner, "render_research_cards", return_value=["/tmp/prb.png"]
        ) as prb_render, patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path: sent_photos.append((str(chat_id), path)) or True,
        ):
            scanner.send_research_cards("TOKEN", "999", "BTC PRB", symbol="BTC/USD")

        self.assertEqual(alert_render.call_args.kwargs["logo_path"], scanner.POINKLE_RESEARCH_EMBLEM_PATH)
        self.assertEqual(prb_render.call_args.kwargs["logo_path"], scanner.POINKLE_RESEARCH_EMBLEM_PATH)

    def test_confluence_alert_snapshot_passes_alert_cards_and_volume_candles(self):
        captured = {}
        candles = [
            candle(0, 100, 105, 99, 104, 100),
            candle(scanner.TIMEFRAME_MS, 104, 108, 103, 107, 250),
        ]
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }

        def fake_generate(symbol, chart_candles, current_price, supports, resistances, **kwargs):
            captured.update(
                {
                    "symbol": symbol,
                    "candles": chart_candles,
                    "current_price": current_price,
                    "supports": supports,
                    "resistances": resistances,
                    **kwargs,
                }
            )
            return "/tmp/volume-alert-snapshot.png"

        with patch.object(scanner, "generate_levels_chart", side_effect=fake_generate):
            path = scanner.render_alert_snapshot_chart(
                "BTC/USD",
                candles,
                candles[-1],
                [volume_alert, ema_alert],
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
                supports=[95],
                resistances=[110],
            )

        self.assertEqual(path, "/tmp/volume-alert-snapshot.png")
        self.assertEqual([item["volume"] for item in captured["candles"]], [100, 250])
        self.assertEqual(captured["title"], "BTC / USD BULLISH VOLUME SPIKE")
        self.assertIn(
            ("CONFIRMING", "Volume context: Bullish Volume Spike (2.50x)\n+ EMA context: 21 crossed above 55"),
            captured["card_specs"],
        )
        self.assertIn(("VOLUME", "2.50x average\nCurrent candle"), captured["card_specs"])
        self.assertEqual(captured["signal_scope"], scanner.ALERT_SIGNAL_SCOPE)
        self.assertEqual(captured["supports"], [95])
        self.assertEqual(captured["resistances"], [110])

    def test_confluence_alert_snapshot_footer_includes_secondary_timeframe_context(self):
        captured = {}
        candles = [
            candle(0, 100, 105, 99, 104, 100),
            candle(scanner.TIMEFRAME_MS, 104, 108, 103, 107, 250),
        ]
        secondary_context = {
            "6h": {"latest_close": 110, "ema_21": 105, "ema_55": 100, "rsi_14": 58},
        }
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
            "secondary_timeframe_context": secondary_context,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
            "secondary_timeframe_context": secondary_context,
        }

        def fake_generate(symbol, chart_candles, current_price, supports, resistances, **kwargs):
            captured.update(kwargs)
            return "/tmp/volume-alert-snapshot.png"

        with patch.object(scanner, "generate_levels_chart", side_effect=fake_generate):
            path = scanner.render_alert_snapshot_chart(
                "BTC/USD",
                candles,
                candles[-1],
                [volume_alert, ema_alert],
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
                supports=[95],
                resistances=[110],
            )

        self.assertEqual(path, "/tmp/volume-alert-snapshot.png")
        self.assertIn(
            "3. 6h context: 6h bullish (RSI 58)",
            captured["footer_items"],
        )

    def test_single_volume_alert_sends_lightweight_card_when_renderer_succeeds(self):
        sent_photos = []
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }

        with patch.object(scanner, "render_lightweight_alert_card", return_value="/tmp/alert-card.png") as render_card, patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="", reply_markup=None: sent_photos.append(
                (str(chat_id), path, caption, reply_markup)
            )
            or True,
        ), patch.object(
            scanner, "send_telegram_message", side_effect=AssertionError("text fallback should not be sent")
        ):
            scanner.send_alert_to_chat(
                "TOKEN",
                "999",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                volume_alert,
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
                alert_candles=[
                    candle(0, 100, 105, 99, 104, 100),
                    candle(scanner.TIMEFRAME_MS, 104, 108, 103, 107, 250),
                ],
                supports=[95],
                resistances=[110],
            )

        render_card.assert_called_once()
        self.assertEqual(sent_photos[0][:3], ("999", "/tmp/alert-card.png", "🟢 <b>BTC/USD Bullish Volume Spike</b>"))
        self.assertEqual(
            sent_photos[0][3]["inline_keyboard"][0][0],
            {"text": "📊 Research BTC", "callback_data": "wact:research:BTC/USD"},
        )

    def test_alert_card_draws_signal_scope_line(self):
        drawn_text = []
        alert_data = {
            "symbol": "BTC/USD",
            "label": "Bullish Volume Spike",
            "direction": "bullish",
            "timeframe": "15M",
            "timestamp": "10:35 AM ET",
            "stats": [("PRICE", "100"), ("VOLUME", "2.50x avg")],
            "takeaway": "Watch confirmation.",
        }

        def capture_text(pixels, width, height, y, text, color=prb_card_renderer.TEXT, scale=prb_card_renderer.BODY_SCALE):
            drawn_text.append((y, text, color, scale))

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            prb_card_renderer,
            "draw_centered_text",
            side_effect=capture_text,
        ):
            prb_card_renderer.render_alert_card(alert_data, output_dir=tmpdir)

        self.assertIn(
            (386, prb_card_renderer.ALERT_SIGNAL_SCOPE, prb_card_renderer.MUTED, prb_card_renderer.SMALL_SCALE),
            drawn_text,
        )

    def test_single_volume_alert_falls_back_to_text_when_renderer_fails(self):
        sent_messages = []
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }

        with patch.object(scanner, "render_lightweight_alert_card", side_effect=RuntimeError("render failed")), patch.object(
            scanner, "send_telegram_photo", side_effect=AssertionError("photo should not be sent")
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
        ):
            scanner.send_alert_to_chat(
                "TOKEN",
                "999",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                volume_alert,
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
            )

        self.assertEqual(sent_messages[0][0], "999")
        self.assertIn("🟢 <b>BTC/USD Bullish Volume Spike</b>", sent_messages[0][1])
        self.assertEqual(
            sent_messages[0][2]["inline_keyboard"][0][0],
            {"text": "📊 Research BTC", "callback_data": "wact:research:BTC/USD"},
        )

    def test_confluence_alerts_send_one_combined_snapshot_chart(self):
        sent_photos = []
        sent_messages = []
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }
        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }

        with patch.object(scanner, "render_alert_snapshot_chart", return_value="/tmp/confluence.png") as render_chart, patch.object(
            scanner,
            "render_lightweight_alert_card",
            side_effect=AssertionError("confluence should not use small card"),
        ), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="", reply_markup=None: sent_photos.append(
                (str(chat_id), path, caption, reply_markup)
            )
            or True,
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
        ):
            scanner.send_alert_group_to_chat(
                "TOKEN",
                "999",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                [volume_alert, ema_alert],
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
                alert_candles=[
                    candle(0, 100, 105, 99, 104, 100),
                    candle(scanner.TIMEFRAME_MS, 104, 108, 103, 107, 250),
                ],
                supports=[95],
                resistances=[110],
            )

        render_chart.assert_called_once()
        self.assertEqual(len(sent_photos), 1)
        self.assertEqual(sent_photos[0][1], "/tmp/confluence.png")
        self.assertEqual(
            sent_photos[0][2],
            "<b>BTC/USD — Market Context</b>\n"
            "Developing\n"
            "Confirming: Volume context: Bullish Volume Spike (2.50x) + EMA context: 21 crossed above 55\n"
            "Learn more: https://bitcoin.org",
        )
        self.assertEqual(
            sent_photos[0][3]["inline_keyboard"][0][0],
            {"text": "📊 Research BTC", "callback_data": "wact:research:BTC/USD"},
        )
        self.assertEqual(sent_messages, [])

    def test_severity_label_for_alerts_uses_confirmed_zone_agreement(self):
        self.assertEqual(
            scanner.severity_label_for_alerts(
                [
                    {"type": "volume_spike"},
                    {"type": "ema_cross_above"},
                ]
            ),
            "Developing",
        )

        bare_break = severity_confirmed_break_alert(
            ema_trend="Neutral EMA trend, not aligned",
            volume_multiple=1.0,
        )
        self.assertEqual(
            scanner.alert_severity_tier([bare_break]),
            scanner.ALERT_SEVERITY_BUILDING,
        )
        self.assertEqual(
            scanner.severity_label_for_alerts([bare_break]),
            "Worth a look · zone confirmed",
        )

        full_agreement = severity_confirmed_break_alert(
            direction="breakout",
            ema_trend="Bullish EMA trend",
            volume_multiple=2.5,
        )
        full_agreement["secondary_timeframe_context"] = secondary_timeframe_context_for_bias("bullish")
        self.assertEqual(
            scanner.level_break_agreement_score([full_agreement]),
            3,
        )
        self.assertEqual(
            scanner.severity_label_for_alerts([full_agreement]),
            "Worth a close look · zone confirmed, 3 of 3 agree",
        )

    def test_confirmed_break_with_two_agreements_is_strong(self):
        alert = severity_confirmed_break_alert(
            direction="breakdown",
            ema_trend="Bearish EMA trend",
            volume_multiple=2.1,
        )

        self.assertEqual(scanner.level_break_agreement_score([alert]), 2)
        self.assertEqual(scanner.alert_severity_tier([alert]), scanner.ALERT_SEVERITY_STRONG)

    def test_confirmed_break_contradiction_lowers_score_but_stays_building(self):
        alert = severity_confirmed_break_alert(
            direction="breakdown",
            ema_trend="Bearish EMA trend",
            volume_multiple=2.1,
        )
        contradictory_lightweight = {"type": "ema_cross_above", "label": "EMA 21 crossed above EMA 55"}

        self.assertEqual(scanner.level_break_agreement_score([alert, contradictory_lightweight]), 1)
        self.assertEqual(
            scanner.alert_severity_tier([alert, contradictory_lightweight]),
            scanner.ALERT_SEVERITY_BUILDING,
        )

    def test_rsi_extreme_does_not_contradict_level_break_agreement(self):
        alert = severity_confirmed_break_alert(
            direction="breakdown",
            ema_trend="Bearish EMA trend",
            volume_multiple=2.1,
        )
        rsi_extreme = {"type": "rsi_cross_above_70", "label": "RSI above 70 — extended"}

        self.assertEqual(scanner.level_break_agreement_score([alert]), 2)
        self.assertEqual(scanner.level_break_agreement_score([alert, rsi_extreme]), 2)

    def test_confluence_caption_adds_severity_for_three_or_more_signals(self):
        sent_photos = []
        level_break = severity_confirmed_break_alert(
            direction="breakout",
            ema_trend="Bullish EMA trend",
            volume_multiple=2.5,
        )
        level_break["secondary_timeframe_context"] = secondary_timeframe_context_for_bias("bullish")
        alerts = [
            level_break,
            {
                "type": "volume_spike",
                "label": "Bullish Volume Spike",
                "emoji": "🟢",
                "volume_multiple": 2.5,
            },
            {
                "type": "ema_cross_above",
                "label": "EMA 21 crossed above EMA 55",
                "emoji": "🟢",
            },
            {
                "type": "rsi_cross_above_70",
                "label": "RSI above 70 — extended",
                "emoji": "🔥",
            },
        ]

        with patch.object(scanner, "render_alert_snapshot_chart", return_value="/tmp/confluence.png"), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="", reply_markup=None: sent_photos.append(
                (str(chat_id), path, caption, reply_markup)
            )
            or True,
        ), patch.object(scanner, "send_telegram_message"):
            scanner.send_alert_group_to_chat(
                "TOKEN",
                "999",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                alerts,
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
                alert_candles=[
                    candle(0, 100, 105, 99, 104, 100),
                    candle(scanner.TIMEFRAME_MS, 104, 108, 103, 107, 250),
                ],
            )

        self.assertTrue(
            sent_photos[0][2].startswith(
                "✅ <b>BTC/USD — Zone Broken (Up)</b>\n"
                "Worth a close look · zone confirmed, 3 of 3 agree\n"
                "Confirming: Volume context: Bullish Volume Spike (2.50x) + EMA context: 21 crossed above 55"
            )
        )

    def test_bare_confirmed_level_break_renders_severity_label(self):
        sent_photos = []
        alert = severity_confirmed_break_alert(
            direction="breakout",
            ema_trend="Neutral EMA trend, not aligned",
            volume_multiple=1.0,
        )

        with patch.object(scanner, "render_alert_snapshot_chart", return_value="/tmp/level.png"), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="", reply_markup=None: sent_photos.append(
                (str(chat_id), path, caption, reply_markup)
            )
            or True,
        ), patch.object(scanner, "send_telegram_message"):
            scanner.send_alert_group_to_chat(
                "TOKEN",
                "999",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                [alert],
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
                alert_candles=[
                    candle(0, 100, 105, 99, 104, 100),
                    candle(scanner.TIMEFRAME_MS, 104, 108, 103, 107, 250),
                ],
            )

        self.assertTrue(
            sent_photos[0][2].startswith(
                "✅ <b>BTC/USD — Zone Broken (Up)</b>\nWorth a look · zone confirmed"
            )
        )
        self.assertNotIn("Confirming:", sent_photos[0][2])

    def test_rsi_reading_still_renders_on_alert_caption(self):
        sent_photos = []
        level_break = severity_confirmed_break_alert(direction="breakout")
        rsi_reading = {
            "type": "rsi_cross_above_70",
            "label": "RSI above 70 — extended",
            "emoji": "🔥",
        }

        with patch.object(scanner, "render_alert_snapshot_chart", return_value="/tmp/rsi.png"), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="", reply_markup=None: sent_photos.append(
                (str(chat_id), path, caption, reply_markup)
            )
            or True,
        ), patch.object(scanner, "send_telegram_message"):
            scanner.send_alert_group_to_chat(
                "TOKEN",
                "999",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                [level_break, rsi_reading],
                ema_21=101,
                ema_55=99,
                current_rsi=72,
                volume_avg=100,
                alert_candles=[
                    candle(0, 100, 105, 99, 104, 100),
                    candle(scanner.TIMEFRAME_MS, 104, 108, 103, 107, 250),
                ],
            )

        self.assertIn("RSI reading: RSI above 70 — extended", sent_photos[0][2])

    def test_bare_confirmed_breakdown_caption_names_zone_break_without_confluence(self):
        sent_photos = []
        alert = severity_confirmed_break_alert(
            direction="breakdown",
            ema_trend="Neutral EMA trend, not aligned",
            volume_multiple=1.0,
        )

        with patch.object(scanner, "render_alert_snapshot_chart", return_value="/tmp/breakdown.png"), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="", reply_markup=None: sent_photos.append(
                (str(chat_id), path, caption, reply_markup)
            )
            or True,
        ), patch.object(scanner, "send_telegram_message"):
            scanner.send_alert_group_to_chat(
                "TOKEN",
                "999",
                "BTC/USD",
                candle(0, 100, 105, 99, 96, 250),
                [alert],
                ema_21=99,
                ema_55=101,
                current_rsi=42,
                volume_avg=100,
                alert_candles=[
                    candle(0, 100, 105, 99, 104, 100),
                    candle(scanner.TIMEFRAME_MS, 104, 108, 95, 96, 250),
                ],
            )

        caption = sent_photos[0][2]
        self.assertIn("✅ <b>BTC/USD — Zone Broken (Down)</b>", caption)
        self.assertIn("Worth a look · zone confirmed", caption)
        self.assertNotIn("Confluence", caption)
        self.assertNotIn("Confirming:", caption)

    def test_confirmed_breakout_caption_lists_confirming_context(self):
        sent_photos = []
        level_break = severity_confirmed_break_alert(
            direction="breakout",
            ema_trend="Bullish EMA trend",
            volume_multiple=2.5,
        )
        alerts = [
            level_break,
            {
                "type": "volume_spike",
                "label": "Volume Spike on an Up Candle",
                "emoji": "🟢",
                "volume_multiple": 2.5,
            },
            {
                "type": "ema_cross_above",
                "label": "EMA 21 crossed above EMA 55",
                "emoji": "🟢",
            },
        ]

        with patch.object(scanner, "render_alert_snapshot_chart", return_value="/tmp/breakout.png"), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="", reply_markup=None: sent_photos.append(
                (str(chat_id), path, caption, reply_markup)
            )
            or True,
        ), patch.object(scanner, "send_telegram_message"):
            scanner.send_alert_group_to_chat(
                "TOKEN",
                "999",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                alerts,
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
                alert_candles=[
                    candle(0, 100, 105, 99, 104, 100),
                    candle(scanner.TIMEFRAME_MS, 104, 108, 103, 107, 250),
                ],
            )

        caption = sent_photos[0][2]
        self.assertIn("✅ <b>BTC/USD — Zone Broken (Up)</b>", caption)
        self.assertIn(
            "Confirming: Volume context: Volume Spike on an Up Candle (2.50x) + EMA context: 21 crossed above 55",
            caption,
        )
        self.assertNotIn("Confluence", caption)

    def test_sent_alert_text_does_not_use_confluence_language(self):
        sent_photos = []
        sent_messages = []
        level_break = severity_confirmed_break_alert(direction="breakout")

        with patch.object(scanner, "render_alert_snapshot_chart", return_value="/tmp/zone.png"), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="", reply_markup=None: sent_photos.append(
                (str(chat_id), path, caption, reply_markup)
            )
            or True,
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((str(chat_id), text, reply_markup)),
        ):
            scanner.send_alert_group_to_chat(
                "TOKEN",
                "999",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                [level_break],
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
                alert_candles=[
                    candle(0, 100, 105, 99, 104, 100),
                    candle(scanner.TIMEFRAME_MS, 104, 108, 103, 107, 250),
                ],
            )

        user_facing = "\n".join([photo[2] for photo in sent_photos] + [message[1] for message in sent_messages])
        self.assertNotIn("Confluence", user_facing)

    def test_alert_research_button_reuses_wact_and_clears_keyboard_first(self):
        callback_query = {
            "id": "callback-1",
            "from": {"id": 111},
            "message": {
                "chat": {"id": -100, "type": "group"},
                "message_id": 44,
                "reply_markup": scanner.alert_research_keyboard("BTC/USD"),
            },
        }

        with patch.object(scanner, "answer_telegram_callback") as answer_callback, patch.object(
            scanner, "user_watchlist_symbols", return_value=[]
        ), patch.object(scanner, "enqueue_telegram_command_job", return_value=True) as enqueue_job, patch.object(
            scanner, "send_heavy_job_acknowledgment"
        ) as send_ack, patch.object(scanner, "clear_callback_message_keyboard") as clear_keyboard:
            handled = scanner.handle_watchlist_action_callback(
                "TOKEN",
                callback_query,
                "research:BTC/USD",
            )

        self.assertTrue(handled)
        answer_callback.assert_called_once_with("TOKEN", "callback-1")
        clear_keyboard.assert_called_once_with("TOKEN", callback_query)
        enqueue_job.assert_called_once_with(
            "research",
            "111",
            "/research BTC",
            source_chat={"id": "111", "type": "private"},
            from_user={"id": 111},
        )
        send_ack.assert_called_once_with("TOKEN", "111", "research", "/research BTC")

    def test_personal_watchlist_alert_respects_alertlevel_building(self):
        sent_alert_groups = []
        alert = severity_confirmed_break_alert(
            direction="breakout",
            ema_trend="Neutral EMA trend, not aligned",
            volume_multiple=1.0,
        )
        alerts = [alert]

        with patch.object(scanner, "users_watching_symbol", return_value=["111"]), patch.object(
            scanner,
            "user_preference",
            return_value=scanner.ALERT_SEVERITY_BUILDING,
        ), patch.object(
            scanner,
            "send_alert_group_to_chat",
            side_effect=lambda token, chat_id, symbol, candle_arg, alert_group, *args, **kwargs: sent_alert_groups.append(
                (str(chat_id), symbol, scanner.alert_severity_tier(alert_group), scanner.level_break_agreement_score(alert_group))
            )
            or True,
        ), patch.object(scanner, "save_state"):
            delivered = scanner.deliver_personal_watchlist_alerts(
                {},
                "TOKEN",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                alerts,
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
            )

        self.assertEqual(delivered, ["111"])
        self.assertEqual(sent_alert_groups, [("111", "BTC/USD", scanner.ALERT_SEVERITY_BUILDING, 0)])

    def test_personal_watchlist_alert_respects_alertlevel_strong(self):
        sent_alert_groups = []
        alert = severity_confirmed_break_alert(
            direction="breakout",
            ema_trend="Bullish EMA trend",
            volume_multiple=2.5,
        )
        alert["secondary_timeframe_context"] = secondary_timeframe_context_for_bias("bullish")
        alerts = [alert]

        with patch.object(scanner, "users_watching_symbol", return_value=["222"]), patch.object(
            scanner,
            "user_preference",
            return_value=scanner.ALERT_SEVERITY_STRONG,
        ), patch.object(
            scanner,
            "send_alert_group_to_chat",
            side_effect=lambda token, chat_id, symbol, candle_arg, alert_group, *args, **kwargs: sent_alert_groups.append(
                (str(chat_id), symbol, scanner.alert_severity_tier(alert_group))
            )
            or True,
        ), patch.object(scanner, "save_state"):
            delivered = scanner.deliver_personal_watchlist_alerts(
                {},
                "TOKEN",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                alerts,
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
            )

        self.assertEqual(delivered, ["222"])
        self.assertEqual(sent_alert_groups, [("222", "BTC/USD", scanner.ALERT_SEVERITY_STRONG)])

    def test_alertlevel_strong_user_does_not_receive_low_agreement_break(self):
        sent_alert_groups = []
        alert = severity_confirmed_break_alert(
            direction="breakout",
            ema_trend="Neutral EMA trend, not aligned",
            volume_multiple=1.0,
        )
        alerts = [alert]

        with patch.object(scanner, "users_watching_symbol", return_value=["222"]), patch.object(
            scanner,
            "user_preference",
            return_value=scanner.ALERT_SEVERITY_STRONG,
        ), patch.object(
            scanner,
            "send_alert_group_to_chat",
            side_effect=lambda *args, **kwargs: sent_alert_groups.append(args) or True,
        ), patch.object(scanner, "save_state"):
            delivered = scanner.deliver_personal_watchlist_alerts(
                {},
                "TOKEN",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                alerts,
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
            )

        self.assertEqual(delivered, [])
        self.assertEqual(sent_alert_groups, [])

    def test_alertlevel_strong_user_receives_clean_high_agreement_break(self):
        sent_alert_groups = []
        alert = severity_confirmed_break_alert(
            direction="breakout",
            ema_trend="Bullish EMA trend",
            volume_multiple=2.5,
        )
        alert["secondary_timeframe_context"] = secondary_timeframe_context_for_bias("bullish")
        alerts = [alert]

        with patch.object(scanner, "users_watching_symbol", return_value=["222"]), patch.object(
            scanner,
            "user_preference",
            return_value=scanner.ALERT_SEVERITY_STRONG,
        ), patch.object(
            scanner,
            "send_alert_group_to_chat",
            side_effect=lambda token, chat_id, symbol, candle_arg, alert_group, *args, **kwargs: sent_alert_groups.append(
                (
                    str(chat_id),
                    symbol,
                    scanner.alert_severity_tier(alert_group),
                    [alert_item["type"] for alert_item in alert_group],
                )
            )
            or True,
        ), patch.object(scanner, "save_state"):
            delivered = scanner.deliver_personal_watchlist_alerts(
                {},
                "TOKEN",
                "BTC/USD",
                candle(0, 100, 105, 99, 104, 250),
                alerts,
                ema_21=101,
                ema_55=99,
                current_rsi=58,
                volume_avg=100,
            )

        self.assertEqual(delivered, ["222"])
        self.assertEqual(
            sent_alert_groups,
            [("222", "BTC/USD", scanner.ALERT_SEVERITY_STRONG, ["live:breakout:100:confirmation"])],
        )

    def test_research_command_sends_image_cards_when_renderer_succeeds(self):
        sent_groups = []

        with patch.object(scanner, "build_research_command_message", return_value="AAVE PRB"), patch.dict(
            scanner.LAST_RESEARCH_CARD_DATA,
            {"AAVE/USD": [{"title": "The Read"}]},
        ), patch.object(
            scanner, "render_research_cards", return_value=["/tmp/prb-card-1.png", "/tmp/prb-card-2.png"]
        ), patch.object(
            scanner,
            "send_telegram_media_group",
            side_effect=lambda token, chat_id, paths: sent_groups.append((str(chat_id), list(paths))) or True,
        ), patch.object(
            scanner, "send_telegram_photo", side_effect=AssertionError("individual photos should not be sent")
        ), patch.object(
            scanner, "send_telegram_message", side_effect=AssertionError("text fallback should not be sent")
        ):
            scanner.handle_research_command(
                object(),
                "TOKEN",
                "999",
                "/research AAVE",
                source_chat={"id": "999", "type": "private"},
            )

        self.assertEqual(sent_groups, [("999", ["/tmp/prb-card-1.png", "/tmp/prb-card-2.png"])])

    def test_research_cards_pass_snapshot_chart_to_prb_renderer(self):
        sent_groups = []
        sent_photos = []
        captured = {}
        chart_data = {
            "candles": [
                {"time": 0, "open": 100, "high": 105, "low": 99, "close": 104, "volume": 100},
                {"time": scanner.TIMEFRAME_MS, "open": 104, "high": 108, "low": 103, "close": 107, "volume": 250},
            ],
            "current_price": 107,
            "supports": [95],
            "resistances": [110],
            "ema21": [101, 102],
            "ema55": [99, 100],
        }

        def fake_render_research_cards(card_data, logo_path=None, output_dir=None):
            captured["card_data"] = card_data
            captured["logo_path"] = logo_path
            return ["/tmp/prb-card-with-chart.png"]

        with patch.object(scanner, "generate_levels_chart", return_value="/tmp/prb-snapshot.png") as generate_chart, patch.dict(
            scanner.LAST_RESEARCH_CARD_DATA,
            {"BTC/USD": [{"title": "The Read"}]},
        ), patch.object(
            scanner, "render_research_cards", side_effect=fake_render_research_cards
        ), patch.object(
            scanner,
            "send_telegram_media_group",
            side_effect=lambda token, chat_id, paths: sent_groups.append((str(chat_id), list(paths))) or True,
        ), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path: sent_photos.append((str(chat_id), path)) or True,
        ):
            self.assertTrue(
                scanner.send_research_cards(
                    "TOKEN",
                    "999",
                    "BTC PRB",
                    symbol="BTC/USD",
                    chart_data=chart_data,
                )
            )

        generate_chart.assert_called_once()
        self.assertEqual(sent_photos, [("999", "/tmp/prb-snapshot.png")])
        self.assertEqual(captured["card_data"], [{"title": "The Read"}])
        self.assertEqual(captured["logo_path"], scanner.POINKLE_RESEARCH_EMBLEM_PATH)
        self.assertEqual(sent_groups, [("999", ["/tmp/prb-card-with-chart.png"])])

    def test_research_cards_fall_back_to_individual_photos_when_media_group_fails(self):
        sent_photos = []

        with patch.dict(scanner.LAST_RESEARCH_CARD_DATA, {"AAVE/USD": [{"title": "The Read"}]}), patch.object(
            scanner, "render_research_cards", return_value=["/tmp/prb-card-1.png", "/tmp/prb-card-2.png"]
        ), patch.object(
            scanner, "send_telegram_media_group", return_value=False
        ), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path: sent_photos.append((str(chat_id), path)) or True,
        ):
            self.assertTrue(scanner.send_research_cards("TOKEN", "999", "AAVE PRB", symbol="AAVE/USD"))

        self.assertEqual(
            sent_photos,
            [
                ("999", "/tmp/prb-card-1.png"),
                ("999", "/tmp/prb-card-2.png"),
            ],
        )

    def test_research_command_falls_back_to_text_when_renderer_fails(self):
        sent_messages = []

        with patch.object(scanner, "build_research_command_message", return_value="AAVE PRB"), patch.dict(
            scanner.LAST_RESEARCH_CARD_DATA,
            {"AAVE/USD": [{"title": "The Read"}]},
        ), patch.object(
            scanner, "render_research_cards", side_effect=RuntimeError("render failed")
        ), patch.object(
            scanner, "send_telegram_photo", side_effect=AssertionError("no card should be sent")
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_research_command(
                object(),
                "TOKEN",
                "999",
                "/research AAVE",
                source_chat={"id": "999", "type": "private"},
            )

        self.assertEqual(sent_messages, [("999", "AAVE PRB")])

    def test_levels_group_command_sends_full_report_by_dm_only(self):
        sent_messages = []
        original_username = scanner.BOT_USERNAME
        scanner.BOT_USERNAME = "Poinkle_Bot"

        try:
            with patch.object(scanner, "build_levels_command_message", return_value="FULL LEVELS REPORT"), patch.object(
                scanner, "send_levels_chart", return_value=False
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_levels_command(
                    object(),
                    "TOKEN",
                    "-100",
                    "/snapshot BTC",
                    source_chat={"id": "-100", "type": "supergroup"},
                    from_user={"id": 777},
                )
        finally:
            scanner.BOT_USERNAME = original_username

        self.assertEqual(sent_messages[0], ("777", "FULL LEVELS REPORT"))
        self.assertEqual(
            sent_messages[1],
            (
                "-100",
                "Sent BTC/USD levels to your DM. If you did not receive it, start the bot first: @Poinkle_Bot",
            ),
        )

    def test_levels_group_command_handles_dm_failure(self):
        sent_messages = []
        original_username = scanner.BOT_USERNAME
        scanner.BOT_USERNAME = "Poinkle_Bot"

        def fake_send(token, chat_id, text):
            if str(chat_id) == "777":
                raise RuntimeError("Forbidden")
            sent_messages.append((str(chat_id), text))

        try:
            with patch.object(scanner, "build_levels_command_message", return_value="FULL LEVELS REPORT"), patch.object(
                scanner, "send_levels_chart", return_value=False
            ), patch.object(
                scanner, "send_telegram_message", side_effect=fake_send
            ):
                scanner.handle_levels_command(
                    object(),
                    "TOKEN",
                    "-100",
                    "/snapshot BTC",
                    source_chat={"id": "-100", "type": "group"},
                    from_user={"id": 777},
                )
        finally:
            scanner.BOT_USERNAME = original_username

        self.assertEqual(
            sent_messages,
            [
                (
                    "-100",
                    "I can't DM you yet. Please start me first: @Poinkle_Bot, then try /snapshot SYMBOL again.",
                )
            ],
        )

    def test_levels_private_command_replies_in_dm(self):
        sent_messages = []

        with patch.object(scanner, "build_levels_command_message", return_value="FULL LEVELS REPORT"), patch.object(
            scanner, "send_levels_chart", return_value=False
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_levels_command(
                object(),
                "TOKEN",
                "777",
                "/snapshot BTC",
                source_chat={"id": "777", "type": "private"},
                from_user={"id": 777},
            )

        self.assertEqual(sent_messages, [("777", "FULL LEVELS REPORT")])

    def test_levels_symbol_map_accepts_new_symbols_and_case(self):
        self.assertEqual(scanner.normalize_symbol("tao"), "TAO/USD")
        self.assertEqual(scanner.normalize_symbol("Tao"), "TAO/USD")
        self.assertEqual(scanner.normalize_symbol("JASMY"), "JASMY/USD")
        self.assertEqual(scanner.normalize_symbol("FARTCOIN"), "FARTCOIN/USD")
        self.assertEqual(scanner.normalize_symbol("hype"), "HYPE/USD")
        self.assertEqual(scanner.normalize_symbol("pengu"), "PENGU/USD")
        self.assertEqual(scanner.normalize_symbol("bnb"), "BNB/USD")
        self.assertEqual(scanner.normalize_symbol("ZEC"), "ZEC/USD")
        self.assertEqual(scanner.normalize_symbol("XMR"), "XMR/USD")
        self.assertEqual(scanner.normalize_symbol("LTC"), "LTC/USD")
        self.assertIsNone(scanner.normalize_symbol("XAU"))
        self.assertIsNone(scanner.normalize_symbol("XAO"))
        self.assertIsNone(scanner.normalize_symbol("GOLD"))
        self.assertIsNone(scanner.normalize_symbol("dogfi"))
        self.assertIsNone(scanner.normalize_symbol("NOTREAL"))

    def test_watchlist_is_single_master_symbol_source(self):
        watchlist_data = __import__("json").loads((PROJECT_DIR / "watchlist.json").read_text())
        expected_watchlist = [
            item["symbol"].upper()
            for item in watchlist_data["symbols"]
            if item.get("enabled", True)
        ]

        self.assertEqual(scanner.WATCHLIST, expected_watchlist)
        self.assertFalse(hasattr(scanner, "LEVELS_SYMBOLS"))
        self.assertEqual(set(self.original_key_levels), set(scanner.WATCHLIST))

    def test_expanded_watchlist_contains_140_enabled_unique_symbols_after_cleanup(self):
        watchlist_data = __import__("json").loads((PROJECT_DIR / "watchlist.json").read_text())
        enabled_symbols = [
            item["symbol"].upper()
            for item in watchlist_data["symbols"]
            if item.get("enabled", True)
        ]
        disabled_symbols = [
            item["symbol"].upper()
            for item in watchlist_data["symbols"]
            if not item.get("enabled", True)
        ]

        self.assertEqual(len(enabled_symbols), 140)
        self.assertEqual(len(set(enabled_symbols)), 140)
        self.assertTrue(all(symbol.endswith("/USD") for symbol in enabled_symbols))
        self.assertIn("BTC/USD", enabled_symbols)
        self.assertIn("BRETT/USD", enabled_symbols)
        self.assertIn("POL/USD", enabled_symbols)
        self.assertNotIn("MATIC/USD", enabled_symbols)
        self.assertNotIn("USDC/USD", enabled_symbols)
        self.assertNotIn("WBTC/USD", enabled_symbols)
        self.assertNotIn("XAU/USD", enabled_symbols)
        self.assertIn("USDC/USD", disabled_symbols)
        self.assertIn("WBTC/USD", disabled_symbols)
        self.assertIn("XAU/USD", disabled_symbols)
        self.assertIn("EOS/USD", disabled_symbols)
        self.assertIn("HOT/USD", disabled_symbols)
        self.assertIn("NEXO/USD", disabled_symbols)

    def test_scan_cycle_benchmark_reports_cycle_time_and_safe_target(self):
        benchmark = scanner.scan_cycle_benchmark(
            44.0,
            scanned_symbols=44,
            skipped_symbols=6,
            failed_symbols=2,
        )
        message = scanner.format_scan_cycle_benchmark(benchmark)

        self.assertEqual(benchmark["target_symbols"], 150)
        self.assertEqual(benchmark["estimated_public_requests"], 88)
        self.assertEqual(benchmark["rate_limit_floor_seconds"], 8.8)
        self.assertEqual(benchmark["target_rate_limit_floor_seconds"], 30.0)
        self.assertIn("44 scanned, 6 skipped, 2 failed in 44.00s", message)
        self.assertIn("150-symbol target floor: 30.0s", message)

    def test_alert_delivery_metric_records_delay_from_candle_close(self):
        state = {}
        alert = {"type": "volume_spike", "label": "Bullish Volume Spike"}
        closed_candle = candle(1_700_000_000_000, 100, 105, 99, 104, 250)
        sent_at = (1_700_000_000_000 + scanner.TIMEFRAME_MS) / 1000 + 90

        metric = scanner.record_alert_delivery_metric(
            state,
            "BTC/USD",
            closed_candle,
            [alert],
            sent_at=sent_at,
            delivery_type="photo",
        )

        self.assertEqual(metric["symbol"], "BTC/USD")
        self.assertEqual(metric["alert_types"], ["volume_spike"])
        self.assertEqual(metric["delay_seconds"], 90)
        self.assertEqual(metric["delivery_type"], "photo")
        self.assertEqual(scanner.alert_delivery_summary(state["__alert_delivery_metrics"]), "Alert delivery delay over last 1 alert(s): min 90.0s, max 90.0s, avg 90.0s.")

    def test_append_diagnostic_record_creates_valid_jsonl_with_logged_at(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner.DIAGNOSTICS_FILE = Path(tmpdir) / "diagnostics" / "alert_diagnostics.jsonl"

            scanner.append_diagnostic_record({"record_type": "delivery", "symbol": "BTC/USD"})

            self.assertTrue(scanner.DIAGNOSTICS_FILE.exists())
            lines = scanner.DIAGNOSTICS_FILE.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["record_type"], "delivery")
            self.assertEqual(record["symbol"], "BTC/USD")
            self.assertIn("logged_at", record)

    def test_append_diagnostic_record_catches_write_failure(self):
        warnings = []

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "log_warn", side_effect=lambda message: warnings.append(message)
        ), patch.object(scanner, "DIAGNOSTICS_FILE", Path(tmpdir)):
            scanner.append_diagnostic_record({"record_type": "delivery"})

        self.assertEqual(len(warnings), 1)
        self.assertIn("Could not write diagnostic record", warnings[0])

    def test_run_once_logs_scan_failure_diagnostic_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            diagnostics_file = Path(tmpdir) / "diagnostics.jsonl"
            with patch.object(scanner, "DIAGNOSTICS_FILE", diagnostics_file), patch.object(
                scanner, "WATCHLIST", ["FAIL/USD"]
            ), patch.object(scanner, "load_user_watchlists", return_value={}), patch.object(
                scanner,
                "scan_symbol",
                side_effect=RuntimeError("timeout fetching candles"),
            ), patch.object(scanner, "log_info"), patch.object(scanner, "throttled_log_warn"):
                scanner.run_once(None, "token", "chat", {})

            lines = diagnostics_file.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["record_type"], "scan_failure")
        self.assertEqual(record["symbol"], "FAIL/USD")
        self.assertEqual(record["error_type"], "RuntimeError")
        self.assertEqual(record["error_message"], "timeout fetching candles")
        self.assertEqual(record["error_class"], "network_or_rate_limit")

    def test_loop_phase_benchmark_formats_phase_breakdown(self):
        message = scanner.format_loop_phase_benchmark(
            command_seconds=1.25,
            scan_seconds=30.0,
            user_alert_seconds=2.5,
            active_trade_seconds=0.75,
        )

        self.assertIn("commands 1.25s", message)
        self.assertIn("scan 30.00s", message)
        self.assertIn("user alerts 2.50s", message)
        self.assertIn("active trades 0.75s", message)
        self.assertIn("total before sleep 34.50s", message)

    def test_accuracy_audit_snapshot_logs_selected_symbol_metrics(self):
        logged = []

        with patch.object(scanner, "accuracy_audit_symbols", return_value={"BTC/USD"}), patch.object(
            scanner,
            "log_info",
            side_effect=lambda message: logged.append(message),
        ), patch.object(scanner, "append_diagnostic_record") as append_record:
            scanner.log_accuracy_audit_snapshot(
                "BTC/USD",
                candle(1_700_000_000_000, 100, 105, 99, 104, 250),
                current_market_price=104.5,
                ema_21=101.25,
                ema_55=99.75,
                current_rsi=58.123,
            )

        self.assertEqual(len(logged), 1)
        self.assertIn("Accuracy audit snapshot: BTC/USD", logged[0])
        self.assertIn("price 104.5", logged[0])
        self.assertIn("RSI14 58.12", logged[0])
        self.assertIn("EMA21 101.25", logged[0])
        self.assertIn("EMA55 99.75", logged[0])
        append_record.assert_called_once()
        self.assertEqual(append_record.call_args.args[0]["record_type"], "accuracy_audit")
        self.assertEqual(append_record.call_args.args[0]["symbol"], "BTC/USD")

    def test_levels_command_accepts_watchlist_json_symbols(self):
        sent_messages = []
        accepted_symbols = []

        def fake_message(exchange, symbol):
            accepted_symbols.append(symbol)
            return f"{symbol} report"

        with patch.object(scanner, "build_levels_command_message", side_effect=fake_message), patch.object(
            scanner, "send_levels_chart", return_value=False
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            for command in ["/snapshot ZEC", "/snapshot XMR", "/snapshot LTC"]:
                scanner.handle_levels_command(
                    object(),
                    "TOKEN",
                    "999",
                    command,
                    source_chat={"id": "999", "type": "private"},
                    from_user={"id": 999},
                )

        self.assertEqual(
            accepted_symbols,
            ["ZEC/USD", "XMR/USD", "LTC/USD"],
        )
        self.assertEqual(sent_messages[-1], ("999", "LTC/USD report"))

    def test_research_command_accepts_watchlist_json_symbol_with_fallback_prb(self):
        sent_photos = []

        with patch.object(scanner, "build_research_command_message", return_value="ZEC PRB fallback") as build_message, patch.object(
            scanner,
            "send_research_cards",
            side_effect=lambda token, chat_id, text, **kwargs: sent_photos.append((str(chat_id), text, kwargs.get("symbol"))) or True,
        ), patch.object(
            scanner, "send_telegram_message", side_effect=AssertionError("text fallback should not be used")
        ):
            scanner.handle_research_command(
                object(),
                "TOKEN",
                "999",
                "/research ZEC",
                source_chat={"id": "999", "type": "private"},
            )

        build_message.assert_called_once_with(ANY, "ZEC/USD")
        self.assertEqual(sent_photos, [("999", "ZEC PRB fallback", "ZEC/USD")])

    def test_validate_watchlist_against_exchange_splits_unsupported_symbols(self):
        class ExchangeWithMarkets:
            def load_markets(self):
                return {"BTC/USD": {}, "ZEC/USD": {}}

        with patch.object(scanner, "log_warn") as warn:
            supported, unsupported = scanner.validate_watchlist_against_exchange(
                ExchangeWithMarkets(),
                ["BTC/USD", "ZEC/USD", "XMR/USD", "EOS/USD", "HOT/USD", "NEXO/USD"],
            )

        self.assertEqual(supported, ["BTC/USD", "ZEC/USD", "XMR/USD"])
        self.assertEqual(unsupported, ["EOS/USD", "HOT/USD", "NEXO/USD"])
        self.assertEqual(warn.call_count, 2)

    def test_run_once_skips_unsupported_symbols_for_session(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD", "XMR/USD", "ZEC/USD"]
        scanner.UNSUPPORTED_SYMBOLS_THIS_SESSION.update({"XMR/USD"})
        scanned_symbols = []

        try:
            with patch.object(
                scanner,
                "scan_symbol",
                side_effect=lambda exchange, symbol: scanned_symbols.append(symbol)
                or scanner.ScanSymbolResult(
                    previous_candle=candle(0, 99, 101, 98, 100, 100),
                    candle=candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 100),
                    alerts=[],
                    ema_21=100,
                    ema_55=99,
                    current_rsi=50,
                    current_atr_14=1,
                    volume_avg=100,
                    range_low=90,
                    range_high=110,
                    closed_candles=[
                        candle(0, 99, 101, 98, 100, 100),
                        candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 100),
                    ],
                    key_levels={"support": [90], "resistance": [110]},
                    signal_state={"alerts": [], "volume_multiple": 1.0},
                ),
            ), patch.object(scanner, "get_current_market_price", return_value=101), patch.object(
                scanner, "print_compact_scan_summary"
            ), patch.object(scanner, "load_user_watchlists", return_value={}), patch.object(scanner, "save_state"):
                scanner.run_once(object(), "TOKEN", "999", {})
        finally:
            scanner.WATCHLIST = original_watchlist
            scanner.UNSUPPORTED_SYMBOLS_THIS_SESSION.discard("XMR/USD")

        self.assertEqual(scanned_symbols, ["BTC/USD", "ZEC/USD"])

    def test_warning_throttle_keys_are_stable(self):
        fallback = make_ohlcv_series([100, 101, 102])
        failing_exchange = FakeExchange({"15m": []}, ticker_price=100, failing_timeframes={"4h"})

        with patch.object(scanner, "throttled_log_warn") as warn:
            scanner.fetch_closed_ohlcv(failing_exchange, "BTC/USD", "4h", 180, fallback=fallback)

        self.assertEqual(warn.call_args.args[1], "4h:fallback")

        class FailingOhlcvExchange:
            def fetch_ohlcv(self, symbol, timeframe, limit):
                raise RuntimeError("raw moving error")

        with patch.object(scanner, "throttled_log_warn") as warn:
            with self.assertRaises(scanner.MarketDataError):
                scanner.fetch_closed_ohlcv(FailingOhlcvExchange(), "BTC/USD", "4h", 180)

        self.assertEqual(
            warn.call_args.args[1],
            "4h:BTC/USD: Coinbase candle fetch failed. Will retry quietly.",
        )

        with patch.object(scanner, "throttled_log_warn") as warn:
            scanner.get_current_market_price(object(), "BTC/USD", 100)

        self.assertEqual(warn.call_args.args[1], "ticker")

        with patch.object(scanner, "build_levels_scan_snapshot", side_effect=RuntimeError("boom")), patch.object(
            scanner, "load_user_alerts", return_value={"777": {"BTC": {"type": "support", "enabled": True}}}
        ), patch.object(scanner, "throttled_log_warn") as warn:
            scanner.check_user_level_alerts(object(), "TOKEN")

        self.assertEqual(warn.call_args.args[1], "user-alert:support")

        with patch.object(scanner, "get_telegram_updates", side_effect=RuntimeError("poll boom")), patch.object(
            scanner, "throttled_log_warn"
        ) as warn:
            scanner.process_telegram_commands(object(), "TOKEN", "999", {})

        self.assertEqual(warn.call_args.args[1], "updates")

        class FailingTradeExchange:
            def fetch_ohlcv(self, symbol, timeframe, limit):
                raise RuntimeError("trade boom")

        state = {
            "__active_trades": {
                "BTC/USD": {
                    "last_monitor_at": 0,
                    "started_at": scanner.current_time_ms(),
                }
            }
        }
        with patch.object(scanner, "TRADE_TRACKING_TELEGRAM_ENABLED", True), patch.object(
            scanner, "load_bot_config", return_value={"live_alerts_enabled": True}
        ), patch.object(
            scanner, "throttled_log_warn"
        ) as warn:
            scanner.monitor_active_trades(FailingTradeExchange(), "TOKEN", "999", state)

        self.assertEqual(warn.call_args.args[1], "active-trade")

    def test_levels_command_returns_unavailable_message_for_bad_or_failed_symbol(self):
        sent_messages = []

        with patch.object(scanner, "send_telegram_message", side_effect=lambda token, chat_id, text: sent_messages.append(text)):
            scanner.handle_levels_command(object(), "TOKEN", "999", "/snapshot NOTREAL")

        self.assertEqual(
            sent_messages[-1],
            (
                "I don't have NOTREAL in my list yet. Try /snapshot with one of the coins "
                "I track — or type /snapshot on its own to pick from a list."
            ),
        )

        failing_exchange = FakeExchange({}, ticker_price=0, failing_timeframes={scanner.TIMEFRAME})
        with patch.object(scanner, "send_telegram_message", side_effect=lambda token, chat_id, text: sent_messages.append(text)):
            scanner.handle_levels_command(failing_exchange, "TOKEN", "999", "/snapshot BTC")

        self.assertEqual(sent_messages[-1], "I couldn't build that card just now. Try again in a moment.")

    def test_levels_command_uses_wide_zones_not_micro_levels(self):
        current_price = 62300
        fifteen_minute_closes = [61000 + (index % 20) * 80 for index in range(119)] + [current_price]
        four_hour_closes = [59000 + (index % 16) * 450 for index in range(179)] + [current_price]
        daily_closes = [52000 + (index % 35) * 650 for index in range(179)] + [current_price]
        weekly_closes = [38000 + (index % 18) * 1800 for index in range(103)] + [current_price]
        fake_exchange = FakeExchange(
            {
                "15m": make_ohlcv_series(fifteen_minute_closes),
                "1h": make_ohlcv_series(four_hour_closes, step=3_600_000),
                "1d": make_ohlcv_series(daily_closes, step=86_400_000),
                "1w": make_ohlcv_series(weekly_closes, step=604_800_000),
            },
            ticker_price=current_price,
        )

        message = scanner.build_levels_command_message(fake_exchange, "BTC/USD")

        self.assertTrue(message.startswith("📍 POINKLE SNAPSHOT — BTC / USD"))
        self.assertIn("💰 PRICE\n62,300", message)
        self.assertIn("🎯 FOCUS\nApproaching Higher-Timeframe Support", message)
        self.assertIn("🧠 SETUP GRADE\nB — Good accumulation", message)
        chart_data = scanner.LAST_LEVELS_CHART_DATA["BTC/USD"]
        self.assertIn(60000.0, chart_data["supports"])
        self.assertIn(65000.0, chart_data["resistances"])
        self.assertNotIn(62100, chart_data["supports"])
        self.assertNotIn(61800, chart_data["supports"])
        self.assertNotIn("62,100", message)
        self.assertNotIn("61,800", message)


if __name__ == "__main__":
    unittest.main()
