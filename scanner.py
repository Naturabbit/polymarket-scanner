"""Manual Polymarket market filter.

筛选条件：
1) active=true 且 closed=false
2) tags 包含 Culture 或 Geopolitics
3) outcomePrices 任意价格 <= 0.001
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

import requests

API_URL = "https://gamma-api.polymarket.com/markets"
ALLOWED_TAGS = {"culture", "geopolitics"}
PRICE_THRESHOLD = 0.001
REQUEST_TIMEOUT = 20
PAGE_LIMIT = 500


def _normalize_tags(raw_tags: Any) -> List[str]:
    """从多种 tag 结构中提取字符串标签。"""
    tags: List[str] = []

    if not isinstance(raw_tags, list):
        return tags

    for tag in raw_tags:
        if isinstance(tag, str):
            tags.append(tag.strip())
        elif isinstance(tag, dict):
            # 兼容常见结构: {label/name/slug: "..."}
            value = tag.get("label") or tag.get("name") or tag.get("slug")
            if isinstance(value, str):
                tags.append(value.strip())

    return [t for t in tags if t]


def _extract_prices(market: Dict[str, Any]) -> List[float]:
    """提取 outcomePrices 并转换为 float 列表。"""
    raw_prices = market.get("outcomePrices")
    if not isinstance(raw_prices, list):
        return []

    prices: List[float] = []
    for p in raw_prices:
        try:
            prices.append(float(p))
        except (TypeError, ValueError):
            continue

    return prices


def _passes_tag_filter(tags: Iterable[str]) -> bool:
    lower_tags = {t.lower() for t in tags}
    return any(tag in lower_tags for tag in ALLOWED_TAGS)


def fetch_active_markets() -> List[Dict[str, Any]]:
    """分页拉取 active=true 且 closed=false 的市场。"""
    all_markets: List[Dict[str, Any]] = []
    offset = 0

    while True:
        params = {
            "active": "true",
            "closed": "false",
            "limit": PAGE_LIMIT,
            "offset": offset,
        }

        try:
            resp = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"请求 Polymarket API 失败: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError(f"API 返回非 JSON: {exc}") from exc

        if not isinstance(data, list):
            raise RuntimeError("API 返回格式异常：预期 list")

        if not data:
            break

        all_markets.extend(data)

        if len(data) < PAGE_LIMIT:
            break

        offset += PAGE_LIMIT

    return all_markets


def scan_markets(markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """执行标签 + 价格阈值筛选。"""
    results: List[Dict[str, Any]] = []

    for market in markets:
        tags = _normalize_tags(market.get("tags"))
        if not _passes_tag_filter(tags):
            continue

        prices = _extract_prices(market)
        if not prices:
            continue

        if not any(price <= PRICE_THRESHOLD for price in prices):
            continue

        question = str(market.get("question") or market.get("title") or "").strip()
        slug = str(market.get("slug") or "").strip()
        link = f"https://polymarket.com/event/{slug}" if slug else ""

        results.append(
            {
                "question": question,
                "prices": prices,
                "tags": tags,
                "link": link,
            }
        )

    return results


def print_results(results: List[Dict[str, Any]]) -> None:
    if not results:
        print("未找到符合条件的标的。")
        return

    print(f"共找到 {len(results)} 个符合条件的标的:\n")
    for idx, item in enumerate(results, start=1):
        prices_text = ", ".join(f"{p:.6f}" for p in item["prices"])
        tags_text = ", ".join(item["tags"]) if item["tags"] else "N/A"

        print(f"[{idx}] {item['question'] or 'N/A'}")
        print(f"    Prices : [{prices_text}]")
        print(f"    Tags   : {tags_text}")
        print(f"    Link   : {item['link'] or 'N/A'}")
        print()


def main() -> int:
    try:
        markets = fetch_active_markets()
        results = scan_markets(markets)
        print_results(results)
        return 0
    except Exception as exc:
        print(f"执行失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
