import importlib.util
import json
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

    def test_telegram_sends_html_parse_mode_for_messages_and_photos(self):
        class FakeResponse:
            status_code = 200
            text = "OK"

        posted = []

        class FakeRequests:
            @staticmethod
            def post(url, **kwargs):
                posted.append((url, kwargs))
                return FakeResponse()

        with tempfile.NamedTemporaryFile() as photo, patch.object(scanner, "requests", FakeRequests):
            scanner.send_telegram_message("TOKEN", "999", "<b>Hello</b>")
            self.assertTrue(scanner.send_telegram_photo("TOKEN", "999", photo.name, caption="<b>Card</b>"))

        self.assertEqual(posted[0][1]["json"]["parse_mode"], "HTML")
        self.assertEqual(posted[0][1]["json"]["disable_web_page_preview"], True)
        self.assertEqual(posted[1][1]["data"]["parse_mode"], "HTML")

    def test_telegram_media_group_uses_multipart_attachments(self):
        class FakeResponse:
            status_code = 200
            text = "OK"

        posted = []

        class FakeRequests:
            @staticmethod
            def post(url, **kwargs):
                posted.append((url, kwargs))
                return FakeResponse()

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(scanner, "requests", FakeRequests):
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

    def test_register_bot_commands_posts_public_command_list(self):
        class FakeResponse:
            status_code = 200
            text = "OK"

        posted = []

        class FakeRequests:
            @staticmethod
            def post(url, **kwargs):
                posted.append((url, kwargs))
                return FakeResponse()

        with patch.object(scanner, "requests", FakeRequests):
            self.assertTrue(scanner.register_bot_commands("TOKEN"))

        url, kwargs = posted[0]
        command_names = [item["command"] for item in kwargs["json"]["commands"]]
        self.assertTrue(url.endswith("/setMyCommands"))
        self.assertEqual(
            command_names,
            [
                "snapshot",
                "snap",
                "research",
                "levels",
                "alerts",
                "myalerts",
                "mike",
                "guide",
                "explain",
                "learn",
                "coins",
                "help",
                "start",
            ],
        )
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

    def test_mike_command_returns_mikes_curated_symbols_and_reports_failures(self):
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
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ), patch.object(
            scanner, "send_mike_list_card", return_value=False
        ):
            scanner.handle_mike_command(object(), "TOKEN", "999")

        self.assertEqual(seen_symbols, ["BTC/USD", "ETH/USD", "NOTREAL/USD"])
        self.assertEqual(sent_messages[0][0], "999")
        self.assertEqual(len(sent_messages[0][1].splitlines()), 3)
        self.assertIn("BTC: Price 101 | Trend bullish | RSI 56.00", sent_messages[0][1])
        self.assertIn("ETH: Price 102 | Trend bullish | RSI 57.00", sent_messages[0][1])
        self.assertIn("NOTREAL: Price market data unavailable | Trend n/a | RSI n/a", sent_messages[0][1])

    def test_lightweight_confluence_requires_two_distinct_signal_types(self):
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
            "label": "RSI crossed above 70",
            "emoji": "🔥",
        }

        self.assertFalse(scanner.has_lightweight_confluence([volume_alert]))
        self.assertFalse(scanner.has_lightweight_confluence([ema_alert]))
        self.assertFalse(scanner.has_lightweight_confluence([rsi_alert]))
        self.assertFalse(scanner.has_lightweight_confluence([volume_alert, volume_alert.copy()]))
        self.assertTrue(scanner.has_lightweight_confluence([volume_alert, ema_alert]))
        self.assertTrue(scanner.has_lightweight_confluence([ema_alert, rsi_alert]))

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

    def test_monitor_active_trades_mutes_telegram_but_updates_state_when_live(self):
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

        with patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
            scanner, "send_telegram_message", side_effect=AssertionError("tracking send should be muted")
        ), patch.object(scanner, "save_state") as save_state:
            scanner.monitor_active_trades(TrackingExchange(candles), "TOKEN", "MAIN_CHAT", state)

        trade = state["__active_trades"]["BTC/USD"]
        self.assertEqual(trade["last_status"], "Weakening")
        self.assertGreater(trade["last_monitor_at"], 0)
        self.assertIsNotNone(trade["last_rsi"])
        self.assertEqual(trade["last_volume"], 100)
        save_state.assert_called()

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
        self.assertIn("🧠 PATIENCE", message)
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
        scan_result = (
            candle(0, 99, 101, 98, 100, 100),
            candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 200),
            [volume_alert, ema_alert],
            101,
            99,
            55,
            1,
            100,
            90,
            110,
        )

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
            ), patch.object(scanner, "save_state"):
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
        scan_result = (
            candle(0, 99, 101, 98, 100, 100),
            candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 200),
            [volume_alert, ema_alert],
            101,
            99,
            55,
            1,
            100,
            90,
            110,
        )

        try:
            with patch.object(scanner, "scan_symbol", return_value=scan_result), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(
                scanner, "build_level_alerts", side_effect=AssertionError("level alerts disabled")
            ), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, *args, **kwargs: sent_alert_groups.append((str(chat_id), args)),
            ), patch.object(
                scanner, "load_bot_config", return_value={"live_alerts_enabled": False}
            ), patch.object(scanner, "save_state"):
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

        def fake_scan_symbol(exchange, symbol):
            call_counts[symbol] += 1
            candle_time = scanner.TIMEFRAME_MS * call_counts[symbol]
            return (
                candle(candle_time - scanner.TIMEFRAME_MS, 99, 101, 98, 100, 100),
                candle(candle_time, 100, 102, 99, 101, 250),
                [volume_alert.copy(), ema_alert.copy()],
                101,
                99,
                55,
                1,
                100,
                90,
                110,
            )

        state = {}
        try:
            with patch.object(scanner, "scan_symbol", side_effect=fake_scan_symbol), patch.object(
                scanner, "get_current_market_price", return_value=101
            ), patch.object(scanner, "build_level_alerts", return_value=[]), patch.object(
                scanner,
                "send_alert_group_to_chat",
                side_effect=lambda token, chat_id, *args, **kwargs: sent_alert_groups.append((str(chat_id), args)),
            ), patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
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

    def test_rolling_confluence_combines_signals_across_scan_cycles(self):
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
            return (
                candle(candle_time - scanner.TIMEFRAME_MS, 99, 101, 98, 100, 100),
                candle(candle_time, 100, 102, 99, 101, 250),
                alerts,
                101,
                99,
                55,
                1,
                100,
                90,
                110,
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
                scanner, "save_state"
            ), patch.object(scanner.time, "time", side_effect=lambda: current_time["now"]):
                state = {}
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
                current_time["now"] += scanner.ROLLING_CONFLUENCE_WINDOW_SECONDS
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(len(sent_alert_groups), 1)
        self.assertEqual(set(sent_alert_groups[0]), {"volume_spike", "ema_cross_above"})
        self.assertIn("tier2", state["__scan_alert_cooldowns"]["BTC/USD"])

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
            return (
                candle(candle_time - scanner.TIMEFRAME_MS, 99, 101, 98, 100, 100),
                candle(candle_time, 100, 102, 99, 101, 250),
                [alerts_by_call[call_count[symbol] - 1].copy()],
                101,
                99,
                55,
                1,
                100,
                90,
                110,
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
        scan_result = (
            candle(0, 99, 101, 98, 100, 100),
            candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 100),
            [],
            101,
            99,
            55,
            1,
            100,
            90,
            110,
        )

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
        scan_result = (
            candle(0, 99, 101, 98, 100, 100),
            candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 250),
            [volume_alert, ema_alert],
            101,
            99,
            55,
            1,
            100,
            90,
            110,
        )

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

    def test_run_once_sends_daily_alert_when_secondary_context_is_unavailable(self):
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
        scan_result = (
            candle(0, 99, 101, 98, 100, 100),
            candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 250),
            [volume_alert, ema_alert],
            101,
            99,
            55,
            1,
            100,
            90,
            110,
        )

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
                scanner, "save_state"
            ):
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", {})
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(sent_alert_groups, [["volume_spike", "ema_cross_above"]])

    def test_run_once_suppresses_level_attempts_without_suppressing_confluence(self):
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
        scan_result = (
            candle(0, 99, 101, 98, 100, 100),
            candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 250),
            [volume_alert, ema_alert],
            101,
            99,
            55,
            1,
            100,
            90,
            110,
        )
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
                scanner, "save_state"
            ):
                scanner.run_once(object(), "TOKEN", "MAIN_CHAT", state)
        finally:
            scanner.WATCHLIST = original_watchlist

        self.assertEqual(sent_alert_groups, [["volume_spike", "ema_cross_above"]])
        self.assertEqual(
            state["BTC/USD"]["sent_alerts"]["live:breakout:100:early_warning"],
            f"{scanner.TIMEFRAME_MS}:live:breakout:100:early_warning",
        )
        self.assertEqual(
            state["__active_trades"]["BTC/USD"]["source_alert"],
            "Breakout Attempt",
        )

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
        scan_result = (
            candle(0, 99, 101, 98, 100, 100),
            candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 200),
            [volume_alert, ema_alert],
            101,
            99,
            55,
            1,
            100,
            90,
            110,
        )

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
                    scanner,
                    "send_alert_group_to_chat",
                    side_effect=lambda token, chat_id, *args, **kwargs: sent_alert_groups.append((str(chat_id), args)),
                ), patch.object(scanner, "save_state"):
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
                    scanner,
                    "send_alert_group_to_chat",
                    side_effect=lambda token, chat_id, *args, **kwargs: sent_alert_groups.append((str(chat_id), args)),
                ), patch.object(
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
        self.assertIn("🧠 PATIENCE", message)
        self.assertIn("📊 RSI", message)
        self.assertIn("👀 LOOK ORDER", message)
        self.assertIn(scanner.poinkle_educational_footer(), message)

    def test_help_command_is_short_and_points_to_learning_and_coins(self):
        sent_messages = []

        with patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_help_command("TOKEN", "999")

        message = sent_messages[0][1]
        self.assertIn("🐷 POINKLE HELP", message)
        self.assertIn("/explain RSI", message)
        self.assertIn("/learn works too", message)
        self.assertIn("/coins", message)
        self.assertNotIn("Current Supported Coins", message)
        self.assertLess(len(message.splitlines()), 25)

    def test_process_telegram_commands_replies_on_first_poll(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 123,
                "message": {
                    "chat": {"id": "999"},
                    "text": "/levels BTC",
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

        self.assertEqual(sent_messages[0][0:3], ("999", "/levels BTC", "BTC/USD"))
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

        def fake_handle(exchange, token, chat_id, text, source_chat=None):
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

        self.assertIn("strength meter", beginner)
        self.assertIn("momentum oscillator", experienced)
        self.assertEqual(scanner.normalize_concept_key("moving average"), "ema")
        self.assertIsNone(scanner.explain_concept("not-a-real-concept", "beginner"))

    def test_explain_concept_normalizes_case_whitespace_and_friendly_terms(self):
        self.assertEqual(scanner.normalize_concept_key("RSI"), "rsi")
        self.assertEqual(scanner.normalize_concept_key("Rsi"), "rsi")
        self.assertEqual(scanner.normalize_concept_key("rsi"), "rsi")
        self.assertEqual(scanner.normalize_concept_key(" ema "), "ema")
        self.assertEqual(scanner.normalize_concept_key("Support"), "support")
        self.assertEqual(scanner.normalize_concept_key("volume spike"), "volume_spike")
        self.assertIn("strength meter", scanner.explain_concept(" RSI ", "beginner"))
        self.assertIsNone(scanner.explain_concept("mystery term", "beginner"))

    def test_new_explanation_concepts_resolve_for_beginner_and_experienced(self):
        expected_phrases = {
            "confirmation": ("finishes the time period beyond it", "candle CLOSE beyond a level"),
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
        self.assertEqual(scanner.normalize_concept_key("candlestick"), "candle")
        self.assertEqual(scanner.normalize_concept_key("body"), "candle")
        self.assertEqual(scanner.normalize_concept_key("range bound"), "range")
        self.assertEqual(scanner.normalize_concept_key("key level"), "key_level")
        self.assertEqual(scanner.normalize_concept_key("zone"), "key_level")
        self.assertEqual(scanner.normalize_concept_key("illiquid"), "liquidity")

    def test_stage_three_explanation_concepts_resolve_for_beginner_and_experienced(self):
        expected_phrases = {
            "market_structure": ("overall shape of how price rises and falls", "sequence of swing highs/lows"),
            "accumulation": ("quietly stepping in over time", "building a position gradually"),
            "retest": ("comes back to test that level again", "price returns to a broken level"),
            "follow_through": ("What happens after a move or a break", "continuation after an initial move/break"),
            "trade_plan": ("decided-in-advance answer", "predefined entry, target(s), and stop"),
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
        self.assertEqual(scanner.normalize_concept_key("trade plan"), "trade_plan")
        self.assertEqual(scanner.normalize_concept_key("stop loss"), "trade_plan")

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
        self.assertIn("strength meter", sent_messages[0][1])

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
                "/learn moving average",
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
        self.assertIn("momentum oscillator", sent_photos[0][2])
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
        unknown = scanner.build_explain_command_message("/learn mystery term")

        self.assertIn("Poinkle can explain these market concepts", menu)
        self.assertIn("Try: /explain rsi", menu)
        self.assertIn("I don't have that one yet", unknown)
        self.assertIn("breakout", unknown)

    def test_process_telegram_commands_routes_learn_command(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 126,
                "message": {
                    "chat": {"id": "999", "type": "private"},
                    "from": {"id": 999},
                    "text": "/learn breakout",
                },
            }
        ]

        def fake_handle(token, chat_id, text, source_chat=None, from_user=None):
            sent_messages.append((chat_id, text, source_chat, from_user))

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "handle_explain_command", side_effect=fake_handle
        ), patch.object(
            scanner, "command_allowed_by_active_mode", return_value=True
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(sent_messages[0][0:2], ("999", "/learn breakout"))
        self.assertEqual(state["__telegram_commands"]["last_update_id"], 126)

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

        def fake_handle(token, chat_id, text, source_chat=None, from_user=None):
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

    def test_process_telegram_commands_routes_coins_command(self):
        state = {}
        sent_messages = []
        updates = [
            {
                "update_id": 127,
                "message": {
                    "chat": {"id": "999", "type": "private"},
                    "from": {"id": 999},
                    "text": "/coins",
                },
            }
        ]

        def fake_handle(token, chat_id, source_chat=None):
            sent_messages.append((chat_id, source_chat))

        with patch.object(scanner, "get_telegram_updates", return_value=updates), patch.object(
            scanner, "handle_coins_command", side_effect=fake_handle
        ), patch.object(
            scanner, "command_allowed_by_active_mode", return_value=True
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(sent_messages[0][0], "999")
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
        self.assertIn("Status: Market-Structure Brief — Full Research Pending", message)
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
        self.assertIn("Full Research Pending", message)
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
            for command in ["/levels BTC", "/snapshot BTC", "/snap BTC"]:
                scanner.handle_levels_command(
                    object(),
                    "TOKEN",
                    "999",
                    command,
                    source_chat={"id": "999", "type": "private"},
                    from_user={"id": 999},
                )

        self.assertEqual(len(sent_messages), 3)
        for _, text in sent_messages:
            self.assertIn(scanner.poinkle_educational_footer(), text)

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

        self.assertEqual(sent_messages[-1], "Symbol currently unavailable.")

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

    def test_reference_card_renders_and_uses_supported_watchlist_symbols(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD", "ETH/USD", "XMR/USD"]
        scanner.UNSUPPORTED_SYMBOLS_THIS_SESSION.add("XMR/USD")

        try:
            symbols = scanner.reference_card_symbols()
            with tempfile.TemporaryDirectory() as tmpdir:
                path = prb_card_renderer.render_reference_card(symbols, output_dir=tmpdir)
                card_exists = Path(path).exists()
                png_header = Path(path).read_bytes()[:8]
        finally:
            scanner.WATCHLIST = original_watchlist
            scanner.UNSUPPORTED_SYMBOLS_THIS_SESSION.discard("XMR/USD")

        self.assertEqual(symbols, ["BTC/USD", "ETH/USD"])
        self.assertTrue(card_exists)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_coins_command_lists_enabled_supported_watchlist_symbols(self):
        original_watchlist = scanner.WATCHLIST[:]
        scanner.WATCHLIST = ["BTC/USD", "ETH/USD", "XMR/USD"]
        scanner.UNSUPPORTED_SYMBOLS_THIS_SESSION.add("XMR/USD")
        sent_messages = []

        try:
            with patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_coins_command(
                    "TOKEN",
                    "-100",
                    source_chat={"id": "-100", "type": "group"},
                )
        finally:
            scanner.WATCHLIST = original_watchlist
            scanner.UNSUPPORTED_SYMBOLS_THIS_SESSION.discard("XMR/USD")

        self.assertEqual(sent_messages[0][0], "-100")
        self.assertIn("🪙 Coins Poinkle tracks: 2 coins", sent_messages[0][1])
        self.assertIn("BTC, ETH", sent_messages[0][1])
        self.assertNotIn("XMR", sent_messages[0][1])

    def test_welcome_card_renderer_produces_image_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = prb_card_renderer.render_welcome_card(
                ["BTC/USD", "ETH/USD", "SOL/USD"],
                output_dir=tmpdir,
            )

            self.assertTrue(Path(path).exists())
            self.assertEqual(Path(path).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_reference_command_sends_rendered_card(self):
        sent_photos = []

        with patch.object(scanner, "reference_card_symbols", return_value=["BTC/USD", "ETH/USD"]) as symbols, patch.object(
            scanner, "render_reference_card", return_value="/tmp/reference.png"
        ) as render_card, patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path: sent_photos.append((str(chat_id), path)) or True,
        ), patch.object(scanner, "send_telegram_message", side_effect=AssertionError("text fallback should not be sent")):
            scanner.handle_reference_command(
                "TOKEN",
                "999",
                source_chat={"id": "999", "type": "private"},
            )

        symbols.assert_called_once()
        render_card.assert_called_once()
        self.assertEqual(render_card.call_args.kwargs["logo_path"], scanner.POINKLE_RESEARCH_EMBLEM_PATH)
        self.assertEqual(sent_photos, [("999", "/tmp/reference.png")])

    def test_start_command_sends_welcome_message_and_captures_new_profile(self):
        sent_messages = []

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            scanner, "USER_PROFILES_FILE", Path(tmpdir) / "user_profiles.json"
        ), patch.object(
            scanner, "WELCOME_BANNER_PATH", Path(tmpdir) / "missing-welcome-banner.jpg"
        ), patch.object(scanner, "iso_utc_now", return_value="2026-07-08T12:00:00+00:00"), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_start_command(
                "TOKEN",
                "999",
                from_user={"id": 777, "username": "poinkle_user", "first_name": "Pat", "last_name": "Learner"},
            )
            profiles = scanner.load_user_profiles()

        self.assertEqual(sent_messages[0][0], "777")
        self.assertEqual(sent_messages[0][1], scanner.build_welcome_message())
        self.assertEqual(sent_messages[1][0], "777")
        self.assertEqual(sent_messages[1][1], scanner.skill_onboarding_message())
        self.assertIn("🐷 <b>Welcome to Poinkle.</b>", sent_messages[0][1])
        self.assertEqual(profiles["777"]["telegram_user_id"], "777")
        self.assertEqual(profiles["777"]["username"], "poinkle_user")
        self.assertEqual(profiles["777"]["first_name"], "Pat")
        self.assertEqual(profiles["777"]["last_name"], "Learner")
        self.assertEqual(profiles["777"]["first_seen"], "2026-07-08T12:00:00+00:00")
        self.assertEqual(profiles["777"]["last_start"], "2026-07-08T12:00:00+00:00")
        self.assertTrue(profiles["777"]["onboarded"])
        self.assertTrue(profiles["777"]["skill_onboarding_prompted"])

    def test_start_command_sends_welcome_banner_with_caption_before_skill_prompt(self):
        sent_photos = []
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
                side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_start_command("TOKEN", "999", from_user={"id": 777})

        self.assertEqual(sent_photos, [("777", str(banner_path), scanner.build_welcome_message())])
        self.assertEqual(sent_messages, [("777", scanner.skill_onboarding_message())])

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
                scanner, "WELCOME_BANNER_PATH", Path(tmpdir) / "missing-welcome-banner.jpg"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_start_command("TOKEN", "999", from_user={"id": 777, "first_name": "Pat"})
                profiles = scanner.load_user_profiles()

        self.assertEqual(sent_messages, [("777", scanner.build_welcome_message())])
        self.assertEqual(profiles["777"]["first_seen"], "2026-07-01T12:00:00+00:00")
        self.assertEqual(profiles["777"]["last_start"], "2026-07-08T12:00:00+00:00")
        self.assertEqual(profiles["777"]["skill_level"], "beginner")
        self.assertEqual(profiles["777"]["first_name"], "Pat")

    def test_start_command_still_welcomes_when_profile_write_fails(self):
        sent_messages = []

        with patch.object(scanner, "WELCOME_BANNER_PATH", Path("/private/tmp/missing-welcome-banner.jpg")), patch.object(
            scanner, "save_user_profiles", side_effect=OSError("disk full")
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
        ):
            scanner.handle_start_command("TOKEN", "999", from_user={"id": 777})

        self.assertEqual(sent_messages[0][0], "777")
        self.assertEqual(sent_messages[0][1], scanner.build_welcome_message())

    def test_start_command_does_not_repeat_skill_prompt_when_already_prompted(self):
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
                scanner, "WELCOME_BANNER_PATH", Path(tmpdir) / "missing-welcome-banner.jpg"
            ), patch.object(
                scanner,
                "send_telegram_message",
                side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
            ):
                scanner.handle_start_command("TOKEN", "999", from_user={"id": 777})

        self.assertEqual(sent_messages, [("777", scanner.build_welcome_message())])

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

        with patch.object(scanner, "render_prb_cards", return_value=["/tmp/prb.png"]) as prb_render, patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path: sent_photos.append((str(chat_id), path)) or True,
        ):
            scanner.send_research_cards("TOKEN", "999", "BTC PRB")

        with patch.object(scanner, "render_reference_card", return_value="/tmp/reference.png") as reference_render, patch.object(
            scanner,
            "send_telegram_photo",
            return_value=True,
        ):
            scanner.handle_reference_command("TOKEN", "999")

        self.assertEqual(alert_render.call_args.kwargs["logo_path"], scanner.POINKLE_RESEARCH_EMBLEM_PATH)
        self.assertEqual(prb_render.call_args.kwargs["logo_path"], scanner.POINKLE_RESEARCH_EMBLEM_PATH)
        self.assertEqual(reference_render.call_args.kwargs["logo_path"], scanner.POINKLE_RESEARCH_EMBLEM_PATH)

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
        self.assertEqual(captured["title"], "BTC / USD CONFLUENCE ALERT")
        self.assertIn(("SIGNALS", "Bullish Volume Spike (2.50x)\n+ EMA 21 crossed above EMA 55"), captured["card_specs"])
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
            side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
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
        self.assertEqual(sent_photos, [("999", "/tmp/alert-card.png", "🟢 <b>BTC/USD Bullish Volume Spike</b>")])

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
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
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
            side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
        ), patch.object(
            scanner,
            "send_telegram_message",
            side_effect=lambda token, chat_id, text: sent_messages.append((str(chat_id), text)),
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
            "<b>BTC/USD Confluence Alert</b> — "
            "Bullish Volume Spike (2.50x) + EMA 21 crossed above EMA 55\n"
            "Learn more: https://bitcoin.org",
        )
        self.assertEqual(sent_messages, [])

    def test_severity_label_for_alerts_counts_distinct_signal_types(self):
        self.assertEqual(
            scanner.severity_label_for_alerts(
                [
                    {"type": "volume_spike"},
                    {"type": "ema_cross_above"},
                ]
            ),
            "",
        )
        self.assertEqual(
            scanner.severity_label_for_alerts(
                [
                    {"type": "volume_spike"},
                    {"type": "volume_spike"},
                    {"type": "ema_cross_above"},
                ]
            ),
            "",
        )
        self.assertEqual(
            scanner.severity_label_for_alerts(
                [
                    {"type": "volume_spike"},
                    {"type": "ema_cross_above"},
                    {"type": "rsi_cross_above_70"},
                ]
            ),
            "🟡 3 signals",
        )
        self.assertEqual(
            scanner.severity_label_for_alerts(
                [
                    {"type": "volume_spike"},
                    {"type": "ema_cross_above"},
                    {"type": "rsi_cross_above_70"},
                    {"type": "live:breakout:100:early_warning"},
                ]
            ),
            "🔴 4 signals",
        )
        self.assertEqual(
            scanner.severity_label_for_alerts(
                [
                    {"type": "volume_spike"},
                    {"type": "ema_cross_above"},
                    {"type": "rsi_cross_above_70"},
                    {"type": "live:breakout:100:early_warning"},
                    {"type": "live:breakdown:90:early_warning"},
                ]
            ),
            "🔴 5 signals",
        )

    def test_confluence_caption_adds_severity_for_three_or_more_signals(self):
        sent_photos = []
        alerts = [
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
                "label": "RSI crossed above 70",
                "emoji": "🔥",
            },
        ]

        with patch.object(scanner, "render_alert_snapshot_chart", return_value="/tmp/confluence.png"), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path, caption="": sent_photos.append((str(chat_id), path, caption)) or True,
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

        self.assertTrue(sent_photos[0][2].startswith("🟡 3 signals\n<b>BTC/USD Confluence Alert</b> — "))

    def test_research_command_sends_image_cards_when_renderer_succeeds(self):
        sent_groups = []

        with patch.object(scanner, "build_research_command_message", return_value="AAVE PRB"), patch.object(
            scanner, "render_prb_cards", return_value=["/tmp/prb-card-1.png", "/tmp/prb-card-2.png"]
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

        def fake_render_prb_cards(prb_text, logo_path=None, output_dir=None, chart_path=None):
            captured["prb_text"] = prb_text
            captured["logo_path"] = logo_path
            captured["chart_path"] = chart_path
            return ["/tmp/prb-card-with-chart.png"]

        with patch.object(scanner, "generate_levels_chart", return_value="/tmp/prb-snapshot.png") as generate_chart, patch.object(
            scanner, "render_prb_cards", side_effect=fake_render_prb_cards
        ), patch.object(
            scanner,
            "send_telegram_media_group",
            side_effect=lambda token, chat_id, paths: sent_groups.append((str(chat_id), list(paths))) or True,
        ), patch.object(
            scanner, "send_telegram_photo", side_effect=AssertionError("individual photos should not be sent")
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
        self.assertEqual(captured["logo_path"], scanner.POINKLE_RESEARCH_EMBLEM_PATH)
        self.assertEqual(captured["chart_path"], "/tmp/prb-snapshot.png")
        self.assertEqual(sent_groups, [("999", ["/tmp/prb-card-with-chart.png"])])

    def test_research_cards_fall_back_to_individual_photos_when_media_group_fails(self):
        sent_photos = []

        with patch.object(scanner, "render_prb_cards", return_value=["/tmp/prb-card-1.png", "/tmp/prb-card-2.png"]), patch.object(
            scanner, "send_telegram_media_group", return_value=False
        ), patch.object(
            scanner,
            "send_telegram_photo",
            side_effect=lambda token, chat_id, path: sent_photos.append((str(chat_id), path)) or True,
        ):
            self.assertTrue(scanner.send_research_cards("TOKEN", "999", "AAVE PRB"))

        self.assertEqual(
            sent_photos,
            [
                ("999", "/tmp/prb-card-1.png"),
                ("999", "/tmp/prb-card-2.png"),
            ],
        )

    def test_research_command_falls_back_to_text_when_renderer_fails(self):
        sent_messages = []

        with patch.object(scanner, "build_research_command_message", return_value="AAVE PRB"), patch.object(
            scanner, "render_prb_cards", side_effect=RuntimeError("render failed")
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
                    "/levels BTC",
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
                    "/levels BTC",
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
                    "I can't DM you yet. Please start me first: @Poinkle_Bot, then try /levels SYMBOL again.",
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
                "/levels BTC",
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
        self.assertEqual(scanner.normalize_symbol("XAU"), "XAU/USD")
        self.assertEqual(scanner.normalize_symbol("XAO"), "XAU/USD")
        self.assertEqual(scanner.normalize_symbol("GOLD"), "XAU/USD")
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

    def test_expanded_watchlist_contains_144_enabled_unique_symbols_after_cleanup(self):
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

        self.assertEqual(len(enabled_symbols), 144)
        self.assertEqual(len(set(enabled_symbols)), 144)
        self.assertTrue(all(symbol.endswith("/USD") for symbol in enabled_symbols))
        self.assertIn("BTC/USD", enabled_symbols)
        self.assertIn("BRETT/USD", enabled_symbols)
        self.assertIn("XAU/USD", enabled_symbols)
        self.assertIn("POL/USD", enabled_symbols)
        self.assertNotIn("MATIC/USD", enabled_symbols)
        self.assertNotIn("USDC/USD", enabled_symbols)
        self.assertNotIn("WBTC/USD", enabled_symbols)
        self.assertIn("USDC/USD", disabled_symbols)
        self.assertIn("WBTC/USD", disabled_symbols)
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
        ):
            scanner.DIAGNOSTICS_FILE = Path(tmpdir)

            scanner.append_diagnostic_record({"record_type": "delivery"})

        self.assertEqual(len(warnings), 1)
        self.assertIn("Could not write diagnostic record", warnings[0])

    def test_run_once_logs_scan_failure_diagnostic_record(self):
        with patch.object(scanner, "WATCHLIST", ["FAIL/USD"]), patch.object(
            scanner,
            "scan_symbol",
            side_effect=RuntimeError("timeout fetching candles"),
        ), patch.object(scanner, "log_info"), patch.object(scanner, "throttled_log_warn"):
            scanner.run_once(None, "token", "chat", {})

        lines = scanner.DIAGNOSTICS_FILE.read_text().splitlines()
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
            for command in ["/levels ZEC", "/levels XMR", "/levels LTC", "/levels XAU", "/levels XAO"]:
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
            ["ZEC/USD", "XMR/USD", "LTC/USD", "XAU/USD", "XAU/USD"],
        )
        self.assertEqual(sent_messages[-1], ("999", "XAU/USD report"))

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
                or (
                    candle(0, 99, 101, 98, 100, 100),
                    candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 100),
                    [],
                    100,
                    99,
                    50,
                    1,
                    100,
                    90,
                    110,
                ),
            ), patch.object(scanner, "get_current_market_price", return_value=101), patch.object(
                scanner, "print_compact_scan_summary"
            ), patch.object(scanner, "save_state"):
                scanner.run_once(object(), "TOKEN", "999", {})
        finally:
            scanner.WATCHLIST = original_watchlist

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
        with patch.object(scanner, "load_bot_config", return_value={"live_alerts_enabled": True}), patch.object(
            scanner, "throttled_log_warn"
        ) as warn:
            scanner.monitor_active_trades(FailingTradeExchange(), "TOKEN", "999", state)

        self.assertEqual(warn.call_args.args[1], "active-trade")

    def test_levels_command_returns_unavailable_message_for_bad_or_failed_symbol(self):
        sent_messages = []

        with patch.object(scanner, "send_telegram_message", side_effect=lambda token, chat_id, text: sent_messages.append(text)):
            scanner.handle_levels_command(object(), "TOKEN", "999", "/levels NOTREAL")

        self.assertEqual(sent_messages[-1], "Symbol currently unavailable.")

        failing_exchange = FakeExchange({}, ticker_price=0, failing_timeframes={"15m"})
        with patch.object(scanner, "send_telegram_message", side_effect=lambda token, chat_id, text: sent_messages.append(text)):
            scanner.handle_levels_command(failing_exchange, "TOKEN", "999", "/levels EDEL")

        self.assertEqual(sent_messages[-1], "Symbol currently unavailable.")

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
        self.assertIn("🧠 PATIENCE\nB — Good accumulation", message)
        chart_data = scanner.LAST_LEVELS_CHART_DATA["BTC/USD"]
        self.assertIn(60000.0, chart_data["supports"])
        self.assertIn(65000.0, chart_data["resistances"])
        self.assertNotIn(62100, chart_data["supports"])
        self.assertNotIn(61800, chart_data["supports"])
        self.assertNotIn("62,100", message)
        self.assertNotIn("61,800", message)


if __name__ == "__main__":
    unittest.main()
