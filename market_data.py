COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"


def fetch_top_100_assets(requests_module, vs_currency="usd"):
    if requests_module is None:
        raise RuntimeError("requests is required for /scan")

    response = requests_module.get(
        COINGECKO_MARKETS_URL,
        params={
            "vs_currency": vs_currency,
            "order": "market_cap_desc",
            "per_page": 100,
            "page": 1,
            "sparkline": "false",
        },
        timeout=20,
    )
    response.raise_for_status()
    assets = response.json()
    if not isinstance(assets, list):
        raise RuntimeError("CoinGecko returned an unexpected response")
    return assets
