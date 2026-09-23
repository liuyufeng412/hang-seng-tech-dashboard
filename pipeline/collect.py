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
    get_hstech_daily,
    get_news_feed,
    get_official_macro_events,
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
) -> list[dict[str, Any]]:
    dated = [row for row in daily if row["date"] <= trading_date]
    prior = next((row for row in reversed(dated) if row["date"] < trading_date), None)
    current = next((row for row in dated if row["date"] == trading_date), None)
    items = []
    if session == "morning":
        if prior:
            items.extend([
                {"key": "southbound", "label": "上一交易日南向净买入", "value": prior.get("netBuy"), "unit": "亿元人民币", "period": prior["date"], "status": "latest_available", "source": daily_source},
                {"key": "southboundBuy", "label": "上一交易日南向买入额", "value": prior.get("buyTurnover"), "unit": "亿元人民币", "period": prior["date"], "status": "latest_available", "source": daily_source},
                {"key": "southboundSell", "label": "上一交易日南向卖出额", "value": prior.get("sellTurnover"), "unit": "亿元人民币", "period": prior["date"], "status": "latest_available", "source": daily_source},
            ])
        else:
            items.append({"key": "southbound", "label": "上一交易日南向净买入", "value": None, "unit": "亿元人民币", "period": "上一交易日", "status": "unavailable", "source": daily_source})
    else:
        cutoff = SESSION_CUTOFFS[session]
        intraday_rows = [row for row in intraday if row["date"] == trading_date and row["time"] <= cutoff]
        if intraday_rows:
            row = intraday_rows[-1]
            period = f"截至 {row['time']}"
            items.extend([
                {"key": "southbound", "label": "南向资金净流向", "value": _round(row["southbound"] / 10000.0, 2) if row.get("southbound") is not None else None, "unit": "亿元人民币", "period": period, "status": "delayed_estimate", "source": intraday_source},
                {"key": "southboundShanghai", "label": "港股通（沪）净流向", "value": _round(row["shanghaiRoute"] / 10000.0, 2) if row.get("shanghaiRoute") is not None else None, "unit": "亿元人民币", "period": period, "status": "delayed_estimate", "source": intraday_source},
                {"key": "southboundShenzhen", "label": "港股通（深）净流向", "value": _round(row["shenzhenRoute"] / 10000.0, 2) if row.get("shenzhenRoute") is not None else None, "unit": "亿元人民币", "period": period, "status": "delayed_estimate", "source": intraday_source},
            ])
        elif current:
            items.extend([
                {"key": "southbound", "label": "南向成交净买额", "value": current.get("netBuy"), "unit": "亿元人民币", "period": "全天", "status": "latest_available", "source": daily_source},
                {"key": "southboundBuy", "label": "南向买入成交额", "value": current.get("buyTurnover"), "unit": "亿元人民币", "period": "全天", "status": "latest_available", "source": daily_source},
                {"key": "southboundSell", "label": "南向卖出成交额", "value": current.get("sellTurnover"), "unit": "亿元人民币", "period": "全天", "status": "latest_available", "source": daily_source},
            ])
        else:
            items.append({"key": "southbound", "label": "南向资金", "value": None, "unit": "亿元人民币", "period": SESSION_LABELS[session], "status": "unavailable", "source": intraday_source or daily_source})
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
    news: list[dict[str, Any]] | None = None,
    inherited_message_items: list[dict[str, Any]] | None = None,
    official_macro_events: list[dict[str, Any]] | None = None,
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

    macro_events: list[dict[str, Any]] = []
    if MACRO_EVENTS_PATH.exists():
        configured = json.loads(MACRO_EVENTS_PATH.read_text(encoding="utf-8"))
        macro_events.extend(configured.get("events", []))
    macro_events.extend(official_macro_events or [])
    if macro_events:
        horizon = cutoff + timedelta(days=7)
        seen_macro_events: set[tuple[str, str]] = set()
        for event in macro_events:
            event_at = _parse_iso(event["eventAt"]).astimezone(HKT)
            if not (cutoff < event_at <= horizon):
                continue
            event_key = (event["name"], event_at.isoformat())
            if event_key in seen_macro_events:
                continue
            seen_macro_events.add(event_key)
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
    # 公司、行业与市场新闻只进入消息面复盘，不自动进入后续关注。
    # 后续关注只保留有明确时间节点的官方重大事件，以及可执行的价格、宽度和资金条件。
    return items


