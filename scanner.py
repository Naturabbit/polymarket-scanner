"""Deep scanner for all Polymarket markets.

Requirements implemented:
- Full pagination with limit=100, offset increment by 100 until empty response.
- No active/tag filters in API request (scan all markets).
- Compare outcomes and outcomePrices index-by-index.
- Match options with price > 0 and <= 0.0011.
- Add sleep(0.2) each loop to reduce request rate.
- Print progress every scanned 100 markets.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List
from urllib.parse import quote

import requests

API_URL = "https://gamma-api.polymarket.com/markets"
LIMIT = 100
PRICE_MAX = 0.0011
REQUEST_TIMEOUT = 20
SLEEP_SECONDS = 0.2


def _normalize_list(value: Any) -> List[Any]:
    """Normalize list-like API values (list or JSON-string list) to Python list."""
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


def _extract_prices(market: Dict[str, Any]) -> List[float]:
    """Extract outcomePrices as float list; invalid entries become NaN."""
    raw_prices = _normalize_list(market.get("outcomePrices"))
    prices: List[float] = []

    for item in raw_prices:
        try:
            prices.append(float(item))
        except (TypeError, ValueError):
            prices.append(float("nan"))

    return prices


def _extract_outcomes(market: Dict[str, Any]) -> List[str]:
    """Extract outcomes as strings in the same order as outcomePrices."""
    raw_outcomes = _normalize_list(market.get("outcomes"))
    return [str(item).strip() for item in raw_outcomes]


def fetch_all_markets() -> List[Dict[str, Any]]:
    """Fetch all Polymarket markets with full pagination."""
    all_markets: List[Dict[str, Any]] = []
    offset = 0

    while True:
        params = {
            "limit": LIMIT,
            "offset": offset,
        }

        try:
            response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            batch = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"请求 Polymarket API 失败: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError(f"API 返回非 JSON: {exc}") from exc

        if not isinstance(batch, list):
            raise RuntimeError("API 返回格式异常：预期 list")

        if not batch:
            break

        all_markets.extend(batch)

        print(f"已扫描 {len(all_markets)} 个标的...")

        offset += LIMIT
        time.sleep(SLEEP_SECONDS)

    return all_markets


def scan_low_price_options(markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Scan every market option and return matches where 0 < price <= 0.0011."""
    matches: List[Dict[str, Any]] = []

    for market in markets:
        question = str(market.get("question") or market.get("title") or "").strip() or "N/A"
        slug = str(market.get("slug") or "").strip()
        event_link = f"https://polymarket.com/event/{slug}" if slug else "N/A"

        outcomes = _extract_outcomes(market)
        prices = _extract_prices(market)

        if not prices:
            continue

        if len(outcomes) < len(prices):
            outcomes.extend([f"Outcome {i + 1}" for i in range(len(outcomes), len(prices))])

        for idx, price in enumerate(prices):
            # Skip NaN
            if price != price:
                continue

            if price > 0 and price <= PRICE_MAX:
                outcome_name = outcomes[idx] if idx < len(outcomes) else f"Outcome {idx + 1}"
                option_link = (
                    f"https://polymarket.com/event/{slug}?outcome={quote(outcome_name)}"
                    if slug
                    else "N/A"
                )

                match = {
                    "question": question,
                    "outcome": outcome_name,
                    "price": price,
                    "event_link": event_link,
                    "option_link": option_link,
                }
                matches.append(match)

                print(f"市场标题: {question}")
                print(f"选项名称: {outcome_name}")
                print(f"准确价格: {price:.10f}")
                print(f"链接: {option_link}")
                print("-" * 60)

    return matches


def main() -> int:
    try:
        markets = fetch_all_markets()
        matches = scan_low_price_options(markets)
        print(f"扫描结束，共发现 {len(matches)} 条 0.1¢ 附近低价选项。")
        return 0
    except Exception as exc:
        print(f"执行失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
