"""Manual Polymarket market filter.

筛选条件：
1) active=true 且 closed=false
2) tags 包含 Culture 或 Geopolitics
3) outcomePrices 数组中任意价格 <= 0.001
4) 输出命中的具体选项名称（outcome）与价格
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List
from urllib.parse import quote

import requests

API_URL = "https://gamma-api.polymarket.com/markets"
ALLOWED_TAGS = {"culture", "geopolitics"}
PRICE_THRESHOLD = 0.001
REQUEST_TIMEOUT = 20
PAGE_LIMIT = 500


def _normalize_list(value: Any) -> List[Any]:
    """将 list 或 JSON 字符串 list 统一为 Python list。"""
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


def _normalize_tags(raw_tags: Any) -> List[str]:
    """从多种 tag 结构中提取字符串标签。"""
    tags: List[str] = []
    tag_list = _normalize_list(raw_tags)

    for tag in tag_list:
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
    raw_prices = _normalize_list(market.get("outcomePrices"))

    prices: List[float] = []
    for p in raw_prices:
        try:
            prices.append(float(p))
        except (TypeError, ValueError):
            prices.append(float("nan"))

    return prices


def _extract_outcomes(market: Dict[str, Any]) -> List[str]:
    """提取 outcomes（与 outcomePrices 按索引一一对应）。"""
    raw_outcomes = _normalize_list(market.get("outcomes"))
    outcomes: List[str] = []

    for item in raw_outcomes:
        outcomes.append(str(item).strip())

    return outcomes


def _passes_tag_filter(tags: Iterable[str]) -> bool:
    lower_tags = [t.lower() for t in tags]
    return any(any(allowed in tag for tag in lower_tags) for allowed in ALLOWED_TAGS)


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
    """执行标签筛选 + 多选项低价命中筛选。"""
    results: List[Dict[str, Any]] = []

    for market in markets:
        tags = _normalize_tags(market.get("tags"))
        if not _passes_tag_filter(tags):
            continue

        prices = _extract_prices(market)
        outcomes = _extract_outcomes(market)
        if not prices:
            continue

        # 确保 outcomes 与 prices 按索引对齐，缺失时使用占位名称。
        if len(outcomes) < len(prices):
            outcomes.extend([f"Outcome {i + 1}" for i in range(len(outcomes), len(prices))])

        question = str(market.get("question") or market.get("title") or "").strip() or "N/A"
        slug = str(market.get("slug") or "").strip()
        event_link = f"https://polymarket.com/event/{slug}" if slug else "N/A"

        # 深度筛选：逐个 outcomePrice 判断 <= 0.001
        for idx, price in enumerate(prices):
            # 过滤 NaN
            if price != price:
                continue
            if price <= PRICE_THRESHOLD:
                outcome_name = outcomes[idx] if idx < len(outcomes) else f"Outcome {idx + 1}"
                option_link = (
                    f"https://polymarket.com/event/{slug}?outcome={quote(outcome_name)}"
                    if slug
                    else "N/A"
                )
                results.append(
                    {
                        "question": question,
                        "outcome": outcome_name,
                        "price": price,
                        "tags": tags,
                        "event_link": event_link,
                        "buy_link": option_link,
                    }
                )

    return results


def print_results(results: List[Dict[str, Any]]) -> None:
    if not results:
        print("未找到符合条件的标的。")
        return

    print(f"共找到 {len(results)} 条符合条件的低价选项:\n")
    for idx, item in enumerate(results, start=1):
        tags_text = ", ".join(item["tags"]) if item["tags"] else "N/A"

        print(f"[{idx}] 市场: {item['question']}")
        print(f"    Outcome : {item['outcome']}")
        print(f"    Price   : {item['price']:.6f}")
        print(f"    Tags    : {tags_text}")
        print(f"    Event   : {item['event_link']}")
        print(f"    BuyLink : {item['buy_link']}")
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