NEWS_CATALYST_TERMS = {
    "财报", "业绩", "盈利", "指引", "回购", "配股", "监管", "政策", "制裁", "调查", "获批",
    "投资", "订单", "发布", "推出", "芯片", "晶片", "ai", "人工智能", "利率", "加息", "降息",
    "美联储", "fomc", "美债", "人民币", "通胀", "cpi", "就业", "零售", "gdp", "原油", "油价",
    "关税", "地缘", "战争", "央行", "刺激", "财政",
}
NEWS_RECAP_TERMS = {
    "港股市况", "港股市況", "恒指走势", "恒指走勢", "收市", "收盘", "收盤", "高开", "高開",
    "低开", "低開", "午市", "盘中", "盤中", "曾升", "曾跌", "升逾", "跌逾", "涨超", "漲超",
    "港股收评", "港股收評", "恒生指数", "恆生指數", "小涨", "小漲", "撑市", "撐市", "领升", "領升",
    "强势回血", "強勢回血",
}
NEWS_SPECIFIC_ACTION_TERMS = {
    "财报", "財報", "业绩", "業績", "盈利", "指引", "回购", "回購", "配股", "监管", "監管",
    "政策", "制裁", "调查", "調查", "获批", "獲批", "投入", "投资", "投資", "订单", "訂單",
    "发布", "發佈", "發布", "推出", "加息", "降息", "关税", "關稅", "刺激", "财政", "財政",
}


def _news_watch_analysis(item: dict[str, Any]) -> tuple[str, str, str, str]:
    category = item.get("category") or "市场动态"
    assets = "、".join(item.get("relatedAssets") or []) or "相关资产"
    direction = item.get("impactDirection") or "待验证"
    prefix = f"初步影响方向为“{direction}”，但必须用后续市场反应验证。"
    if category == "央行 / 利率":
        return (
            prefix + "重点比较政策信息与市场原有预期，并联动观察美国10年期收益率、美元/离岸人民币、纳指和金龙指数。",
            "美债收益率与美元回落，纳指及中概股走强，恒科权重股随后获得量价确认。",
            "美债收益率与美元继续上行，成长股估值承压；若市场反应与标题方向相反，以市场定价为准。",
            "下一份报告核验利率、汇率及隔夜科技股反应，不根据单一标题追涨杀跌。",
        )
    if category == "宏观数据":
        return (
            prefix + "先比较实际值、市场预期与前值，再判断增长利好和利率压力哪一项主导定价。",
            "数据组合改善且未推高美债收益率与美元，纳指、中概股和离岸人民币同步稳定。",
            "数据引发收益率或美元明显上行，或弱数据触发衰退交易，恒科风险偏好转弱。",
            "公布后同时核验美债、美元/离岸人民币、纳指期货和金龙指数，保留实际值及市场反应。",
        )
    if category == "地缘 / 原油":
        return (
            prefix + "重点判断事件是否持续推高原油、美元和避险需求，而不是只看一次性新闻冲击。",
            "油价和避险资产回落，亚洲风险偏好恢复，恒科成交与市场宽度同步改善。",
            "油价、美元或避险需求持续上升，亚洲股市及恒科权重股出现扩散式走弱。",
            "后续报告持续跟踪Brent、美元、日韩股市及恒科开盘反应。",
        )
    if category == "政策":
        return (
            prefix + "等待官方细则、覆盖范围和执行时间，并观察受益资产是否出现持续而非脉冲式反应。",
            "官方细则强化正面逻辑，相关权重股放量跑赢恒科且同板块跟随。",
            "细则弱于预期、执行不确定，或相关资产高开回落且板块没有扩散。",
            f"核验官方原文及{assets}的相对恒科表现、成交量和板块扩散度。",
        )
    return (
        prefix + f"消息直接涉及{assets}；需要验证公司层面信息能否转化为持续盈利预期或行业主线。",
        f"{assets}后续放量跑赢恒科，相关板块同步走强，说明消息得到量价与扩散确认。",
        f"{assets}仅短暂冲高、随后回吐，或同板块没有跟随，说明消息影响有限或已被计价。",
        f"下一时点核验{assets}的相对涨跌、成交变化和同板块表现；未确认前不把报道直接写成指数涨跌原因。",
    )


