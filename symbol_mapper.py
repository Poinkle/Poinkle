QUOTE_PREFERENCE = ("USD", "USDT")


def asset_ticker(asset):
    return str(asset.get("symbol", "")).strip().upper()


def load_exchange_symbols(exchange):
    try:
        markets = exchange.load_markets()
    except Exception:
        markets = getattr(exchange, "markets", None) or {}

    if isinstance(markets, dict):
        symbols = set(markets.keys())
    else:
        symbols = set(markets or [])

    return symbols


def map_asset_to_pair(asset, available_symbols, quote_preference=QUOTE_PREFERENCE):
    ticker = asset_ticker(asset)
    if not ticker:
        return None

    for quote in quote_preference:
        symbol = f"{ticker}/{quote}"
        if symbol in available_symbols:
            return symbol

    return None


def map_top_assets_to_pairs(assets, exchange, quote_preference=QUOTE_PREFERENCE):
    available_symbols = load_exchange_symbols(exchange)
    mapped = []
    seen_symbols = set()

    for asset in assets:
        symbol = map_asset_to_pair(asset, available_symbols, quote_preference)
        if not symbol or symbol in seen_symbols:
            continue

        mapped.append(
            {
                "asset": asset,
                "ticker": asset_ticker(asset),
                "symbol": symbol,
            }
        )
        seen_symbols.add(symbol)

    return mapped
