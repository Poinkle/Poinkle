import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import chart_generator
    import numpy as np
    from matplotlib.axes import Axes
except ModuleNotFoundError:
    chart_generator = None
    np = None
    Axes = None


def candle(high, low, close=None):
    return {
        "timestamp": 1_800_000_000_000,
        "open": close or (high + low) / 2,
        "high": high,
        "low": low,
        "close": close or (high + low) / 2,
        "volume": 100,
    }


class ChartGeneratorTests(unittest.TestCase):
    @unittest.skipIf(chart_generator is None, "matplotlib is not installed")
    def test_axis_targets_visible_candle_height_without_levels(self):
        candles = [candle(110, 100), candle(112, 101)]

        y_min, y_max = chart_generator.axis_bounds(106, candles, [], [])

        candle_span = 12
        axis_span = y_max - y_min
        self.assertAlmostEqual(candle_span / axis_span, 0.72)

    @unittest.skipIf(chart_generator is None, "matplotlib is not installed")
    def test_chart_levels_only_include_nearby_visible_levels(self):
        candles = [candle(110, 100), candle(112, 101)]
        levels = [99.8, 96, 113.2, 120]

        nearby = chart_generator.chart_near_levels(levels, 106, candles, limit=4)

        self.assertEqual(nearby, [99.8, 113.2])

    @unittest.skipIf(chart_generator is None, "matplotlib is not installed")
    def test_current_price_does_not_expand_axis_beyond_visible_candles(self):
        candles = [candle(110, 100), candle(112, 101)]

        y_min, y_max = chart_generator.axis_bounds(140, candles, [], [])

        candle_span = 12
        axis_span = y_max - y_min
        self.assertAlmostEqual(candle_span / axis_span, 0.72)

    @unittest.skipIf(chart_generator is None, "matplotlib is not installed")
    def test_snapshot_chart_renders_volume_panel_with_real_candle_volumes(self):
        candles = []
        for index in range(30):
            item = candle(110 + index, 100 + index, close=105 + index)
            item["open"] = 104 + index
            item["volume"] = 100 + index * 10
            candles.append(item)
        candles[-1]["volume"] = 900
        recorded_bar_heights = []
        original_bar = Axes.bar

        def spy_bar(self, x, height, *args, **kwargs):
            recorded_bar_heights.append(height)
            return original_bar(self, x, height, *args, **kwargs)

        with patch.object(Axes, "bar", new=spy_bar):
            path = chart_generator.generate_levels_chart(
                "BTC/USD",
                candles,
                candles[-1]["close"],
                supports=[120],
                resistances=[140],
                card_specs=[
                    ("ALERT\nTYPE", "Bullish Volume Spike"),
                    ("PRICE", "134"),
                    ("VOLUME", "9.00x average"),
                    ("RSI", "58.00"),
                    ("EMA\nCONTEXT", "21 / 55"),
                ],
                footer_items=[
                    "1. High volume detected",
                    "2. Watch confirmation",
                    "3. Compare follow-through",
                ],
                title="BTC / USD BULLISH VOLUME SPIKE",
            )

        self.assertTrue(Path(path).exists())
        self.assertIn(900, recorded_bar_heights)
        self.assertIn(100, recorded_bar_heights)

    @unittest.skipIf(chart_generator is None, "matplotlib is not installed")
    def test_confluence_alert_chart_renders_small_decimal_candles_and_wraps_footer(self):
        import chart_generator_reference

        candles = []
        base = 0.00000420
        for index in range(36):
            open_price = base + index * 0.000000006
            close = open_price + (0.000000018 if index % 2 == 0 else -0.000000014)
            high = max(open_price, close) + 0.000000055
            low = min(open_price, close) - 0.000000045
            candles.append(
                {
                    "timestamp": 1_800_000_000_000 + index * 900_000,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 100 + index * 20,
                }
            )
        candles[-1]["volume"] = 3900
        y_limits = []
        wick_calls = []
        footer_text = []
        original_set_ylim = Axes.set_ylim
        original_vlines = Axes.vlines
        original_text = Axes.text

        def spy_set_ylim(self, bottom=None, top=None, *args, **kwargs):
            if bottom is not None and top is not None:
                y_limits.append((bottom, top))
            return original_set_ylim(self, bottom, top, *args, **kwargs)

        def spy_vlines(self, x, ymin, ymax, *args, **kwargs):
            wick_calls.append((x, ymin, ymax))
            return original_vlines(self, x, ymin, ymax, *args, **kwargs)

        def spy_text(self, x, y, s, *args, **kwargs):
            footer_text.append((x, y, str(s)))
            return original_text(self, x, y, s, *args, **kwargs)

        with patch.object(Axes, "set_ylim", new=spy_set_ylim), patch.object(
            Axes, "vlines", new=spy_vlines
        ), patch.object(Axes, "text", new=spy_text):
            path = chart_generator_reference.generate_reference_levels_chart(
                "BONK/USD",
                candles,
                candles[-1]["close"],
                supports=[0.00000410],
                resistances=[0.00000455],
                card_specs=[
                    ("SIGNALS", "Bearish Volume Spike (37.93x)\n+ RSI crossed below 30"),
                    ("PRICE", "0.00000443"),
                    ("VOLUME", "37.93x average\nCurrent candle"),
                    ("RSI", "28.40\nOversold"),
                    ("EMA\nCONTEXT", "21 0.00000450\n55 0.00000462"),
                ],
                footer_items=[
                    "1. Bearish Volume Spike (37.93x) + RSI crossed below 30",
                    "2. Price 0.00000443 -> watch confirmation",
                    "3. Volume 37.93x average -> compare follow-through",
                ],
                title="BONK / USD CONFLUENCE ALERT",
                output_prefix="bonk_confluence_test_",
                signal_scope="15m signal - snapshot in time, not a trend call",
            )

        self.assertTrue(Path(path).exists())
        micro_limits = [
            (bottom, top)
            for bottom, top in y_limits
            if 0 <= bottom < top < 0.00001
        ]
        self.assertTrue(micro_limits)
        self.assertGreaterEqual(len(wick_calls), len(candles))
        drawn_footer_lines = [text for _x, _y, text in footer_text]
        self.assertNotIn("1. Bearish Volume Spike (37.93x) + RSI crossed below 30", drawn_footer_lines)
        self.assertTrue(any("Bearish Volume Spike" in text for text in drawn_footer_lines))
        self.assertTrue(any("RSI crossed below" in text for text in drawn_footer_lines))

    @unittest.skipIf(chart_generator is None, "matplotlib is not installed")
    def test_confluence_signals_card_wraps_long_multi_signal_text(self):
        import chart_generator_reference

        candles = []
        for index in range(36):
            item = candle(110 + index, 100 + index, close=105 + index)
            item["open"] = 104 + index
            item["volume"] = 100 + index * 10
            candles.append(item)

        long_signal = (
            "EMA 21 crossed above EMA 55 + Bullish Volume Spike (2.20x) "
            "+ RSI crossed above 70"
        )
        original_text = Axes.text
        drawn_card_text = []

        def spy_text(self, x, y, s, *args, **kwargs):
            if kwargs.get("color") == "#d4dfe5" and kwargs.get("zorder") == 4:
                drawn_card_text.append(
                    {
                        "x": x,
                        "y": y,
                        "text": str(s),
                        "fontsize": kwargs.get("fontsize"),
                    }
                )
            return original_text(self, x, y, s, *args, **kwargs)

        with patch.object(Axes, "text", new=spy_text):
            path = chart_generator_reference.generate_reference_levels_chart(
                "ENA/USD",
                candles,
                candles[-1]["close"],
                supports=[120],
                resistances=[140],
                card_specs=[
                    ("SIGNALS", long_signal),
                    ("PRICE", "134"),
                    ("VOLUME", "2.20x average\nCurrent candle"),
                    ("RSI", "72.40\nOverbought"),
                    ("EMA\nCONTEXT", "21 132\n55 128"),
                ],
                title="ENA / USD CONFLUENCE ALERT",
                output_prefix="ena_confluence_signals_test_",
            )

        self.assertTrue(Path(path).exists())
        signal_lines = [
            item for item in drawn_card_text if any(token in item["text"] for token in ("EMA 21", "Bullish", "RSI"))
        ]
        self.assertGreaterEqual(len(signal_lines), 3)
        self.assertNotIn(long_signal, [item["text"] for item in signal_lines])
        self.assertTrue(all(len(item["text"]) <= 24 for item in signal_lines))
        self.assertTrue(all(item["x"] < 0.50 for item in signal_lines))
        self.assertTrue(all(item["fontsize"] <= 8.7 for item in signal_lines))

    @unittest.skipIf(chart_generator is None, "matplotlib is not installed")
    def test_ghost_watermark_renders_at_low_opacity_behind_candles(self):
        import chart_generator_reference

        candles = []
        for index in range(36):
            item = candle(110 + index, 100 + index, close=105 + index)
            item["open"] = 104 + index
            candles.append(item)

        fake_logo = np.zeros((12, 12, 4))
        fake_logo[:, :, 0] = 0.05
        fake_logo[:, :, 1] = 0.12
        fake_logo[:, :, 2] = 0.14
        fake_logo[:, :, 3] = 0.70
        imshow_calls = []
        wick_zorders = []
        original_imshow = Axes.imshow
        original_vlines = Axes.vlines

        def spy_imshow(self, image, *args, **kwargs):
            imshow_calls.append(kwargs)
            return original_imshow(self, image, *args, **kwargs)

        def spy_vlines(self, x, ymin, ymax, *args, **kwargs):
            wick_zorders.append(kwargs.get("zorder"))
            return original_vlines(self, x, ymin, ymax, *args, **kwargs)

        with patch.object(chart_generator_reference.os.path, "exists", return_value=True), patch.object(
            chart_generator_reference.plt, "imread", return_value=fake_logo
        ), patch.object(Axes, "imshow", new=spy_imshow), patch.object(Axes, "vlines", new=spy_vlines):
            path = chart_generator_reference.generate_reference_levels_chart(
                "BTC/USD",
                candles,
                candles[-1]["close"],
                supports=[120],
                resistances=[140],
                output_prefix="ghost_watermark_test_",
            )

        self.assertTrue(Path(path).exists())
        watermark_calls = [
            call for call in imshow_calls if call.get("alpha") == chart_generator_reference.GHOST_WATERMARK_OPACITY
        ]
        self.assertTrue(watermark_calls)
        self.assertLessEqual(watermark_calls[0]["alpha"], 0.05)
        self.assertLess(watermark_calls[0]["zorder"], min(wick_zorders))

    @unittest.skipIf(chart_generator is None, "matplotlib is not installed")
    def test_generate_levels_chart_passes_signal_scope_to_reference_renderer(self):
        import chart_generator_reference

        captured = {}

        def fake_reference(symbol, candles, current_price, supports, resistances, **kwargs):
            captured.update(kwargs)
            return "/tmp/scope-chart.png"

        with patch.object(chart_generator_reference, "generate_reference_levels_chart", side_effect=fake_reference):
            path = chart_generator.generate_levels_chart(
                "BTC/USD",
                [candle(110, 100)],
                105,
                supports=[100],
                resistances=[110],
                signal_scope="15m signal - snapshot in time, not a trend call",
            )

        self.assertEqual(path, "/tmp/scope-chart.png")
        self.assertEqual(captured["signal_scope"], "15m signal - snapshot in time, not a trend call")


if __name__ == "__main__":
    unittest.main()
