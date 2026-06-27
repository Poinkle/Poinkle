import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCANNER_PATH = PROJECT_DIR / "crypto_alert_scanner.py"

spec = importlib.util.spec_from_file_location("crypto_alert_scanner", SCANNER_PATH)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


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
        scanner.TEST_MODE = False
        scanner.KEY_LEVELS = {
            "BTC/USD": {"support": [95], "resistance": [100]},
        }

    def tearDown(self):
        scanner.TEST_MODE = self.original_test_mode
        scanner.KEY_LEVELS = self.original_key_levels

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

    def test_confirmation_sends_trade_plan_only_when_break_strength_is_strong(self):
        current_timestamp = scanner.TIMEFRAME_MS * 2
        symbol_state = {
            "pending_setups": {
                "live:breakout:100": {
                    "direction": "breakout",
                    "level": 100,
                    "first_candle": scanner.TIMEFRAME_MS,
                    "first_candle_open": 99,
                    "first_candle_high": 103,
                    "first_candle_low": 98,
                    "first_candle_close": 102,
                    "first_candle_volume": 180,
                    "expected_confirmation_candle": current_timestamp,
                }
            }
        }
        confirmation_candle = candle(current_timestamp, 101, 105, 100.8, 104, 300)

        alerts = scanner.build_level_alerts(
            "BTC/USD",
            candle(scanner.TIMEFRAME_MS, 99, 103, 98, 102, 180),
            confirmation_candle,
            symbol_state,
            atr_14=1.0,
            current_market_price=104,
            range_low=90,
            range_high=110,
            ema_21=102,
            ema_55=99,
            current_rsi=60,
            volume_avg=100,
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["label"], "Breakout Confirmation")
        self.assertGreaterEqual(alerts[0]["trade_plan"]["break_strength_score"], 70)
        self.assertIn("setup_quality", alerts[0]["trade_plan"])
        self.assertNotEqual(alerts[0]["trade_plan"]["setup_quality"], "D")
        self.assertIn("entry", alerts[0]["trade_plan"])
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
        )

        self.assertEqual(len(alerts), 1)
        self.assertIn(alerts[0]["label"], {"Weak Break / Watch Only", "Failed Follow-Through"})
        self.assertNotEqual(alerts[0]["label"], "Breakout Confirmation")
        self.assertLess(alerts[0]["trade_plan"]["break_strength_score"], 70)

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
        self.assertIn("High volume detected. Watch for breakout confirmation.", message)
        self.assertNotIn("Strong buyer participation detected.", message)

    def test_volume_alert_requires_confirmation_context(self):
        volume_alert = {
            "type": "volume_spike",
            "label": "Bullish Volume Spike",
            "emoji": "🟢",
            "direction": "bullish",
            "volume_multiple": 2.5,
        }

        self.assertFalse(scanner.should_send_telegram_alert(volume_alert, [volume_alert]))

        ema_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }
        self.assertTrue(
            scanner.should_send_telegram_alert(volume_alert, [volume_alert, ema_alert])
        )

        break_alert = {
            "type": "live:breakout:100:early_warning",
            "label": "Breakout Attempt",
            "emoji": "⚠️",
        }
        self.assertTrue(
            scanner.should_send_telegram_alert(volume_alert, [volume_alert, break_alert])
        )

        self.assertTrue(
            scanner.should_send_telegram_alert(
                volume_alert, [volume_alert], active_trade_status="Retest Holding"
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
                "4h": make_ohlcv_series(four_hour_closes, step=14_400_000),
                "1d": make_ohlcv_series(daily_closes, step=86_400_000),
                "1w": make_ohlcv_series(weekly_closes, step=604_800_000),
            },
            ticker_price=100,
        )

        message = scanner.build_levels_command_message(fake_exchange, "BTC/USD")

        self.assertIn("BTC/USD Market Levels", message)
        self.assertIn("Current Price", message)
        self.assertIn("Current Location", message)
        self.assertIn("Trend", message)
        self.assertIn("Reason", message)
        self.assertIn("because:", message)
        self.assertIn("•", message)
        self.assertIn("Overall Confidence", message)
        self.assertRegex(message, r"Overall Confidence:</b> \d+%")
        self.assertIn("EMA Information", message)
        self.assertIn("EMA Timeframe", message)
        self.assertIn("EMA21:", message)
        self.assertIn("EMA55:", message)
        self.assertNotIn("EMA Structure:", message)
        self.assertNotIn(" vs ", message)
        self.assertIn("RSI Information", message)
        self.assertIn("RSI Status", message)
        self.assertIn("Accumulation Zones", message)
        self.assertIn("Distribution Zones", message)
        self.assertNotIn("Buy Zones", message)
        self.assertNotIn("Resistance Zones", message)
        self.assertIn("Market Structure", message)
        self.assertRegex(
            message,
            r"Range Bound|Accumulating|Trending Higher|Trending Lower|Approaching Support|Approaching Resistance",
        )
        self.assertIn("Distance To Nearest Support", message)
        self.assertRegex(
            message,
            r"Distance To Nearest Support:</b> .+ \((At Support|Near Support|Approaching Support|Far From Support|Support Distance Unknown)\)",
        )
        self.assertIn("Distance To Nearest Resistance", message)
        self.assertIn("Accumulation Rating", message)
        self.assertRegex(message, r"Accumulation Rating:</b> [ABCDF]")
        self.assertRegex(
            message,
            r"Excellent accumulation|Good accumulation|Neutral|Weak accumulation|Avoid",
        )
        self.assertIn("Score Breakdown", message)
        self.assertNotIn("Reasons:", message)
        self.assertRegex(message, r"✓|✗")
        self.assertIn("Best Use Case", message)
        self.assertRegex(
            message,
            r"✓ DCA|✓ Long-Term Hold|✗ Breakout Trade|✓ Trim Position|✓ Wait For Pullback|✓ Watch Only",
        )
        self.assertIn("Summary", message)
        self.assertLess(message.index("🧠 <b>Summary</b>"), message.index("📊 <b>Market Structure</b>"))
        self.assertLess(message.index("📊 <b>Market Structure</b>"), message.index("🟢 <b>Accumulation Zones</b>"))
        self.assertIn(
            "Educational market structure only. Not financial advice. Use your own risk management.",
            message,
        )
        self.assertTrue(message.rstrip().endswith("Levels Engine v1.0"))
        self.assertNotIn("Suggested plan", message)
        self.assertNotIn("Stop loss", message)
        self.assertIn("Trend", message)
        summary_text = message.split("🧠 <b>Summary</b>\n", 1)[1].split(
            "\n\n📊 <b>Market Structure</b>", 1
        )[0]
        self.assertLessEqual(len(summary_text.split(". ")), 3)
        self.assertNotIn("Risk/Reward To First Resistance", message)
        self.assertNotIn("99.9", message)

    def test_main_chat_safe_mode_suppresses_automatic_scanner_alerts(self):
        original_watchlist = scanner.WATCHLIST[:]
        original_safe_mode = scanner.MAIN_CHAT_SAFE_MODE
        scanner.WATCHLIST = ["BTC/USD"]
        scanner.MAIN_CHAT_SAFE_MODE = True
        sent_messages = []
        fake_alert = {
            "type": "ema_cross_above",
            "label": "EMA 21 crossed above EMA 55",
            "emoji": "🟢",
        }
        scan_result = (
            candle(0, 99, 101, 98, 100, 100),
            candle(scanner.TIMEFRAME_MS, 100, 102, 99, 101, 200),
            [fake_alert],
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
                "send_telegram_message",
                side_effect=lambda token, chat_id, text: sent_messages.append(text),
            ), patch.object(scanner, "save_state"):
                scanner.run_once(object(), "TOKEN", "999", {})
        finally:
            scanner.WATCHLIST = original_watchlist
            scanner.MAIN_CHAT_SAFE_MODE = original_safe_mode

        self.assertEqual(sent_messages, [])

    def test_levels_command_falls_back_when_higher_timeframes_fail(self):
        fifteen_minute_closes = [95 + (index % 20) * 0.5 for index in range(119)] + [100]
        fake_exchange = FakeExchange(
            {
                "15m": make_ohlcv_series(fifteen_minute_closes),
            },
            ticker_price=100,
            failing_timeframes={"4h", "1d", "1w"},
        )

        message = scanner.build_levels_command_message(fake_exchange, "BTC/USD")

        self.assertIn("BTC/USD Market Levels", message)
        self.assertIn("Accumulation Zones", message)
        self.assertIn("Distribution Zones", message)

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
        ), patch.object(scanner, "save_state"):
            scanner.process_telegram_commands(object(), "TOKEN", "999", state)

        self.assertEqual(sent_messages[0][0:3], ("999", "/levels BTC", "BTC/USD"))
        self.assertEqual(state["__telegram_commands"]["last_update_id"], 123)

    def test_levels_group_command_sends_full_report_by_dm_only(self):
        sent_messages = []
        original_username = scanner.BOT_USERNAME
        scanner.BOT_USERNAME = "TICBot"

        try:
            with patch.object(scanner, "build_levels_command_message", return_value="FULL LEVELS REPORT"), patch.object(
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
                "Sent BTC/USD levels to your DM. If you did not receive it, start the bot first: @TICBot",
            ),
        )

    def test_levels_group_command_handles_dm_failure(self):
        sent_messages = []
        original_username = scanner.BOT_USERNAME
        scanner.BOT_USERNAME = "TICBot"

        def fake_send(token, chat_id, text):
            if str(chat_id) == "777":
                raise RuntimeError("Forbidden")
            sent_messages.append((str(chat_id), text))

        try:
            with patch.object(scanner, "build_levels_command_message", return_value="FULL LEVELS REPORT"), patch.object(
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
                    "I can't DM you yet. Please start me first: @TICBot, then try /levels SYMBOL again.",
                )
            ],
        )

    def test_levels_private_command_replies_in_dm(self):
        sent_messages = []

        with patch.object(scanner, "build_levels_command_message", return_value="FULL LEVELS REPORT"), patch.object(
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
        self.assertEqual(scanner.normalize_symbol("NOBODY"), "NOBODY/USD")
        self.assertEqual(scanner.normalize_symbol("pengu"), "PENGU/USD")
        self.assertEqual(scanner.normalize_symbol("bnb"), "BNB/USD")
        self.assertIsNone(scanner.normalize_symbol("dogfi"))
        self.assertIsNone(scanner.normalize_symbol("NOTREAL"))

    def test_watchlist_is_single_master_symbol_source(self):
        expected_watchlist = [
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

        self.assertEqual(scanner.WATCHLIST, expected_watchlist)
        self.assertFalse(hasattr(scanner, "LEVELS_SYMBOLS"))
        self.assertEqual(set(self.original_key_levels), set(scanner.WATCHLIST))

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
                "4h": make_ohlcv_series(four_hour_closes, step=14_400_000),
                "1d": make_ohlcv_series(daily_closes, step=86_400_000),
                "1w": make_ohlcv_series(weekly_closes, step=604_800_000),
            },
            ticker_price=current_price,
        )

        message = scanner.build_levels_command_message(fake_exchange, "BTC/USD")

        self.assertIn("BTC/USD Market Levels", message)
        self.assertIn("Accumulation Zones", message)
        self.assertIn("Zone 1", message)
        self.assertIn("Distribution Zones", message)
        self.assertIn("Summary", message)
        self.assertNotIn("62,100", message)
        self.assertNotIn("61,800", message)


if __name__ == "__main__":
    unittest.main()
