from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pipeline.event_engine import detect_events
from pipeline.sources import (
    HKT,
    SourceError,
    get_constituent_minutes,
    get_cross_market_series,
    get_hsi_factsheet,
    get_hkex_short_selling_daily,
    get_hstech_daily,
    get_news_feed,
    get_southbound_history,
    get_southbound_minutes,
    get_tencent_minutes,
    get_tencent_quotes,
    iso_now,
    news_window,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "data" / "runtime"
SESSIONS = ("morning", "midday", "evening")
SESSION_LABELS = {"morning": "早报", "midday": "午报", "evening": "晚报"}
SESSION_CUTOFFS = {"morning": "08:30", "midday": "12:00", "evening": "16:00"}
MACRO_EVENTS_PATH = PROJECT_ROOT / "data" / "config" / "macro-events.json"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _safe(callable_, source_id: str, errors: list[dict[str, str]], fallback: Any):
    try:
        return callable_()
    except Exception as exc:
        errors.append({"sourceId": source_id, "message": f"{type(exc).__name__}: {exc}"})
        return fallback


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def rebuild_runtime_index(runtime_root: Path = RUNTIME_ROOT) -> tuple[Path, Path]:
    report_root = runtime_root / "reports"
    available: dict[str, list[str]] = {}
    for date_dir in report_root.iterdir() if report_root.exists() else []:
        if not date_dir.is_dir() or not DATE_PATTERN.match(date_dir.name):
            continue
        sessions = [session for session in SESSIONS if (date_dir / f"{session}.json").is_file()]
        if sessions:
            available[date_dir.name] = sessions
    if not available:
        raise SourceError("Cannot build runtime index without report files")

    latest_date = max(available)
    latest_session = max(available[latest_date], key=SESSIONS.index)
    latest_report_path = report_root / latest_date / f"{latest_session}.json"
    latest_snapshot = json.loads(latest_report_path.read_text(encoding="utf-8"))
    index_path = runtime_root / "index.json"
    latest_path = runtime_root / "latest.json"
    index_payload = {
        "latestDate": latest_date,
        "latestSession": latest_session,
        "available": dict(sorted(available.items(), reverse=True)),
        "updatedAt": iso_now(),
    }
    _write_json_atomic(index_path, index_payload)
    _write_json_atomic(latest_path, latest_snapshot)
    return index_path, latest_path


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _pct(start: float | None, end: float | None) -> float | None:
    if start in (None, 0) or end is None:
        return None
    return (end / start - 1.0) * 100.0


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None or math.isnan(value) else round(value, digits)


def _latest_bar(bars: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any] | None:
    eligible = [bar for bar in bars if _parse_iso(bar["timestamp"]) <= cutoff.astimezone(timezone.utc)]
    return eligible[-1] if eligible else None


def _market_snapshot(series: dict[str, Any], cutoff: datetime) -> dict[str, Any] | None:
    bars = [bar for bar in series.get("bars", []) if _parse_iso(bar["timestamp"]) <= cutoff.astimezone(timezone.utc)]
    if not bars:
        return None
    exchange_tz = ZoneInfo(series["exchangeTimezone"]) if series["exchangeTimezone"] != "UTC" else timezone.utc
    grouped: dict[str, list[dict[str, Any]]] = {}
    for bar in bars:
        local_date = _parse_iso(bar["timestamp"]).astimezone(exchange_tz).date().isoformat()
        grouped.setdefault(local_date, []).append(bar)
    session_dates = sorted(grouped)
    latest_date = session_dates[-1]
    latest = grouped[latest_date][-1]
    previous = grouped[session_dates[-2]][-1] if len(session_dates) > 1 else None
    change_pct = _pct(float(previous["close"]), float(latest["close"])) if previous else None
    return {
        "key": series["key"],
        "symbol": series["symbol"],
        "name": series["name"],
        "value": _round(float(latest["close"]), 4),
        "changePct": _round(change_pct, 3),
        "timestamp": latest["timestamp"],
        "marketSessionDate": latest_date,
        "sessionRelationship": series["sessionRelationship"],
        "freshness": series["source"]["freshness"],
        "source": series["source"],
        "bars": bars,
    }


def _bars_for_session(all_bars: list[dict[str, Any]], trading_date: str, session: str) -> list[dict[str, Any]]:
    if session == "morning":
        return []
    cutoff_time = SESSION_CUTOFFS[session]
    return [
        {key: value for key, value in bar.items() if key != "source"}
        for bar in all_bars
        if bar["time"] <= cutoff_time and bar["timestamp"].startswith(trading_date)
    ]


def _constituent_snapshot(
    factsheet: dict[str, Any],
    quotes: dict[str, dict[str, Any]],
    minute_map: dict[str, list[dict[str, Any]]],
    trading_date: str,
    session: str,
    previous_index_close: float | None,
) -> list[dict[str, Any]]:
    result = []
    cutoff_time = SESSION_CUTOFFS[session]
    for member in factsheet.get("constituents", []):
        code = member["code"]
        quote = quotes.get(f"hk{code}", {})
        eligible = [bar for bar in minute_map.get(code, []) if bar["time"] <= cutoff_time]
        minute = eligible[-1] if eligible else None
        last = float(minute["close"]) if minute else None
        previous_close = quote.get("previousClose")
        change_pct = _pct(previous_close, last)
        contribution = None
        if change_pct is not None and previous_index_close is not None:
            contribution = previous_index_close * member["weight"] / 100.0 * change_pct / 100.0
        result.append(
            {
                **member,
                "officialName": member["name"],
                "name": quote.get("name") or member["name"],
                "last": _round(last, 3),
                "previousClose": _round(previous_close, 3),
                "changePct": _round(change_pct, 3),
                "turnover": _round(minute.get("cumulativeTurnover") if minute else None, 2),
                "timestamp": minute.get("timestamp") if minute else None,
                "contributionPoints": _round(contribution, 2),
                "contributionType": "estimated" if contribution is not None else "unavailable",
                "contributionMethodology": "prior index close × official factsheet weight × constituent return; approximate because intraday divisor/free-float changes are unavailable" if contribution is not None else None,
                "quoteSource": quote.get("source"),
                "weightSource": factsheet.get("source"),
            }
        )
    return result


def _index_snapshot(
    daily: list[dict[str, Any]],
    bars: list[dict[str, Any]],
    trading_date: str,
    session: str,
    minute_source: dict[str, Any] | None,
    daily_source: dict[str, Any] | None,
) -> dict[str, Any]:
    dated = [row for row in daily if row["date"] <= trading_date]
    current_daily = next((row for row in dated if row["date"] == trading_date), None)
    prior_daily = next((row for row in reversed(dated) if row["date"] < trading_date), None)
    previous_close = prior_daily.get("close") if prior_daily else None
    if session == "morning":
        last = previous_close
        return {
            "symbol": "HSTECH",
            "name": "恒生科技指数",
            "last": last,
            "previousClose": prior_daily.get("close") if prior_daily else None,
            "open": None,
            "high": None,
            "low": None,
            "change": None,
            "changePct": None,
            "volume": None,
            "turnover": prior_daily.get("turnover") if prior_daily else None,
            "timestamp": f"{prior_daily['date']}T16:00:00+08:00" if prior_daily else None,
            "status": "latest_available",
            "source": daily_source,
        }
    if not bars:
        return {"symbol": "HSTECH", "name": "恒生科技指数", "status": "unavailable", "source": minute_source}
    closes = [float(bar["close"]) for bar in bars]
    last = closes[-1]
    return {
        "symbol": "HSTECH",
        "name": "恒生科技指数",
        "last": _round(last),
        "previousClose": _round(previous_close),
        "open": _round(closes[0]),
        "high": _round(max(closes)),
        "low": _round(min(closes)),
        "change": _round(last - previous_close) if previous_close is not None else None,
        "changePct": _round(_pct(previous_close, last), 3),
        "volume": _round(bars[-1].get("cumulativeVolume"), 2),
        "turnover": _round(bars[-1].get("cumulativeTurnover"), 2),
        "timestamp": bars[-1]["timestamp"],
        "status": "delayed",
        "source": minute_source,
        "officialCloseCheck": current_daily if session == "evening" else None,
    }


def _breadth(constituents: list[dict[str, Any]]) -> dict[str, Any]:
    values = [item["changePct"] for item in constituents if item.get("changePct") is not None]
    return {
        "advances": sum(value > 0 for value in values),
        "declines": sum(value < 0 for value in values),
        "unchanged": sum(value == 0 for value in values),
        "available": len(values),
        "universe": len(constituents),
        "status": "calculated" if len(values) == len(constituents) else "partial",
        "methodology": "30只官方成分股在报告截止时点相对昨收的涨跌家数",
    }


def _technical(daily: list[dict[str, Any]], trading_date: str, index: dict[str, Any]) -> dict[str, Any]:
    closes = [float(row["close"]) for row in daily if row["date"] < trading_date and row.get("close") is not None]
    moving_averages = {}
    for period in (5, 20, 60, 120):
        moving_averages[f"ma{period}"] = _round(sum(closes[-period:]) / period) if len(closes) >= period else None
    last = index.get("last")
    named = [f"MA{period}" for period in (20, 60, 120) if moving_averages.get(f"ma{period}") is not None and last is not None and last < moving_averages[f"ma{period}"]]
    return {
        "movingAverages": moving_averages,
        "below": named,
        "state": f"位于 {'/'.join(named)} 下方" if named else "未形成三线下方",
        "valueType": "calculated",
    }


def _flow_snapshot(
    trading_date: str,
    session: str,
    daily: list[dict[str, Any]],
    intraday: list[dict[str, Any]],
    daily_source: dict[str, Any] | None,
    intraday_source: dict[str, Any] | None,
    short_selling_by_date: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    dated = [row for row in daily if row["date"] <= trading_date]
    prior = next((row for row in reversed(dated) if row["date"] < trading_date), None)
    current = next((row for row in dated if row["date"] == trading_date), None)
    items = []
    if session == "morning":
        items.append({"key": "southbound", "label": "上一交易日南向净买入", "value": prior.get("netBuy") if prior else None, "unit": "亿元人民币", "period": "上一交易日", "status": "latest_available" if prior else "unavailable", "source": daily_source})
    else:
        cutoff = SESSION_CUTOFFS[session]
        intraday_rows = [row for row in intraday if row["date"] == trading_date and row["time"] <= cutoff]
        if intraday_rows:
            value = intraday_rows[-1]["southbound"] / 10000.0
            items.append({"key": "southbound", "label": "南向资金净流向", "value": _round(value, 2), "unit": "亿元人民币", "period": f"截至 {intraday_rows[-1]['time']}", "status": "delayed_estimate", "source": intraday_source})
        elif current:
            items.append({"key": "southbound", "label": "南向成交净买额", "value": current.get("netBuy"), "unit": "亿元人民币", "period": "全天", "status": "latest_available", "source": daily_source})
        else:
            items.append({"key": "southbound", "label": "南向资金", "value": None, "unit": "亿元人民币", "period": SESSION_LABELS[session], "status": "unavailable", "source": intraday_source or daily_source})
    short_date = prior["date"] if session == "morning" and prior else trading_date if session == "evening" else None
    short_record = short_selling_by_date.get(short_date or "")
    items.append(
        {
            "key": "shortSelling",
            "label": "港股沽空比率",
            "value": short_record["data"]["ratioPct"] if short_record else None,
            "unit": "%",
            "period": "上一交易日" if session == "morning" else "全天" if session == "evening" else "午间历史口径不可回补",
            "status": "official_daily" if short_record else "not_published_or_not_available",
            "scope": short_record["data"]["scope"] if short_record else None,
            "source": short_record["source"] if short_record else None,
        }
    )
    items.append({"key": "futuresBasis", "label": "恒科期货基差", "value": None, "unit": "点", "period": SESSION_LABELS[session], "status": "unavailable", "source": None})
    return items


def _watchlist(
    index: dict[str, Any],
    bars: list[dict[str, Any]],
    daily: list[dict[str, Any]],
    trading_date: str,
    session: str,
    breadth: dict[str, Any],
    flows: list[dict[str, Any]],
    cutoff: datetime,
) -> list[dict[str, Any]]:
    prior = next((row for row in reversed(daily) if row["date"] < trading_date), None)
    if not prior:
        return []
    last = index.get("last")
    minute_closes = [float(bar["close"]) for bar in bars]

    def level_item(identifier: str, label: str, threshold: float, operator: str) -> dict[str, Any]:
        comparator = (lambda value: value > threshold) if operator == ">" else (lambda value: value < threshold)
        longest = current = 0
        triggered_at = None
        for bar in bars:
            if comparator(float(bar["close"])):
                current += 1
                if triggered_at is None:
                    triggered_at = bar["timestamp"]
                longest = max(longest, current)
            else:
                current = 0
                if longest < 30:
                    triggered_at = None
        triggered = longest > 0
        validated = longest >= 30
        status = "validated" if validated else "triggered" if triggered else "pending"
        return {
            "id": identifier,
            "conditionType": "resistance" if operator == ">" else "support",
            "conditionTypeLabel": "压力位" if operator == ">" else "支撑位",
            "group": "market",
            "label": label,
            "subject": "HSTECH",
            "operator": operator,
            "threshold": _round(threshold),
            "displayValue": f"恒科 {threshold:.0f} 点",
            "durationMinutes": 30,
            "status": status,
            "triggeredAt": triggered_at if triggered else None,
            "expected": f"需要连续30分钟{'站上' if operator == '>' else '低于'}该位置才视为有效",
            "positive": f"连续30分钟{'站稳' if operator == '>' else '快速收回'}，且市场宽度同步改善",
            "negative": f"触发后未维持30分钟，视为{'假突破' if operator == '>' else '短暂跌破'}",
            "action": "等待条件验证后再调整风险敞口",
            "subsequentPerformance": _round(_pct(threshold, last), 3) if last is not None else None,
            "validationResult": f"最长连续 {longest} 分钟",
            "valueType": "calculated",
            "importance": "high",
        }

    items: list[dict[str, Any]] = []
    level_candidates = [
        level_item("prior-high", "上一交易日高点", float(prior["high"]), ">"),
        level_item("prior-low", "上一交易日低点", float(prior["low"]), "<"),
    ]
    # 价位不是固定展示项：盘前保留开盘参考；盘中只保留已经触发，
    # 或距离当前指数不超过 2.5% 的可执行位置。
    for candidate in level_candidates:
        threshold = float(candidate["threshold"])
        distance_pct = abs(_pct(last, threshold) or 0) if last not in (None, 0) else None
        if session == "morning" or candidate["status"] != "pending" or (distance_pct is not None and distance_pct <= 2.5):
            candidate["selectionReason"] = "盘前关键参考" if session == "morning" else "已触发或接近当前价格"
            items.append(candidate)

    breadth_status = "validated" if breadth.get("advances", 0) >= 16 else "pending"
    breadth_available = int(breadth.get("available", 0) or 0)
    breadth_imbalance = abs(int(breadth.get("advances", 0) or 0) - int(breadth.get("declines", 0) or 0))
    index_change = abs(float(index.get("changePct") or 0))
    # 宽度只有在覆盖充分且出现明显分化/扩散，或指数本身显著波动时才成为关注项。
    if breadth_available >= 24 and (breadth_imbalance >= 6 or index_change >= 0.75):
        items.append({
            "id": "breadth-majority",
            "conditionType": "marketBreadth",
            "conditionTypeLabel": "市场宽度",
            "group": "market",
            "label": "上涨成分股过半",
            "subject": "HSTECH constituents",
            "operator": ">=",
            "threshold": 16,
            "displayValue": f"{breadth.get('advances', 0)} 涨 / {breadth.get('declines', 0)} 跌",
            "durationMinutes": 0,
            "status": breadth_status,
            "triggeredAt": index.get("timestamp") if breadth_status == "validated" else None,
            "expected": "30只成分股中至少16只上涨，验证反弹是否扩散",
            "positive": "权重与多数成分股同步上涨",
            "negative": "指数上涨但上涨家数不足，属于结构性托举",
            "action": "宽度未过半时，不因指数单独上涨而提高仓位",
            "validationResult": f"{breadth.get('advances', 0)}涨 / {breadth.get('declines', 0)}跌 / {breadth.get('unchanged', 0)}平",
            "valueType": "calculated",
            "importance": "medium",
            "selectionReason": "市场宽度出现明显扩散或分化",
        })

    southbound = next((item for item in flows if item["key"] == "southbound"), None)
    southbound_value = southbound.get("value") if southbound else None
    # 小幅或不可用资金数据留在复盘卡，不挤占后续关注；显著流入/流出才升级为条件。
    if southbound_value is not None and abs(float(southbound_value)) >= 5:
        items.append({
            "id": "southbound-positive",
            "conditionType": "capitalFlow",
            "conditionTypeLabel": "南向资金",
            "group": "capital",
            "label": "南向资金保持净流入",
            "subject": "southbound",
            "operator": ">",
            "threshold": 0,
            "displayValue": f"{southbound.get('value')} {southbound.get('unit')}" if southbound and southbound.get("value") is not None else "数据不可用",
            "durationMinutes": 0,
            "status": "validated" if southbound_value > 0 else "triggered",
            "triggeredAt": index.get("timestamp"),
            "expected": "资金净流入需与价格、成交和市场宽度共同确认",
            "positive": "净流入扩大且指数、宽度同步改善",
            "negative": "净流入但指数下跌，说明承接不足或存在卖压",
            "action": "仅作为承接证据，不单独形成交易结论",
            "validationResult": f"{southbound.get('value')} {southbound.get('unit')}" if southbound and southbound.get("value") is not None else "数据不可用",
            "valueType": "observed" if southbound and southbound.get("value") is not None else "unavailable",
            "importance": "high",
            "source": southbound.get("source") if southbound else None,
            "selectionReason": "南向净流向达到显著阈值",
        })

    short_selling = next((item for item in flows if item["key"] == "shortSelling"), None)
    short_value = short_selling.get("value") if short_selling else None
    # 沽空仅在高压或异常低位时进入关注区；普通水平仍保留在资金复盘中。
    if short_value is not None and (short_value >= 18 or short_value <= 12):
        items.append({
            "id": "short-selling-ratio",
            "conditionType": "shortSelling",
            "conditionTypeLabel": "沽空比率",
            "group": "capital",
            "label": "港股沽空压力",
            "subject": "Hong Kong market",
            "operator": ">=",
            "threshold": 20,
            "displayValue": f"{short_value:.2f}%" if short_value is not None else "尚未发布",
            "durationMinutes": 0,
            "status": "triggered" if short_value is not None and short_value >= 20 else "validated" if short_value is not None else "pending",
            "triggeredAt": index.get("timestamp") if short_value is not None and short_value >= 20 else None,
            "expected": "将沽空比率与指数涨跌、成交额和南向资金共同判断，单日高沽空不等于市场必然下跌。",
            "positive": "沽空比率回落，同时指数企稳、市场宽度改善，说明短线卖压缓和。",
            "negative": "沽空比率达到或高于 20%，且指数放量下跌、权重股同步转弱。",
            "action": "高沽空环境下减少追涨；若价格走强同时沽空高企，则关注潜在回补行情。",
            "validationResult": f"官方全天口径 {short_value:.2f}%" if short_value is not None else "官方数据尚未发布或当前时点不可回补",
            "valueType": "observed" if short_value is not None else "unavailable",
            "importance": "high" if short_value >= 20 else "medium",
            "source": short_selling.get("source") if short_selling else None,
            "selectionReason": "沽空比率处于需要关注的区间",
        })

    if MACRO_EVENTS_PATH.exists():
        configured = json.loads(MACRO_EVENTS_PATH.read_text(encoding="utf-8"))
        horizon = cutoff + timedelta(days=7)
        for event in configured.get("events", []):
            event_at = _parse_iso(event["eventAt"]).astimezone(HKT)
            if not (cutoff < event_at <= horizon):
                continue
            hours_until_event = (event_at - cutoff).total_seconds() / 3600
            # 一周内自动纳入高/最高优先级事件；普通事件仅在 24 小时内升级为关注项。
            if event.get("importance") not in {"high", "critical"} and hours_until_event > 24:
                continue
            fetched_at = iso_now()
            source = {
                "sourceId": f"macro_calendar_{event['id']}",
                "sourceName": event["sourceName"],
                "sourceType": event["sourceType"],
                "sourceUrl": event["sourceUrl"],
                "originalTimestamp": event["eventAt"],
                "fetchedAt": fetched_at,
                "updateFrequency": event["updateFrequency"],
                "freshness": "latest_available",
                "reliability": event["reliability"],
                "status": "scheduled",
            }
            items.append(
                {
                    "id": event["id"],
                    "conditionType": "macroEvent",
                    "conditionTypeLabel": event["category"],
                    "group": "message",
                    "label": event["name"],
                    "subject": "macro",
                    "operator": "at",
                    "threshold": 0,
                    "displayValue": event_at.strftime("%m月%d日 %H:%M（香港）"),
                    "durationMinutes": 0,
                    "status": "pending",
                    "triggeredAt": None,
                    "expected": event["expected"],
                    "positive": event["positive"],
                    "negative": event["negative"],
                    "action": event["action"],
                    "validationResult": f"待公布 · {event_at.strftime('%m月%d日 %H:%M')} 香港时间",
                    "valueType": "official_schedule",
                    "importance": event["importance"],
                    "eventAt": event["eventAt"],
                    "source": source,
                    "selectionReason": "临近的高优先级官方事件",
                }
            )
    return items


def _metrics(index: dict[str, Any], breadth: dict[str, Any], flows: list[dict[str, Any]], factsheet: dict[str, Any], technical: dict[str, Any], cross: list[dict[str, Any]]) -> list[dict[str, Any]]:
    southbound = next((item for item in flows if item["key"] == "southbound"), None)
    short_selling = next((item for item in flows if item["key"] == "shortSelling"), None)
    us10y = next((item for item in cross if item["key"] == "us10y"), None)
    return [
        {"key": "price", "label": "恒生科技", "value": index.get("last"), "unit": "点", "badge": f"{index.get('changePct'):+.2f}%" if index.get("changePct") is not None else "最近收盘", "tone": "up" if (index.get("changePct") or 0) > 0 else "down" if (index.get("changePct") or 0) < 0 else "neutral", "note": f"高 {index.get('high') or '—'} / 低 {index.get('low') or '—'}", "source": index.get("source")},
        {"key": "turnover", "label": "指数口径成交额", "value": _round((index.get("turnover") or 0) / 1e8, 2) if index.get("turnover") is not None else None, "unit": "亿港元", "badge": "供应商指数口径", "tone": "neutral", "note": "与30只成分股成交额合计不是同一口径", "source": index.get("source")},
        {"key": "breadth", "label": "市场宽度", "value": f"{breadth.get('advances', 0)} / {breadth.get('declines', 0)}", "unit": "涨/跌", "badge": f"覆盖 {breadth.get('available', 0)}/{breadth.get('universe', 30)}", "tone": "up" if breadth.get("advances", 0) > breadth.get("declines", 0) else "down", "note": "30只成分股上涨与下跌数量", "source": None},
        {"key": "flow", "label": "南向资金", "value": southbound.get("value") if southbound else None, "unit": southbound.get("unit") if southbound else "亿元人民币", "badge": southbound.get("status") if southbound else "unavailable", "tone": "up" if southbound and (southbound.get("value") or 0) > 0 else "neutral", "note": southbound.get("period") if southbound else "数据不可用", "source": southbound.get("source") if southbound else None},
        {"key": "valuation", "label": "恒科 PE", "value": factsheet.get("peRatio"), "unit": "倍", "badge": factsheet.get("factsheetMonth") or "官方月度", "tone": "neutral", "note": "历史分位尚未接入；当前为恒指公司月度事实表", "source": factsheet.get("source")},
        {"key": "short", "label": "港股沽空比率", "value": short_selling.get("value") if short_selling else None, "unit": "%", "badge": short_selling.get("status") if short_selling else "Data unavailable", "tone": "down" if short_selling and (short_selling.get("value") or 0) >= 20 else "neutral", "note": short_selling.get("scope") or "午间历史口径不可回补" if short_selling else "Data unavailable", "source": short_selling.get("source") if short_selling else None},
        {"key": "technical", "label": "技术状态", "value": technical.get("state"), "unit": "", "badge": "MA20 / MA60 / MA120", "tone": "down" if technical.get("below") else "neutral", "note": "使用此前收盘日线计算", "source": None},
        {"key": "yield", "label": "美国10Y", "value": us10y.get("value") if us10y else None, "unit": "%", "badge": us10y.get("freshness") if us10y else "unavailable", "tone": "down" if us10y and (us10y.get("value") or 0) >= 4.5 else "neutral", "note": "Yahoo显示的TNX数值按收益率百分比展示", "source": us10y.get("source") if us10y else None},
    ]


def _judgment(session: str, index: dict[str, Any], breadth: dict[str, Any], events: list[dict[str, Any]], technical: dict[str, Any]) -> dict[str, Any]:
    change_pct = index.get("changePct")
    if session == "morning":
        return {"title": "盘前数据已更新，等待开盘验证", "summary": "早报使用最近完成的香港收盘、隔夜海外市场和盘前消息；当日分时与市场宽度尚未发生。", "short": "先观察开盘30分钟的价格、成交与权重股同步性。", "medium": technical.get("state", "技术数据不足"), "validation": "午报验证早报观察条件", "analysisType": "rule_based_calculation", "confidence": "medium"}
    direction = "上涨" if (change_pct or 0) > 0 else "下跌" if (change_pct or 0) < 0 else "持平"
    width = "多数成分股上涨" if breadth.get("advances", 0) >= 16 else "市场宽度不足"
    return {
        "title": f"恒科{direction} {abs(change_pct or 0):.2f}% · {width}",
        "summary": f"截至{SESSION_CUTOFFS[session]}，指数位于 {index.get('low')}–{index.get('high')} 区间，事件引擎识别 {len(events)} 个满足阈值的走势事件。",
        "short": "价格、量能、宽度和资金需要共同确认；未发现充分证据时，事件原因保持结构性或未知。",
        "medium": technical.get("state", "技术数据不足"),
        "validation": "晚报验证午间判断" if session == "midday" else "后续报告持续验证观察条件",
        "analysisType": "rule_based_calculation",
        "confidence": "medium",
    }


def build_snapshot(
    trading_date: str,
    session: str,
    shared: dict[str, Any],
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    cutoff = datetime.strptime(f"{trading_date} {SESSION_CUTOFFS[session]}", "%Y-%m-%d %H:%M").replace(tzinfo=HKT)
    bars = _bars_for_session(shared["hstechMinutes"], trading_date, session)
    minute_source = shared["hstechMinutes"][0]["source"] if shared["hstechMinutes"] else None
    index = _index_snapshot(shared["daily"], bars, trading_date, session, minute_source, shared.get("dailySource"))
    constituents = _constituent_snapshot(shared["factsheet"], shared["quotes"], shared["constituentMinutes"], trading_date, session, index.get("previousClose")) if session != "morning" else [{**member, "officialName": member["name"], "name": shared["quotes"].get(f"hk{member['code']}", {}).get("name") or member["name"], "last": None, "changePct": None, "contributionPoints": None, "contributionType": "unavailable", "weightSource": shared["factsheet"].get("source")} for member in shared["factsheet"].get("constituents", [])]
    breadth = _breadth(constituents)
    cross = []
    for series in shared["crossSeries"].values():
        snapshot = _market_snapshot(series, cutoff)
        if snapshot:
            cross.append(snapshot)
    flows = _flow_snapshot(trading_date, session, shared["southboundDaily"], shared["southboundMinutes"], shared.get("southboundDailySource"), shared.get("southboundMinuteSource"), shared.get("shortSellingByDate", {}))
    technical = _technical(shared["daily"], trading_date, index)
    start, end = news_window(trading_date, session)
    news, news_source = _safe(lambda: get_news_feed(start, end), "google_news_rss", errors, ([], None))
    event_cross = [item for item in cross if item["sessionRelationship"] == "same_session"]
    events = detect_events(bars, shared["constituentMinutes"], constituents, event_cross, news) if bars else []
    watchlist = _watchlist(index, bars, shared["daily"], trading_date, session, breadth, flows, cutoff)
    source_status: dict[str, dict[str, Any]] = {}
    for source in [shared["factsheet"].get("source"), shared.get("dailySource"), minute_source, shared.get("southboundDailySource"), shared.get("southboundMinuteSource"), news_source]:
        if source:
            source_status[source["sourceId"]] = source
    for flow in flows:
        if flow.get("source"):
            source_status[flow["source"]["sourceId"]] = flow["source"]
    for item in cross:
        source_status[item["source"]["sourceId"]] = item["source"]
    for item in watchlist:
        if item.get("source"):
            source_status[item["source"]["sourceId"]] = item["source"]
    report_errors = list(errors)
    cross_output = [{key: value for key, value in item.items() if key != "bars"} for item in cross]
    return {
        "schemaVersion": 1,
        "reportId": f"{trading_date}-{session}-v1",
        "tradingDate": trading_date,
        "session": session,
        "sessionLabel": SESSION_LABELS[session],
        "nominalTime": {"morning": "08:30", "midday": "12:30", "evening": "17:00"}[session],
        "marketCutoff": cutoff.isoformat(),
        "generatedAt": iso_now(),
        "timezone": "Asia/Hong_Kong",
        "overallStatus": "partial" if report_errors or any(metric.get("value") is None for metric in _metrics(index, breadth, flows, shared["factsheet"], technical, cross)) else "ok",
        "index": index,
        "minuteBars": bars,
        "constituents": constituents,
        "breadth": breadth,
        "crossMarkets": cross_output,
        "capitalFlows": flows,
        "news": news,
        "events": events,
        "watchlist": watchlist,
        "technical": technical,
        "judgment": _judgment(session, index, breadth, events, technical),
        "metrics": _metrics(index, breadth, flows, shared["factsheet"], technical, cross),
        "sourceStatus": list(source_status.values()),
        "sourceErrors": report_errors,
    }


def collect(trading_date: str | None, sessions: tuple[str, ...]) -> list[Path]:
    errors: list[dict[str, str]] = []
    factsheet = _safe(get_hsi_factsheet, "hsi_official_factsheet", errors, {"constituents": [], "source": None})
    daily, daily_source = _safe(get_hstech_daily, "sina_hk_index_daily", errors, ([], None))
    if not trading_date:
        if not daily:
            raise SourceError("Cannot infer trading date without HSTECH daily data")
        trading_date = daily[-1]["date"]
    hstech_minutes = _safe(lambda: get_tencent_minutes("hkHSTECH", trading_date), "tencent_finance_minute", errors, [])
    codes = [item["code"] for item in factsheet.get("constituents", [])]
    quotes = _safe(lambda: get_tencent_quotes(["hkHSTECH"] + [f"hk{code}" for code in codes]), "tencent_finance_quote", errors, {})
    constituent_minutes = get_constituent_minutes(codes, trading_date) if codes else {}
    missing_minutes = [code for code, rows in constituent_minutes.items() if not rows]
    if missing_minutes:
        errors.append({"sourceId": "tencent_finance_minute", "message": f"No minute history for {len(missing_minutes)} constituents: {', '.join(missing_minutes)}"})
    cross_series, cross_errors = get_cross_market_series(trading_date)
    errors.extend(cross_errors)
    southbound_daily, southbound_daily_source = _safe(get_southbound_history, "eastmoney_stock_connect_via_akshare", errors, ([], None))
    southbound_minutes, southbound_minute_source = _safe(get_southbound_minutes, "eastmoney_stock_connect_intraday_via_akshare", errors, ([], None))
    prior_date = next((row["date"] for row in reversed(daily) if row["date"] < trading_date), None)
    short_dates = set()
    if "morning" in sessions and prior_date:
        short_dates.add(prior_date)
    if "evening" in sessions:
        short_dates.add(trading_date)
    short_selling_by_date = {}
    for short_date in sorted(short_dates):
        result = _safe(lambda short_date=short_date: get_hkex_short_selling_daily(short_date), "hkex_official_short_selling", errors, (None, None))
        if result[0] and result[1]:
            short_selling_by_date[short_date] = {"data": result[0], "source": result[1]}
    shared = {
        "factsheet": factsheet,
        "daily": daily,
        "dailySource": daily_source,
        "hstechMinutes": hstech_minutes,
        "quotes": quotes,
        "constituentMinutes": constituent_minutes,
        "crossSeries": cross_series,
        "southboundDaily": southbound_daily,
        "southboundDailySource": southbound_daily_source,
        "southboundMinutes": southbound_minutes,
        "southboundMinuteSource": southbound_minute_source,
        "shortSellingByDate": short_selling_by_date,
    }
    report_dir = RUNTIME_ROOT / "reports" / trading_date
    report_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    snapshots = {}
    for session in sessions:
        session_errors = list(errors)
        snapshot = build_snapshot(trading_date, session, shared, session_errors)
        path = report_dir / f"{session}.json"
        _write_json_atomic(path, snapshot)
        paths.append(path)
        snapshots[session] = snapshot
    index_path, latest_path = rebuild_runtime_index()
    paths.extend([index_path, latest_path])
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect real market data and build dashboard snapshots")
    parser.add_argument("--date", help="Trading date in YYYY-MM-DD; defaults to latest HSTECH daily row")
    parser.add_argument("--session", choices=(*SESSIONS, "all"), default="all")
    args = parser.parse_args()
    sessions = SESSIONS if args.session == "all" else (args.session,)
    for path in collect(args.date, sessions):
        print(path.relative_to(PROJECT_ROOT))


if __name__ == "__main__":
    main()