def _news_watch_items(news: list[dict[str, Any]], cutoff: datetime, limit: int = 4) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_themes: set[str] = set()
    for item in sorted(
        news,
        key=lambda value: (
            value.get("sourceReliability") == "high",
            value.get("impactWeight") == "高",
            int(value.get("relevanceScore") or 0),
            value.get("publishedAt") or "",
        ),
        reverse=True,
    ):
        headline = str(item.get("headline") or "").strip()
        lowered = headline.lower()
        if not headline:
            continue
        has_catalyst = any(term in lowered for term in NEWS_CATALYST_TERMS)
        is_recap = any(term in lowered for term in NEWS_RECAP_TERMS)
        score = int(item.get("relevanceScore") or 0)
        material = item.get("impactWeight") == "高" or score >= 6
        category = item.get("category") or "市场动态"
        has_specific_action = any(term in lowered for term in NEWS_SPECIFIC_ACTION_TERMS)
        if not has_catalyst or (is_recap and not has_specific_action):
            continue
        if category == "市场动态" and not material:
            continue
        related_assets = item.get("relatedAssets") or []
        theme = f"{category}|{'/'.join(sorted(related_assets)) or re.sub(r'\\W+', '', headline)[:24]}"
        if theme in seen_themes:
            continue
        seen_themes.add(theme)
        expected, positive, negative, action = _news_watch_analysis(item)
        published_at = _parse_iso(item["publishedAt"]).astimezone(HKT)
        publisher = item.get("publisher") or "原始媒体"
        source = {
            "sourceId": f"news_watch_{item.get('eventId', 'unknown')}",
            "sourceName": publisher,
            "sourceType": item.get("sourceType") or "news_publisher",
            "sourceUrl": item.get("url"),
            "originalTimestamp": item.get("publishedAt"),
            "fetchedAt": item.get("fetchedAt") or iso_now(),
            "updateFrequency": "publisher-dependent continuous feed",
            "freshness": "latest_available",
            "reliability": item.get("sourceReliability") or "medium",
            "status": "published",
        }
        candidates.append({
            "id": f"watch-{item.get('eventId', len(candidates))}",
            "conditionType": "newsCatalyst",
            "conditionTypeLabel": "新闻催化",
            "group": "message",
            "label": headline,
            "subject": ",".join(related_assets) if related_assets else category,
            "operator": "validate",
            "threshold": 0,
            "displayValue": f"{published_at.strftime('%m月%d日 %H:%M')} · {publisher}",
            "durationMinutes": 0,
            "status": "pending",
            "triggeredAt": None,
            "expected": expected,
            "positive": positive,
            "negative": negative,
            "action": action,
            "validationResult": "等待下一时点的价格、成交、板块扩散及跨市场反应验证",
            "valueType": "news_based_analysis",
            "importance": "high" if material else "medium",
            "eventAt": None,
            "source": source,
            "selectionReason": "高相关性新闻且包含可持续验证的政策、宏观、行业或公司催化",
            "newsEventId": item.get("eventId"),
            "impactDirection": item.get("impactDirection") or "待验证",
            "generatedAt": cutoff.isoformat(),
        })
        if len(candidates) >= limit:
            break
    return candidates


def _prior_report_path(trading_date: str, session: str, runtime_root: Path = RUNTIME_ROOT) -> Path | None:
    report_root = runtime_root / "reports"
    same_date = report_root / trading_date
    if session == "midday" and (same_date / "morning.json").is_file():
        return same_date / "morning.json"
    if session == "evening":
        for prior_session in ("midday", "morning"):
            candidate = same_date / f"{prior_session}.json"
            if candidate.is_file():
                return candidate
    prior_dates = sorted(
        (path for path in report_root.iterdir() if path.is_dir() and DATE_PATTERN.match(path.name) and path.name < trading_date),
        key=lambda path: path.name,
        reverse=True,
    ) if report_root.exists() else []
    for date_path in prior_dates:
        for prior_session in ("evening", "midday", "morning"):
            candidate = date_path / f"{prior_session}.json"
            if candidate.is_file():
                return candidate
    return None


