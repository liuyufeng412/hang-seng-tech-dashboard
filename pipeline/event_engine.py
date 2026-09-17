from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import Any


def _pct(start: float, end: float) -> float:
    return 0.0 if not start else (end / start - 1.0) * 100.0


def _level_type(event_type: str) -> tuple[str, str]:
    if event_type in {"rapidDrop", "breakdown", "failedBreakout"}:
        return "warning", "资金"
    if event_type in {"breakout", "rapidRise", "failedBreakdown"}:
        return "turn", "资金"
    if event_type == "volumeSpike":
        return "warning", "资金"
    return "turn", "外盘"


def detect_events(
    bars: list[dict[str, Any]],
    constituent_minutes: dict[str, list[dict[str, Any]]],
    constituents: list[dict[str, Any]],
    cross_markets: list[dict[str, Any]],
    news: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(bars) < 20:
        return []
    closes = [float(bar["close"]) for bar in bars]
    turnovers = [float(bar.get("turnover") or 0) for bar in bars]
    five_moves = [abs(_pct(closes[max(0, i - 5)], closes[i])) for i in range(5, len(closes))]
    move_threshold = max(0.22, median(five_moves) * 2.5 if five_moves else 0.22)
    positive_turnovers = [value for value in turnovers if value > 0]
    turnover_median = median(positive_turnovers) if positive_turnovers else 0
    candidates: list[tuple[int, int, str, float]] = []

    for index in range(5, len(bars)):
        move = _pct(closes[index - 5], closes[index])
        if move >= move_threshold:
            candidates.append((index - 5, index, "rapidRise", abs(move)))
        elif move <= -move_threshold:
            candidates.append((index - 5, index, "rapidDrop", abs(move)))
        if turnover_median and turnovers[index] >= turnover_median * 3:
            candidates.append((max(0, index - 1), index, "volumeSpike", turnovers[index] / turnover_median))

    rolling_window = 30
    for index in range(rolling_window, len(bars)):
        prior = closes[index - rolling_window : index]
        recent_turnover = median([value for value in turnovers[max(0, index - 10) : index] if value > 0] or [1])
        volume_confirmed = turnovers[index] > recent_turnover * 1.4
        if closes[index] > max(prior) * 1.0005 and volume_confirmed:
            candidates.append((index - 1, index, "breakout", 2.0))
        elif closes[index] < min(prior) * 0.9995 and volume_confirmed:
            candidates.append((index - 1, index, "breakdown", 2.0))

    for index in range(10, len(bars) - 10):
        left = closes[index - 10 : index]
        right = closes[index + 1 : index + 11]
        if closes[index] == max(left + [closes[index]]) and _pct(closes[index], min(right)) <= -move_threshold:
            candidates.append((index, index + 10, "reversal", 2.5))
        elif closes[index] == min(left + [closes[index]]) and _pct(closes[index], max(right)) >= move_threshold:
            candidates.append((index, index + 10, "reversal", 2.5))

    breakouts = [candidate for candidate in candidates if candidate[2] in {"breakout", "breakdown"}]
    for start_index, end_index, event_type, _ in breakouts:
        level = closes[start_index]
        future = closes[end_index + 1 : end_index + 16]
        if event_type == "breakout" and future and min(future) < level:
            return_index = end_index + 1 + next(i for i, value in enumerate(future) if value < level)
            candidates.append((start_index, return_index, "failedBreakout", 3.0))
        if event_type == "breakdown" and future and max(future) > level:
            return_index = end_index + 1 + next(i for i, value in enumerate(future) if value > level)
            candidates.append((start_index, return_index, "failedBreakdown", 3.0))

    candidates.sort(key=lambda item: (item[1], -item[3]))
    deduped: list[tuple[int, int, str, float]] = []
    for candidate in candidates:
        if deduped and candidate[1] - deduped[-1][1] < 6:
            if candidate[3] > deduped[-1][3]:
                deduped[-1] = candidate
            continue
        deduped.append(candidate)

    name_by_code = {item["code"]: item["name"] for item in constituents}
    events = []
    for number, (start_index, end_index, event_type, _) in enumerate(deduped, start=1):
        start_bar, end_bar = bars[start_index], bars[end_index]
        event_start = datetime.fromisoformat(start_bar["timestamp"])
        event_end = datetime.fromisoformat(end_bar["timestamp"])
        related_stocks = []
        for code, stock_bars in constituent_minutes.items():
            lookup = {bar["time"]: bar for bar in stock_bars}
            start_stock = lookup.get(start_bar["time"])
            end_stock = lookup.get(end_bar["time"])
            if start_stock and end_stock:
                change_pct = _pct(float(start_stock["close"]), float(end_stock["close"]))
                related_stocks.append({"code": code, "name": name_by_code.get(code, code), "changePct": round(change_pct, 3)})
        direction = 1 if float(end_bar["close"]) >= float(start_bar["close"]) else -1
        related_stocks.sort(key=lambda item: direction * item["changePct"], reverse=True)
        related_stocks = related_stocks[:5]

        event_news = []
        for item in news:
            published = datetime.fromisoformat(item["publishedAt"])
            if event_start - timedelta(minutes=30) <= published <= event_end + timedelta(minutes=30):
                event_news.append({"eventId": item["eventId"], "headline": item["headline"], "publishedAt": item["publishedAt"], "publisher": item["publisher"]})

        cross_moves = []
        for market in cross_markets:
            if market.get("sessionRelationship") != "same_session":
                continue
            market_bars = market.get("bars", [])
            before = [bar for bar in market_bars if datetime.fromisoformat(bar["timestamp"].replace("Z", "+00:00")) <= event_start]
            after = [bar for bar in market_bars if datetime.fromisoformat(bar["timestamp"].replace("Z", "+00:00")) <= event_end]
            if before and after:
                change_pct = _pct(float(before[-1]["close"]), float(after[-1]["close"]))
                cross_moves.append({"key": market["key"], "name": market["name"], "changePct": round(change_pct, 3)})

        move = float(end_bar["close"]) - float(start_bar["close"])
        move_pct = _pct(float(start_bar["close"]), float(end_bar["close"]))
        event_turnover = sum(turnovers[start_index : end_index + 1])
        baseline = turnover_median * (end_index - start_index + 1) if turnover_median else 0
        volume_change = (event_turnover / baseline - 1) * 100 if baseline else None
        attribution = "possible" if event_news else "structural"
        evidence = [
            f"指数在 {end_index - start_index + 1} 分钟内变动 {move_pct:+.2f}%",
            f"区间成交额相对分钟中位数 {volume_change:+.0f}%" if volume_change is not None else "成交额基准不可用",
        ]
        if cross_moves:
            evidence.append("同一窗口跨市场数据已对齐")
        if event_news:
            evidence.append("存在发布时间接近的新闻，仅列为可能相关")
        confidence = "high" if abs(move_pct) >= move_threshold and volume_change and volume_change > 50 else "medium"
        kind, category = _level_type(event_type)
        events.append(
            {
                "id": f"event-{number}-{end_bar['time'].replace(':', '')}",
                "startTime": start_bar["time"],
                "endTime": end_bar["time"],
                "indexStart": round(float(start_bar["close"]), 2),
                "indexEnd": round(float(end_bar["close"]), 2),
                "change": round(move, 2),
                "changePct": round(move_pct, 3),
                "volumeChange": round(volume_change, 1) if volume_change is not None else None,
                "eventType": event_type,
                "kind": kind,
                "category": category,
                "title": {
                    "rapidRise": "短时快速上涨",
                    "rapidDrop": "短时快速下跌",
                    "reversal": "局部反转",
                    "breakout": "放量突破",
                    "breakdown": "放量破位",
                    "volumeSpike": "成交量异常放大",
                    "failedBreakout": "突破失败",
                    "failedBreakdown": "破位后收回",
                }[event_type],
                "relatedStocks": related_stocks,
                "crossMarketMoves": cross_moves,
                "relatedNews": event_news,
                "technicalContext": f"前30分钟区间 {min(closes[max(0, end_index-30):end_index+1]):.2f}–{max(closes[max(0, end_index-30):end_index+1]):.2f}",
                "possibleExplanation": "价格与成交结构共同触发；未发现足够证据确认单一新闻因果。" if not event_news else "同期存在新闻，但目前只有时间接近证据，归因仍需市场与成分股响应验证。",
                "evidence": evidence,
                "attributionLevel": attribution,
                "confidence": confidence,
                "pointIndex": end_index,
            }
        )
    return events
