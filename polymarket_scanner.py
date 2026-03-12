"""Scan Polymarket markets and rank potential trading opportunities.

This script is analysis-only. It does not place any trades.
"""

from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import config


@dataclass
class MarketOpportunity:
    """Normalized market fields plus derived metrics used for ranking."""

    market_id: str
    question: str
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    end_date: str
    spread: float
    liquidity_score: float
    volume_score: float
    opportunity_score: float


def _to_float(value: Any, default: float = 0.0) -> float:
    """Best-effort conversion of API values to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_yes_no_prices(market: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    """Extract YES/NO prices from several possible Polymarket payload shapes."""
    # Shape A: explicit price fields
    yes_direct = market.get("yesPrice")
    no_direct = market.get("noPrice")
    if yes_direct is not None and no_direct is not None:
        return _to_float(yes_direct, -1), _to_float(no_direct, -1)

    # Shape B: outcomes + outcomePrices arrays (common in gamma API)
    outcomes = market.get("outcomes")
    outcome_prices = market.get("outcomePrices")
    if isinstance(outcomes, list) and isinstance(outcome_prices, list) and len(outcomes) == len(outcome_prices):
        mapped = {str(name).strip().lower(): _to_float(price, -1) for name, price in zip(outcomes, outcome_prices)}
        if "yes" in mapped and "no" in mapped:
            return mapped["yes"], mapped["no"]

    # Shape C: token objects with outcome + price
    tokens = market.get("tokens")
    if isinstance(tokens, list):
        mapped = {}
        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = str(token.get("outcome", "")).strip().lower()
            price = _to_float(token.get("price"), -1)
            if outcome:
                mapped[outcome] = price
        if "yes" in mapped and "no" in mapped:
            return mapped["yes"], mapped["no"]

    return None, None


def _is_resolved_or_inactive(market: Dict[str, Any]) -> bool:
    """Detect markets that are no longer tradable and should be ignored."""
    if market.get("resolved") is True or market.get("isResolved") is True:
        return True

    # Additional common flags that indicate inactive state.
    if market.get("closed") is True and market.get("active") is False:
        return True

    # If end date is in the past and the API marks it closed, treat as resolved/inactive.
    end_date = market.get("endDate") or market.get("end_date") or market.get("closeTime")
    if end_date and market.get("closed") is True:
        try:
            end_dt = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
            if end_dt < datetime.now(timezone.utc):
                return True
        except ValueError:
            # If parsing fails, do not auto-filter solely on date string.
            pass

    return False


def fetch_active_markets() -> List[Dict[str, Any]]:
    """Fetch all active markets from Polymarket's public Gamma API with pagination."""
    all_markets: List[Dict[str, Any]] = []
    offset = 0

    while True:
        params = {
            "active": "true",
            "closed": "false",
            "limit": config.PAGE_SIZE,
            "offset": offset,
        }

        try:
            query_string = urlencode(params)
            request_url = f"{config.API_BASE_URL}?{query_string}"
            with urlopen(request_url, timeout=config.REQUEST_TIMEOUT_SECONDS) as response:
                payload = response.read().decode("utf-8")
            batch = json.loads(payload)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to fetch markets from Polymarket API: {exc}") from exc

        if not isinstance(batch, list):
            raise RuntimeError("Unexpected API response format: expected a JSON list of markets.")

        if not batch:
            break

        all_markets.extend(batch)

        if len(batch) < config.PAGE_SIZE:
            break

        offset += config.PAGE_SIZE

    return all_markets


