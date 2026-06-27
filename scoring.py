FILTER_ALIASES = {
    "support": "support",
    "breakout": "breakout",
    "oversold": "oversold",
    "bullish": "bullish",
    "bearish": "bearish",
}


def strategy_text(use_cases):
    return " / ".join(use_case.replace("✓ ", "").replace("✗ ", "") for use_case in use_cases)


def opportunity_label(snapshot):
    support_label = snapshot["support_distance_label"]
    rsi_value = snapshot["rsi"]
    bias = snapshot["bias"]
    distance_to_resistance = snapshot["distance_to_resistance"]

    if support_label in {"At Support", "Near Support", "Approaching Support"}:
        return support_label
    if rsi_value <= 35:
        return "Oversold Watch"
    if bias == "Bullish" and distance_to_resistance is not None and distance_to_resistance <= 10:
        return "Breakout Watch"
    if bias == "Neutral":
        return "Reclaim Setup"
    return snapshot["location"]


def strongest_opportunity_score(snapshot):
    score = snapshot["market_score"]
    support_label = snapshot["support_distance_label"]

    if support_label == "At Support":
        score += 12
    elif support_label == "Near Support":
        score += 9
    elif support_label == "Approaching Support":
        score += 6

    if snapshot["rsi"] <= 35:
        score += 5
    if snapshot["bias"] == "Bullish":
        score += 4
    if snapshot["accumulation_grade"] in {"A", "B"}:
        score += 4

    return min(score, 100)


def matches_filter(snapshot, scan_filter):
    if not scan_filter:
        return True

    normalized_filter = FILTER_ALIASES.get(scan_filter.lower())
    if normalized_filter is None:
        return True

    if normalized_filter == "support":
        return snapshot["support_distance_label"] in {"At Support", "Near Support", "Approaching Support"}
    if normalized_filter == "breakout":
        return snapshot["distance_to_resistance"] is not None and snapshot["distance_to_resistance"] <= 10
    if normalized_filter == "oversold":
        return snapshot["rsi"] <= 35
    if normalized_filter == "bullish":
        return snapshot["bias"] == "Bullish"
    if normalized_filter == "bearish":
        return snapshot["bias"] == "Bearish"

    return True


def rank_snapshots(snapshots, scan_filter=None):
    filtered = [snapshot for snapshot in snapshots if matches_filter(snapshot, scan_filter)]
    return sorted(filtered, key=lambda snapshot: snapshot["opportunity_score"], reverse=True)