def _inherited_message_watchlist(
    trading_date: str,
    session: str,
    cutoff: datetime,
    runtime_root: Path = RUNTIME_ROOT,
) -> list[dict[str, Any]]:
    prior_path = _prior_report_path(trading_date, session, runtime_root)
    if not prior_path:
        return []
    try:
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    inherited: list[dict[str, Any]] = []
    for item in prior.get("watchlist", []):
        if item.get("group") != "message" or item.get("conditionType") != "newsCatalyst":
            continue
        published_value = (item.get("source") or {}).get("originalTimestamp")
        if not published_value:
            continue
        published_at = _parse_iso(published_value).astimezone(HKT)
        if cutoff - published_at > timedelta(hours=36) or cutoff < published_at:
            continue
        carried = dict(item)
        carried["status"] = "pending"
        carried["triggeredAt"] = None
        carried["validationResult"] = (
            f"承接自 {prior.get('tradingDate', prior_path.parent.name)} {SESSION_LABELS.get(prior.get('session'), '上一份报告')}；"
            "等待当前时点的量价、板块扩散及跨市场反应验证"
        )
        carried["selectionReason"] = "上一份报告尚未完成验证的高重要性消息"
        carried["inheritedFromReportId"] = prior.get("reportId")
        inherited.append(carried)
    return inherited[:4]


def _load_prior_snapshot(trading_date: str, session: str, runtime_root: Path = RUNTIME_ROOT) -> dict[str, Any] | None:
    path = _prior_report_path(trading_date, session, runtime_root)
    if not path:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _scaled_component(value: float | None, weight: float, scale: float, inverse: bool = False) -> float:
    if value is None:
        return weight / 2
    signed = -value if inverse else value
    return weight * _clamp(0.5 + signed / (2 * scale), 0, 1)


def _average_true_range(daily: list[dict[str, Any]], trading_date: str, periods: int = 14) -> float | None:
    rows = [row for row in daily if row["date"] < trading_date and all(row.get(key) is not None for key in ("high", "low", "close"))]
    if len(rows) < 2:
        return None
    ranges = []
    for previous, current in zip(rows[-(periods + 1):-1], rows[-periods:]):
        ranges.append(max(
            float(current["high"]) - float(current["low"]),
            abs(float(current["high"]) - float(previous["close"])),
            abs(float(current["low"]) - float(previous["close"])),
        ))
    return sum(ranges) / len(ranges) if ranges else None


def _target_point(
    last: float,
    desired: float,
    levels: list[tuple[float, str]],
    atr: float,
    direction: int,
) -> tuple[float, str]:
    eligible = [(value, label) for value, label in levels if (value - last) * direction > atr * 0.08]
    if not eligible:
        return desired, "波动率投射"
    nearest = min(eligible, key=lambda item: abs(item[0] - desired))
    if abs(nearest[0] - desired) <= atr * 0.65:
        return nearest
    return desired, "波动率投射"


