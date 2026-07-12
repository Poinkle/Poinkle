#!/usr/bin/env python3
"""
Standalone KuCoin timing probe for muted watchlist symbols.

This script does not import or modify the scanner. It creates one ccxt.kucoin
object, times load_markets() separately, then measures the per-symbol cost of
the fetches a future scan route would likely need.
"""

import statistics
import time


SYMBOLS = [
    "THETA",
    "NEXO",
    "EOS",
    "KAIA",
    "IOTA",
    "BRETT",
    "TWT",
    "ZIL",
    "ELF",
    "SFP",
    "HOT",
    "RVN",
]

TIMEFRAME_DAILY = "1d"
TIMEFRAME_MIDDLE = "6h"
CANDLE_LIMIT = 120


def elapsed_call(fn):
    started = time.perf_counter()
    try:
        result = fn()
        return time.perf_counter() - started, result, None
    except Exception as error:
        return time.perf_counter() - started, None, error


def format_seconds(value):
    return f"{value:.3f}s"


def summarize(label, values):
    if not values:
        print(f"{label}: no successful timings")
        return
    print(
        f"{label}: count={len(values)} "
        f"total={format_seconds(sum(values))} "
        f"avg={format_seconds(statistics.mean(values))} "
        f"median={format_seconds(statistics.median(values))} "
        f"max={format_seconds(max(values))}"
    )


def main():
    try:
        import ccxt
    except ModuleNotFoundError:
        raise SystemExit("Missing ccxt. Run this from the project venv or install requirements first.")

    exchange = ccxt.kucoin({"enableRateLimit": True})

    print("KuCoin scan-cost timing probe")
    print(f"Exchange: {exchange.id}")
    print(f"Configured rateLimit: {getattr(exchange, 'rateLimit', 'unknown')} ms")
    print(f"fetchOHLCV supported: {exchange.has.get('fetchOHLCV')}")
    print()

    load_seconds, markets, load_error = elapsed_call(exchange.load_markets)
    if load_error:
        raise SystemExit(f"load_markets failed after {format_seconds(load_seconds)}: {load_error}")

    print(f"load_markets: {format_seconds(load_seconds)} one-time startup cost")
    print(f"markets loaded: {len(markets)}")
    print()

    daily_timings = []
    ticker_timings = []
    six_hour_timings = []
    total_timings = []
    unsupported = []

    for base in SYMBOLS:
        symbol = f"{base}/USDT"
        print(f"{base}/USD -> {symbol}")
        if symbol not in markets:
            print("  unsupported on KuCoin")
            unsupported.append(symbol)
            print()
            continue

        symbol_started = time.perf_counter()

        daily_seconds, daily_candles, daily_error = elapsed_call(
            lambda symbol=symbol: exchange.fetch_ohlcv(
                symbol,
                timeframe=TIMEFRAME_DAILY,
                limit=CANDLE_LIMIT,
            )
        )
        if daily_error:
            print(f"  daily OHLCV: {format_seconds(daily_seconds)} ERROR {daily_error}")
        else:
            daily_timings.append(daily_seconds)
            print(f"  daily OHLCV: {format_seconds(daily_seconds)} candles={len(daily_candles or [])}")

        ticker_seconds, ticker, ticker_error = elapsed_call(
            lambda symbol=symbol: exchange.fetch_ticker(symbol)
        )
        if ticker_error:
            print(f"  ticker:      {format_seconds(ticker_seconds)} ERROR {ticker_error}")
        else:
            ticker_timings.append(ticker_seconds)
            last = (ticker or {}).get("last") or (ticker or {}).get("close")
            print(f"  ticker:      {format_seconds(ticker_seconds)} last={last}")

        six_hour_seconds, six_hour_candles, six_hour_error = elapsed_call(
            lambda symbol=symbol: exchange.fetch_ohlcv(
                symbol,
                timeframe=TIMEFRAME_MIDDLE,
                limit=CANDLE_LIMIT,
            )
        )
        if six_hour_error:
            print(f"  6h OHLCV:    {format_seconds(six_hour_seconds)} ERROR {six_hour_error}")
        else:
            six_hour_timings.append(six_hour_seconds)
            print(f"  6h OHLCV:    {format_seconds(six_hour_seconds)} candles={len(six_hour_candles or [])}")

        symbol_total = time.perf_counter() - symbol_started
        total_timings.append(symbol_total)
        print(f"  symbol total:{format_seconds(symbol_total)}")
        print()

    print("Summary")
    print(f"unsupported symbols: {', '.join(unsupported) if unsupported else 'none'}")
    summarize("daily OHLCV", daily_timings)
    summarize("ticker", ticker_timings)
    summarize("6h OHLCV", six_hour_timings)
    summarize("per-symbol total", total_timings)
    if total_timings:
        print(f"projected scan addition for supported symbols: {format_seconds(sum(total_timings))}")
        print(
            "Note: daily+ticker are the normal per-symbol scan cost; "
            "6h is an upper-bound/context cost that only runs for candidate alerts today."
        )


if __name__ == "__main__":
    main()