def normalize_and_filter_markets(markets: Iterable[Dict[str, Any]]) -> List[MarketOpportunity]:
    """Apply requirements-based filtering and compute ranking metrics."""
    opportunities: List[MarketOpportunity] = []

    for market in markets:
        if _is_resolved_or_inactive(market):
            continue

        question = str(market.get("question") or market.get("title") or "").strip()
        market_id = str(market.get("id") or market.get("conditionId") or "").strip()
        if not question or not market_id:
            continue

        yes_price, no_price = _parse_yes_no_prices(market)
        if yes_price is None or no_price is None:
            continue

        if not (0 <= yes_price <= 1 and 0 <= no_price <= 1):
            continue

        volume = _to_float(market.get("volume") or market.get("volumeNum") or market.get("volumeUsd"), 0.0)
        liquidity = _to_float(market.get("liquidity") or market.get("liquidityNum") or market.get("liquidityUsd"), 0.0)

        # Requirement: remove low-activity markets.
        if volume < config.MIN_VOLUME_USD or liquidity < config.MIN_LIQUIDITY_USD:
            continue

        if volume <= 0 or liquidity <= 0:
            continue

        spread = abs((yes_price + no_price) - 1)
        liquidity_score = math.log(liquidity)
        volume_score = math.log(volume)

        # Ranking formula from requirements:
        # opportunity_score = (2 * spread) + (0.5 * liquidity_score) + (0.5 * volume_score)
        opportunity_score = (2 * spread) + (0.5 * liquidity_score) + (0.5 * volume_score)

        end_date = str(market.get("endDate") or market.get("end_date") or market.get("closeTime") or "")

        opportunities.append(
            MarketOpportunity(
                market_id=market_id,
                question=question,
                yes_price=yes_price,
                no_price=no_price,
                volume=volume,
                liquidity=liquidity,
                end_date=end_date,
                spread=spread,
                liquidity_score=liquidity_score,
                volume_score=volume_score,
                opportunity_score=opportunity_score,
            )
        )

    opportunities.sort(key=lambda item: item.opportunity_score, reverse=True)
    return opportunities[: config.TOP_N_RESULTS]


def print_ranked_table(opportunities: List[MarketOpportunity]) -> None:
    """Print a human-readable table of ranked opportunities."""
    headers = [
        "Rank",
        "Market question",
        "YES",
        "NO",
        "Volume",
        "Liquidity",
        "Spread",
        "Opportunity",
    ]

    rows = []
    for idx, item in enumerate(opportunities, start=1):
        rows.append(
            [
                str(idx),
                item.question,
                f"{item.yes_price:.4f}",
                f"{item.no_price:.4f}",
                f"{item.volume:,.0f}",
                f"{item.liquidity:,.0f}",
                f"{item.spread:.4f}",
                f"{item.opportunity_score:.4f}",
            ]
        )

    if not rows:
        print("No qualifying opportunities found after applying filters.")
        return

    # Basic fixed-width formatter (no external table package required).
    widths = [len(header) for header in headers]
    for row in rows:
        for col_idx, cell in enumerate(row):
            widths[col_idx] = min(max(widths[col_idx], len(cell)), 80)

    def truncate(value: str, max_len: int) -> str:
        return value if len(value) <= max_len else value[: max_len - 3] + "..."

    separator = " | "
    header_line = separator.join(truncate(h, widths[i]).ljust(widths[i]) for i, h in enumerate(headers))
    divider = "-+-".join("-" * widths[i] for i in range(len(headers)))
    print(header_line)
    print(divider)

    for row in rows:
        line = separator.join(truncate(cell, widths[i]).ljust(widths[i]) for i, cell in enumerate(row))
        print(line)


def save_to_csv(opportunities: List[MarketOpportunity], output_path: str) -> None:
    """Persist top opportunities to CSV for manual review."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            [
                "rank",
                "market_id",
                "market_question",
                "yes_price",
                "no_price",
                "volume",
                "liquidity",
                "end_date",
                "spread",
                "opportunity_score",
            ]
        )

        for idx, item in enumerate(opportunities, start=1):
            writer.writerow(
                [
                    idx,
                    item.market_id,
                    item.question,
                    f"{item.yes_price:.6f}",
                    f"{item.no_price:.6f}",
                    f"{item.volume:.2f}",
                    f"{item.liquidity:.2f}",
                    item.end_date,
                    f"{item.spread:.6f}",
                    f"{item.opportunity_score:.6f}",
                ]
            )


def main() -> int:
    """Program entrypoint."""
    try:
        markets = fetch_active_markets()
        opportunities = normalize_and_filter_markets(markets)
        print_ranked_table(opportunities)
        save_to_csv(opportunities, config.OUTPUT_CSV_PATH)
        print(f"\nSaved {len(opportunities)} opportunities to {config.OUTPUT_CSV_PATH}")
        return 0
    except Exception as exc:  # Keep top-level handling user-friendly for CLI usage.
        print(f"Scanner failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
