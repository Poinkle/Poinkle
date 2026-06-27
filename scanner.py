from market_data import fetch_top_100_assets
from scoring import opportunity_label, rank_snapshots, strategy_text, strongest_opportunity_score
from symbol_mapper import map_top_assets_to_pairs


def tradingview_exchange(symbol):
    if symbol.endswith("/USD"):
        return "COINBASE"
    if symbol.endswith("/USDT"):
        return "BINANCE"
    return "CRYPTO"


def tradingview_url(symbol):
    exchange = tradingview_exchange(symbol)
    compact_symbol = symbol.replace("/", "")
    return f"https://www.tradingview.com/chart/?symbol={exchange}%3A{compact_symbol}"


def scan_top_100(exchange, requests_module, levels_snapshot_builder, scan_filter=None, limit=10):
    assets = fetch_top_100_assets(requests_module)
    mapped_assets = map_top_assets_to_pairs(assets, exchange)
    snapshots = []

    for mapped_asset in mapped_assets:
        symbol = mapped_asset["symbol"]
        try:
            snapshot = levels_snapshot_builder(exchange, symbol)
        except Exception as error:
            print(f"Skipping {symbol} during /scan: {error}")
            continue

        snapshot["ticker"] = mapped_asset["ticker"]
        snapshot["asset_name"] = mapped_asset["asset"].get("name", mapped_asset["ticker"])
        snapshot["symbol"] = symbol
        snapshot["opportunity_label"] = opportunity_label(snapshot)
        snapshot["opportunity_score"] = strongest_opportunity_score(snapshot)
        snapshot["strategy_text"] = strategy_text(snapshot["strategy"])
        snapshot["tradingview_url"] = tradingview_url(symbol)
        snapshots.append(snapshot)

    return rank_snapshots(snapshots, scan_filter)[:limit]


def format_scan_message(results, price_formatter, scan_filter=None):
    title = "🔎 <b>Poinkle Top 100 Scan</b>"
    if scan_filter:
        title += f" — {scan_filter.title()}"

    if not results:
        return (
            f"{title}\n\n"
            "No valid opportunities found right now. Try again after the next candle closes."
        )

    lines = [title]
    for index, result in enumerate(results, start=1):
        ticker = result["ticker"]
        price = price_formatter(result["current_price"])
        tv_url = result["tradingview_url"]
        lines.extend(
            [
                "",
                (
                    f'{index}. <a href="{tv_url}">{ticker}</a> — '
                    f"Score {result['opportunity_score']} — {result['opportunity_label']}"
                ),
                f"Bias: {result['bias']}",
                f"Price: ${price}",
                f"Strategy: {result['strategy_text']}",
            ]
        )

    return "\n".join(lines)
