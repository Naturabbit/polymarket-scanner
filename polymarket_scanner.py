"""Polymarket market opportunity scanner.

This script is analysis-only and does not execute trades.
"""

from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

API_BASE_URL = "https://gamma-api.polymarket.com/markets"
REQUEST_TIMEOUT_SECONDS = 20
PAGE_SIZE = 500
TOP_N_RESULTS = 20
MIN_VOLUME_USD = 50_000
MIN_LIQUIDITY_USD = 10_000
OUTPUT_CSV_PATH = "output/opportunities.csv"


@dataclass
class MarketOpportunity:
    """Normalized market data + derived scores."""

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
    """Convert API value to float with fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_list_field(value: Any) -> List[Any]:
    """Normalize API fields that may be list values or JSON-encoded lists."""
    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return parsed

    return []


def _parse_yes_no_prices(market: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Extract YES/NO prices from common Polymarket payload formats."""
    # Format 1: explicit keys
    if market.get("yesPrice") is not None and market.get("noPrice") is not None:
        return _to_float(market.get("yesPrice"), -1), _to_float(market.get("noPrice"), -1)

    # Format 2: outcomes + outcomePrices arrays
    outcomes = _normalize_list_field(market.get("outcomes"))
    outcome_prices = _normalize_list_field(market.get("outcomePrices"))
    if outcomes and outcome_prices and len(outcomes) == len(outcome_prices):
        mapped = {str(name).strip().lower(): _to_float(price, -1) for name, price in zip(outcomes, outcome_prices)}
        if "yes" in mapped and "no" in mapped:
            return mapped["yes"], mapped["no"]

    # Format 3: token objects
    tokens = market.get("tokens")
    if isinstance(tokens, list):
        mapped: Dict[str, float] = {}
        for token in tokens:
            if not isinstance(token, dict):
                continue
            outcome = str(token.get("outcome", "")).strip().lower()
            if outcome:
                mapped[outcome] = _to_float(token.get("price"), -1)
        if "yes" in mapped and "no" in mapped:
            return mapped["yes"], mapped["no"]

    return None, None


def _is_resolved(market: Dict[str, Any]) -> bool:
    """Determine whether a market is resolved/inactive."""
    if market.get("resolved") is True or market.get("isResolved") is True:
        return True

    if market.get("active") is False:
        return True

    if market.get("closed") is True:
        return True

    end_date = market.get("endDate") or market.get("end_date") or market.get("closeTime")
    if end_date:
        try:
            dt = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
            if dt < datetime.now(timezone.utc) and market.get("closed") is True:
                return True
        except ValueError:
            pass

    return False


def fetch_active_markets() -> List[Dict[str, Any]]:
    """Fetch all active markets from the public Polymarket API."""
    all_markets: List[Dict[str, Any]] = []
    offset = 0

    while True:
        params = {
            "active": "true",
            "closed": "false",
            "limit": PAGE_SIZE,
            "offset": offset,
        }

        try:
            response = requests.get(API_BASE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            batch = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to fetch markets: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError(f"API returned invalid JSON: {exc}") from exc

        if not isinstance(batch, list):
            raise RuntimeError("Unexpected API response: expected a list of markets.")

        if not batch:
            break

        all_markets.extend(batch)

        if len(batch) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    return all_markets


def calculate_opportunities(markets: Iterable[Dict[str, Any]]) -> List[MarketOpportunity]:
    """Filter markets and compute opportunity metrics/scores."""
    opportunities: List[MarketOpportunity] = []

    for market in markets:
        if _is_resolved(market):
            continue

        market_id = str(market.get("id") or market.get("conditionId") or "").strip()
        question = str(market.get("question") or market.get("title") or "").strip()
        if not market_id or not question:
            continue

        yes_price, no_price = _parse_yes_no_prices(market)
        if yes_price is None or no_price is None:
            continue

        if not (0 <= yes_price <= 1 and 0 <= no_price <= 1):
            continue

        volume = _to_float(market.get("volume") or market.get("volumeNum") or market.get("volumeUsd"), 0)
        liquidity = _to_float(market.get("liquidity") or market.get("liquidityNum") or market.get("liquidityUsd"), 0)

        # Required filters for illiquid/inactive markets.
        if volume < MIN_VOLUME_USD or liquidity < MIN_LIQUIDITY_USD:
            continue

        if volume <= 0 or liquidity <= 0:
            continue

        probability_yes = yes_price
        probability_no = no_price

        # Pricing inefficiency metric from requirements.
        spread = abs((probability_yes + probability_no) - 1)
        liquidity_score = math.log(liquidity)
        volume_score = math.log(volume)

        # Required opportunity score formula.
        opportunity_score = (2 * spread) + (0.5 * liquidity_score) + (0.5 * volume_score)

        opportunities.append(
            MarketOpportunity(
                market_id=market_id,
                question=question,
                yes_price=probability_yes,
                no_price=probability_no,
                volume=volume,
                liquidity=liquidity,
                end_date=str(market.get("endDate") or market.get("end_date") or market.get("closeTime") or ""),
                spread=spread,
                liquidity_score=liquidity_score,
                volume_score=volume_score,
                opportunity_score=opportunity_score,
            )
        )

    opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)
    return opportunities[:TOP_N_RESULTS]


def print_table(opportunities: List[MarketOpportunity]) -> None:
    """Print ranked opportunity table to stdout."""
    if not opportunities:
        print("No qualifying opportunities found.")
        return

    headers = ["Rank", "Market question", "YES price", "NO price", "Volume", "Liquidity", "Spread", "Opportunity score"]
    rows = []

    for i, item in enumerate(opportunities, start=1):
        rows.append(
            [
                str(i),
                item.question,
                f"{item.yes_price:.4f}",
                f"{item.no_price:.4f}",
                f"{item.volume:,.0f}",
                f"{item.liquidity:,.0f}",
                f"{item.spread:.4f}",
                f"{item.opportunity_score:.4f}",
            ]
        )

    widths = [len(h) for h in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = min(max(widths[idx], len(value)), 90)

    def _clip(text: str, max_len: int) -> str:
        return text if len(text) <= max_len else text[: max_len - 3] + "..."

    sep = " | "
    print(sep.join(_clip(h, widths[i]).ljust(widths[i]) for i, h in enumerate(headers)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(sep.join(_clip(v, widths[i]).ljust(widths[i]) for i, v in enumerate(row)))


def export_csv(opportunities: List[MarketOpportunity], output_path: str = OUTPUT_CSV_PATH) -> None:
    """Export ranked opportunities to CSV."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
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

        for i, item in enumerate(opportunities, start=1):
            writer.writerow(
                [
                    i,
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
    """CLI entrypoint."""
    try:
        markets = fetch_active_markets()
        opportunities = calculate_opportunities(markets)
        print_table(opportunities)
        export_csv(opportunities)
        print(f"\nSaved {len(opportunities)} opportunities to {OUTPUT_CSV_PATH}")
        return 0
    except Exception as exc:
        print(f"Scanner failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