def _score_card(
    index: dict[str, Any],
    daily: list[dict[str, Any]],
    trading_date: str,
    session: str,
    breadth: dict[str, Any],
    constituents: list[dict[str, Any]],
    flows: list[dict[str, Any]],
    cross: list[dict[str, Any]],
    factsheet: dict[str, Any],
    technical: dict[str, Any],
    watchlist: list[dict[str, Any]],
    prior_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    last = float(index.get("last") or 0)
    if last <= 0:
        return {"status": "unavailable", "reason": "恒科指数点位不可用"}
    history = [row for row in daily if row["date"] < trading_date and row.get("close") is not None]
    closes = [float(row["close"]) for row in history]
    ma = technical.get("movingAverages", {})
    dimensions: list[dict[str, Any]] = []

    trend_parts = []
    for key, weight, scale in (("ma5", 3, 4), ("ma20", 5, 6), ("ma60", 6, 10), ("ma120", 6, 15)):
        average = ma.get(key)
        distance = _pct(float(average), last) if average else None
        trend_parts.append(_scaled_component(distance, weight, scale))
    trend_score = sum(trend_parts)
    dimensions.append({"key": "trend", "label": "趋势结构", "score": _round(trend_score, 1), "weight": 20, "reason": technical.get("state", "均线数据不足"), "status": "calculated"})

    return_5 = _pct(closes[-5], last) if len(closes) >= 5 else None
    return_20 = _pct(closes[-20], last) if len(closes) >= 20 else None
    intraday_return = index.get("changePct")
    momentum_score = (
        _scaled_component(return_5, 6, 8)
        + _scaled_component(return_20, 6, 15)
        + _scaled_component(float(intraday_return) if intraday_return is not None else None, 3, 3)
    )
    dimensions.append({"key": "momentum", "label": "技术动量", "score": _round(momentum_score, 1), "weight": 15, "reason": f"近5日 {return_5:+.2f}% / 近20日 {return_20:+.2f}%" if return_5 is not None and return_20 is not None else "历史动量数据不足", "status": "calculated"})

    latest_daily = history[-1] if history else None
    recent_turnovers = [float(row["turnover"]) for row in history[-21:-1] if row.get("turnover")]
    turnover_ratio = None
    price_signal = index.get("changePct")
    if session == "morning" and len(history) >= 2:
        price_signal = _pct(float(history[-2]["close"]), float(history[-1]["close"]))
    if latest_daily and latest_daily.get("turnover") and recent_turnovers:
        turnover_ratio = float(latest_daily["turnover"]) / (sum(recent_turnovers) / len(recent_turnovers))
    price_value = float(price_signal or 0)
    volume_score = 7.5 + _clamp(price_value * 1.5, -4.5, 4.5)
    if turnover_ratio is not None:
        volume_score += _clamp((turnover_ratio - 1) * 3, -2, 2) * (1 if price_value >= 0 else -1)
    volume_score = _clamp(volume_score, 0, 15)
    dimensions.append({"key": "volumePrice", "label": "量价配合", "score": _round(volume_score, 1), "weight": 15, "reason": f"价格 {price_value:+.2f}% / 成交为20日均值 {turnover_ratio:.2f} 倍" if turnover_ratio is not None else "成交基准不足，按中性处理", "status": "calculated" if turnover_ratio is not None else "neutral_assumption"})

    effective_breadth = breadth
    breadth_status = "calculated"
    if int(breadth.get("available", 0) or 0) < 24 and prior_snapshot:
        prior_breadth = prior_snapshot.get("breadth", {})
        if int(prior_breadth.get("available", 0) or 0) >= 24:
            effective_breadth = prior_breadth
            breadth_status = "carried"
    available = int(effective_breadth.get("available", 0) or 0)
    suspicious_flat_breadth = available >= 24 and int(effective_breadth.get("unchanged", 0) or 0) == available
    breadth_score = 5 if suspicious_flat_breadth else (float(effective_breadth.get("advances", 0)) / available * 10) if available else 5
    breadth_reason = "成分股历史涨跌基准不可可靠回溯，按中性处理" if suspicious_flat_breadth else f"{effective_breadth.get('advances', 0)}涨 / {effective_breadth.get('declines', 0)}跌" + ("（承接上一期）" if breadth_status == "carried" else "")
    dimensions.append({"key": "breadth", "label": "市场宽度", "score": _round(breadth_score, 1), "weight": 10, "reason": breadth_reason, "status": "neutral_assumption" if suspicious_flat_breadth or not available else breadth_status})

    effective_constituents = [item for item in constituents if item.get("changePct") is not None]
    constituent_status = "calculated"
    if len(effective_constituents) < 24 and prior_snapshot:
        prior_constituents = [item for item in prior_snapshot.get("constituents", []) if item.get("changePct") is not None]
        if len(prior_constituents) >= 24:
            effective_constituents = prior_constituents
            constituent_status = "carried"
    total_weight = sum(float(item.get("weight") or 0) for item in effective_constituents)
    weighted_return = sum(float(item.get("weight") or 0) * float(item.get("changePct") or 0) for item in effective_constituents) / total_weight if total_weight else None
    if weighted_return == 0 and effective_constituents and all(float(item.get("changePct") or 0) == 0 for item in effective_constituents):
        constituent_status = "neutral_assumption"
    constituent_score = _scaled_component(weighted_return, 10, 3)
    constituent_reason = "成分股历史昨收基准不可可靠回溯，按中性处理" if constituent_status == "neutral_assumption" else f"权重加权涨跌 {weighted_return:+.2f}%" + ("（承接上一期）" if constituent_status == "carried" else "") if weighted_return is not None else "成分股覆盖不足，按中性处理"
    dimensions.append({"key": "constituents", "label": "成分股结构", "score": _round(constituent_score, 1), "weight": 10, "reason": constituent_reason, "status": constituent_status if weighted_return is not None else "neutral_assumption"})

    southbound = next((item for item in flows if item.get("key") == "southbound"), None)
    southbound_value = float(southbound["value"]) if southbound and southbound.get("value") is not None else None
    capital_score = 5 + _clamp((southbound_value or 0) / 25, -5, 5) if southbound_value is not None else 5
    dimensions.append({"key": "capital", "label": "资金承接", "score": _round(capital_score, 1), "weight": 10, "reason": f"南向净流向 {southbound_value:+.2f} 亿元" if southbound_value is not None else "可靠资金数据不足，按中性处理", "status": "observed" if southbound_value is not None else "neutral_assumption"})

    cross_map = {item["key"]: item for item in cross}
    cross_specs = (("hxc", 2.5, 2, False), ("ndx", 1.5, 2, False), ("nasdaq", 1, 2, False), ("us10y", 1.5, 2, True), ("usdcnh", 1.5, 0.6, True), ("kospi", 1, 2, False), ("brent", 1, 4, True))
    cross_score = 0.0
    cross_available = 0
    for key, weight, scale, inverse in cross_specs:
        value = cross_map.get(key, {}).get("changePct")
        cross_score += _scaled_component(float(value) if value is not None else None, weight, scale, inverse)
        cross_available += int(value is not None)
    dimensions.append({"key": "crossMarket", "label": "跨市场环境", "score": _round(cross_score, 1), "weight": 10, "reason": f"关键指标覆盖 {cross_available}/{len(cross_specs)}；权益正向、利率/美元/原油反向计分", "status": "calculated" if cross_available >= 5 else "partial"})

    pe_ratio = factsheet.get("peRatio")
    valuation_score = 2.5
    dimensions.append({"key": "valuation", "label": "估值位置", "score": valuation_score, "weight": 5, "reason": f"PE {pe_ratio:.2f} 倍；历史分位未接入，暂按中性" if pe_ratio is not None else "可靠估值数据不足，按中性处理", "status": "neutral_assumption"})

    upcoming = [item for item in watchlist if item.get("conditionType") == "macroEvent"]
    critical_count = sum(item.get("importance") == "critical" for item in upcoming)
    event_score = _clamp(3.5 - critical_count * 1.25 - max(0, len(upcoming) - critical_count - 1) * 0.35, 0.5, 4.5)
    dimensions.append({"key": "eventRisk", "label": "消息与事件风险", "score": _round(event_score, 1), "weight": 5, "reason": f"未来7天 {len(upcoming)} 项高优先级官方事件，重大事件越近风险分越低", "status": "calculated"})

    total = _round(sum(float(item["score"]) for item in dimensions), 1)
    prior_score = (prior_snapshot or {}).get("scoreCard", {}).get("total")
    delta = _round(total - float(prior_score), 1) if prior_score is not None else None
    movement = "up" if delta is not None and delta > 0.05 else "down" if delta is not None and delta < -0.05 else "flat" if delta is not None else "baseline"
    label = "强势" if total >= 70 else "偏强" if total >= 58 else "中性偏强" if total >= 53 else "中性" if total >= 47 else "中性偏弱" if total >= 42 else "偏弱" if total >= 32 else "弱势"
    bias = _clamp((total - 50) / 15, -1, 1)
    atr = _average_true_range(daily, trading_date) or last * 0.02
    complete_rows = [row for row in daily if row["date"] < trading_date and row.get("high") is not None and row.get("low") is not None]
    resistance_levels = [(float(value), label_name) for value, label_name in [
        (ma.get("ma20"), "MA20"), (ma.get("ma60"), "MA60"), (ma.get("ma120"), "MA120"),
        (max((float(row["high"]) for row in complete_rows[-5:]), default=None), "近5日高点"),
        (max((float(row["high"]) for row in complete_rows[-20:]), default=None), "近20日高点"),
    ] if value is not None]
    support_levels = [(float(value), label_name) for value, label_name in [
        (ma.get("ma5"), "MA5"), (ma.get("ma20"), "MA20"),
        (min((float(row["low"]) for row in complete_rows[-5:]), default=None), "近5日低点"),
        (min((float(row["low"]) for row in complete_rows[-20:]), default=None), "近20日低点"),
        (min((float(row["low"]) for row in complete_rows[-60:]), default=None), "近60日低点"),
    ] if value is not None]
    direction = 1 if bias >= 0.2 else -1 if bias <= -0.2 else (1 if bias >= 0 else -1)
    level_candidates = resistance_levels if direction > 0 else support_levels
    multipliers = (max(0.3, abs(bias) * 0.8), max(0.8, abs(bias) * 2.0), max(1.5, abs(bias) * 4.0))
    widths = (0.08, 0.13, 0.2)
    horizons = ("1–5个交易日", "1–3个月", "6–12个月")
    names = ("short", "medium", "long")
    targets: dict[str, Any] = {}
    invalidation_factors = (0.65, 1.0, 1.5)
    previous_target: float | None = None
    for name, multiplier, width_factor, invalidation_factor, horizon in zip(names, multipliers, widths, invalidation_factors, horizons):
        desired = last + direction * atr * multiplier
        eligible_levels = level_candidates
        if previous_target is not None:
            eligible_levels = [item for item in level_candidates if (item[0] - previous_target) * direction > atr * 0.35]
        point, level_basis = _target_point(last, desired, eligible_levels, atr, direction)
        if previous_target is not None and (point - previous_target) * direction <= atr * 0.35:
            point = previous_target + direction * atr * 0.6
            level_basis = "波动率递进投射"
        previous_target = point
        half_width = max(5.0, atr * width_factor)
        targets[name] = {
            "point": _round(point, 0),
            "rangeLow": _round(point - half_width, 0),
            "rangeHigh": _round(point + half_width, 0),
            "horizon": horizon,
            "direction": "up" if point > last else "down" if point < last else "flat",
            "basis": f"{level_basis} + 14日平均真实波幅 {atr:.0f} 点",
            "invalidation": _round(last - direction * atr * invalidation_factor, 0),
        }

    observed_weight = sum(float(item["weight"]) for item in dimensions if item["status"] not in {"neutral_assumption", "partial"})
    confidence = _round(observed_weight, 0)
    judgment = (
        f"综合评分 {total:.1f}，结构{label}。"
        + ("目标重心位于当前点位上方，但需要量价、宽度和资金共同确认。" if direction > 0 else "目标重心位于当前点位下方，反弹未改变弱势前仍以风险控制为主。")
    )
    return {
        "status": "calculated",
        "total": total,
        "label": label,
        "previousTotal": prior_score,
        "delta": delta,
        "movement": movement,
        "confidence": confidence,
        "asOf": index.get("timestamp"),
        "judgment": judgment,
        "dimensions": dimensions,
        "targets": targets,
        "methodology": "九维加权模型；目标点优先贴近均线与近期高低点，并以14日平均真实波幅生成窄幅容许区间。",
        "valueType": "rule_based_calculation",
    }


def _metrics(index: dict[str, Any], breadth: dict[str, Any], flows: list[dict[str, Any]], factsheet: dict[str, Any], technical: dict[str, Any], cross: list[dict[str, Any]]) -> list[dict[str, Any]]:
    southbound = next((item for item in flows if item["key"] == "southbound"), None)
    return [
        {"key": "price", "label": "恒生科技", "value": index.get("last"), "unit": "点", "badge": f"{index.get('changePct'):+.2f}%" if index.get("changePct") is not None else "最近收盘", "tone": "up" if (index.get("changePct") or 0) > 0 else "down" if (index.get("changePct") or 0) < 0 else "neutral", "note": f"高 {index.get('high') or '—'} / 低 {index.get('low') or '—'}", "source": index.get("source")},
        {"key": "turnover", "label": "指数口径成交额", "value": _round((index.get("turnover") or 0) / 1e8, 2) if index.get("turnover") is not None else None, "unit": "亿港元", "badge": "供应商指数口径", "tone": "neutral", "note": "与30只成分股成交额合计不是同一口径", "source": index.get("source")},
        {"key": "breadth", "label": "市场宽度", "value": f"{breadth.get('advances', 0)} / {breadth.get('declines', 0)}", "unit": "涨/跌", "badge": f"覆盖 {breadth.get('available', 0)}/{breadth.get('universe', 30)}", "tone": "up" if breadth.get("advances", 0) > breadth.get("declines", 0) else "down", "note": "30只成分股上涨与下跌数量", "source": None},
        {"key": "flow", "label": "南向资金", "value": southbound.get("value") if southbound else None, "unit": southbound.get("unit") if southbound else "亿元人民币", "badge": southbound.get("status") if southbound else "unavailable", "tone": "up" if southbound and (southbound.get("value") or 0) > 0 else "neutral", "note": southbound.get("period") if southbound else "数据不可用", "source": southbound.get("source") if southbound else None},
        {"key": "valuation", "label": "恒科 PE", "value": factsheet.get("peRatio"), "unit": "倍", "badge": factsheet.get("factsheetMonth") or "官方月度", "tone": "neutral", "note": "历史分位尚未接入；当前为恒指公司月度事实表", "source": factsheet.get("source")},
        {"key": "technical", "label": "技术状态", "value": technical.get("state"), "unit": "", "badge": "MA20 / MA60 / MA120", "tone": "down" if technical.get("below") else "neutral", "note": "使用此前收盘日线计算", "source": None},
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
    flows = _flow_snapshot(trading_date, session, shared["southboundDaily"], shared["southboundMinutes"], shared.get("southboundDailySource"), shared.get("southboundMinuteSource"))
    technical = _technical(shared["daily"], trading_date, index)
    start, end = news_window(trading_date, session)
    news, news_source = _safe(lambda: get_news_feed(start, end), "google_news_rss", errors, ([], None))
    event_cross = [item for item in cross if item["sessionRelationship"] == "same_session"]
    events = detect_events(bars, shared["constituentMinutes"], constituents, event_cross, news) if bars else []
    prior_snapshot = _load_prior_snapshot(trading_date, session)
    inherited_messages = _inherited_message_watchlist(trading_date, session, cutoff)
    watchlist = _watchlist(
        index,
        bars,
        shared["daily"],
        trading_date,
        session,
        breadth,
        flows,
        cutoff,
        news,
        inherited_messages,
        shared.get("officialMacroEvents", []),
    )
    score_card = _score_card(
        index,
        shared["daily"],
        trading_date,
        session,
        breadth,
        constituents,
        flows,
        cross,
        shared["factsheet"],
        technical,
        watchlist,
        prior_snapshot,
    )
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
        "scoreCard": score_card,
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
    needs_intraday = any(session != "morning" for session in sessions)
    hstech_minutes = _safe(lambda: get_tencent_minutes("hkHSTECH", trading_date), "tencent_finance_minute", errors, []) if needs_intraday else []
    codes = [item["code"] for item in factsheet.get("constituents", [])]
    quotes = _safe(lambda: get_tencent_quotes(["hkHSTECH"] + [f"hk{code}" for code in codes]), "tencent_finance_quote", errors, {})
    constituent_minutes = get_constituent_minutes(codes, trading_date) if codes and needs_intraday else {code: [] for code in codes}
    missing_minutes = [code for code, rows in constituent_minutes.items() if not rows] if needs_intraday else []
    if missing_minutes:
        errors.append({"sourceId": "tencent_finance_minute", "message": f"No minute history for {len(missing_minutes)} constituents: {', '.join(missing_minutes)}"})
    cross_series, cross_errors = get_cross_market_series(trading_date)
    errors.extend(cross_errors)
    southbound_daily, southbound_daily_source = _safe(get_southbound_history, "eastmoney_stock_connect_via_akshare", errors, ([], None))
    southbound_minutes, southbound_minute_source = _safe(get_southbound_minutes, "eastmoney_stock_connect_intraday_via_akshare", errors, ([], None))
    calendar_start = datetime.strptime(trading_date, "%Y-%m-%d").replace(tzinfo=HKT)
    official_macro_events, calendar_errors = get_official_macro_events(calendar_start, calendar_start + timedelta(days=8))
    errors.extend(calendar_errors)
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
        "officialMacroEvents": official_macro_events,
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
