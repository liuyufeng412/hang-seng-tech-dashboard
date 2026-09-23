from __future__ import annotations

import html
import hashlib
import io
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import feedparser
import pandas as pd
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

HKT = ZoneInfo("Asia/Hong_Kong")
ET = ZoneInfo("America/New_York")
UTC = timezone.utc
USER_AGENT = "HangSengTechDashboard/0.2 research-workbench"
HTTP_HEADERS = {"User-Agent": USER_AGENT}
TENCENT_HEADERS = {"User-Agent": USER_AGENT, "Referer": "https://gu.qq.com/"}


class SourceError(RuntimeError):
    pass


def iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _float(value: Any) -> float | None:
    try:
        number = float(value)
        return None if pd.isna(number) else number
    except (TypeError, ValueError):
        return None


def _source(
    source_id: str,
    name: str,
    source_type: str,
    url: str,
    original_timestamp: str | None,
    update_frequency: str,
    freshness: str,
    reliability: str,
    fetched_at: str,
) -> dict[str, Any]:
    return {
        "sourceId": source_id,
        "sourceName": name,
        "sourceType": source_type,
        "sourceUrl": url,
        "originalTimestamp": original_timestamp,
        "fetchedAt": fetched_at,
        "updateFrequency": update_frequency,
        "freshness": freshness,
        "reliability": reliability,
        "status": "ok",
    }


def get_hsi_factsheet() -> dict[str, Any]:
    fetched_at = iso_now()
    url = "https://www.hsi.com.hk/static/uploads/contents/en/dl_centre/factsheets/hsteche.pdf"
    response = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    response.raise_for_status()
    text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(response.content)).pages
    )
    factsheet_month = re.search(r"Hang Seng TECH Index\s+([A-Za-z]+ \d{4})", text)
    data_date = re.search(r"All data as at (\d{1,2} [A-Za-z]+ \d{4})", text)
    pe_match = re.search(r"HSTECH\s+[\d.]+\s+([\d.]+)\s+[\d.]+\s+[\d.]+\s+[\d.]+", text)
    constituent_block = text.split("CONSTITUENTS", 1)[-1].split("Total 100.00", 1)[0]
    industries = (
        "Information Technology|Consumer Discretionary|Healthcare|Industrials|Financials"
    )
    pattern = re.compile(
        rf"^(\d{{4}})\s+([A-Z0-9]+)\s+(.+?)\s+({industries})\s+(.+?)\s+([\d.]+)$",
        re.MULTILINE,
    )
    constituents = []
    for match in pattern.finditer(constituent_block):
        code, isin, name, industry, share_type, weight = match.groups()
        constituents.append(
            {
                "code": code.zfill(5),
                "name": name.strip(),
                "isin": isin,
                "industry": industry,
                "shareType": share_type.strip(),
                "weight": float(weight),
            }
        )
    if len(constituents) != 30:
        raise SourceError(f"HSI factsheet returned {len(constituents)} constituents, expected 30")
    original_date = None
    if data_date:
        original_date = datetime.strptime(data_date.group(1), "%d %b %Y").replace(tzinfo=HKT).isoformat()
    source = _source(
        "hsi_official_factsheet",
        "Hang Seng Indexes Company",
        "official_index_company",
        url,
        original_date,
        "monthly; constituent review quarterly",
        "latest_available",
        "official",
        fetched_at,
    )
    return {
        "constituents": constituents,
        "peRatio": _float(pe_match.group(1)) if pe_match else None,
        "factsheetMonth": factsheet_month.group(1) if factsheet_month else None,
        "dataDate": original_date,
        "source": source,
    }


def _decode_tencent_quote_line(line: str, fetched_at: str) -> tuple[str, dict[str, Any]] | None:
    match = re.search(r"v_(\w+)=\"(.*)\";", line)
    if not match:
        return None
    key, raw = match.groups()
    fields = raw.split("~")
    if len(fields) < 47:
        return None
    observed = None
    try:
        observed = datetime.strptime(fields[30], "%Y/%m/%d %H:%M:%S").replace(tzinfo=HKT).isoformat()
    except (ValueError, IndexError):
        pass
    quote = {
        "code": fields[2],
        "name": fields[1],
        "last": _float(fields[3]),
        "previousClose": _float(fields[4]),
        "open": _float(fields[5]),
        "volume": _float(fields[6]),
        "change": _float(fields[31]),
        "changePct": _float(fields[32]),
        "high": _float(fields[33]),
        "low": _float(fields[34]),
        "turnover": _float(fields[37]),
        "timestamp": observed,
        "englishName": fields[46],
        "source": _source(
            "tencent_finance_quote",
            "Tencent Finance",
            "public_financial_vendor",
            "https://qt.gtimg.cn/",
            observed,
            "vendor snapshot; observed endpoint refreshes during market hours",
            "delayed",
            "high",
            fetched_at,
        ),
    }
    return key, quote


def get_tencent_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    fetched_at = iso_now()
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    response = requests.get(url, headers=TENCENT_HEADERS, timeout=20)
    response.raise_for_status()
    text = response.content.decode("gbk", errors="ignore")
    result: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        parsed = _decode_tencent_quote_line(line, fetched_at)
        if parsed:
            key, quote = parsed
            result[key] = quote
    if not result:
        raise SourceError("Tencent quote endpoint returned no parseable quotes")
    return result


def get_tencent_minutes(symbol: str, trading_date: str) -> list[dict[str, Any]]:
    fetched_at = iso_now()
    url = f"https://web.ifzq.gtimg.cn/appstock/app/day/query?code={symbol}"
    response = requests.get(url, headers=TENCENT_HEADERS, timeout=20)
    response.raise_for_status()
    payload = response.json()
    records = payload.get("data", {}).get(symbol, {}).get("data", [])
    selected = next((item for item in records if item.get("date") == trading_date.replace("-", "")), None)
    if not selected:
        raise SourceError(f"No minute data for {symbol} on {trading_date}")
    source = _source(
        "tencent_finance_minute",
        "Tencent Finance",
        "public_financial_vendor",
        url,
        f"{trading_date}T16:10:00+08:00",
        "approximately 1 minute during market hours",
        "delayed",
        "high",
        fetched_at,
    )
    bars: list[dict[str, Any]] = []
    previous_volume = 0.0
    previous_turnover = 0.0
    for raw in selected.get("data", []):
        parts = raw.split()
        if len(parts) < 4:
            continue
        hhmm, price, cumulative_volume, cumulative_turnover = parts[:4]
        cv = float(cumulative_volume)
        ct = float(cumulative_turnover)
        timestamp = datetime.strptime(f"{trading_date} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=HKT)
        bars.append(
            {
                "timestamp": timestamp.isoformat(),
                "time": timestamp.strftime("%H:%M"),
                "close": float(price),
                "volume": max(0.0, cv - previous_volume),
                "turnover": max(0.0, ct - previous_turnover),
                "cumulativeVolume": cv,
                "cumulativeTurnover": ct,
                "source": source,
            }
        )
        previous_volume, previous_turnover = cv, ct
    return bars


def get_constituent_minutes(codes: list[str], trading_date: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(get_tencent_minutes, f"hk{code}", trading_date): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                result[code] = future.result()
            except Exception:
                result[code] = []
    return result


def get_hstech_daily() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fetched_at = iso_now()
    frame = ak.stock_hk_index_daily_sina(symbol="HSTECH")
    source = _source(
        "sina_hk_index_daily",
        "Sina Finance",
        "public_financial_vendor",
        "https://stock.finance.sina.com.cn/hkstock/quotes/HSTECH.html",
        str(frame.iloc[-1]["date"]) if not frame.empty else None,
        "end of day",
        "latest_available",
        "high",
        fetched_at,
    )
    rows = []
    for _, row in frame.tail(260).iterrows():
        rows.append(
            {
                "date": str(row["date"]),
                "open": _float(row["open"]),
                "high": _float(row["high"]),
                "low": _float(row["low"]),
                "close": _float(row["close"]),
                "volume": _float(row["volume"]),
                "turnover": _float(row.get("amount")),
            }
        )
    return rows, source


YAHOO_SYMBOLS = {
    "hsi": ("^HSI", "恒生指数", "Asia/Hong_Kong", "same_session"),
    "hscei": ("^HSCE", "恒生国企指数", "Asia/Hong_Kong", "same_session"),
    "sse": ("000001.SS", "上证指数", "Asia/Shanghai", "same_session"),
    "szse": ("399001.SZ", "深证成指", "Asia/Shanghai", "same_session"),
    "chinext": ("399006.SZ", "创业板", "Asia/Shanghai", "same_session"),
    "star50": ("000688.SS", "科创50", "Asia/Shanghai", "same_session"),
    "nikkei": ("^N225", "日经225", "Asia/Tokyo", "same_session"),
    "kospi": ("^KS11", "KOSPI", "Asia/Seoul", "same_session"),
    "nasdaq": ("^IXIC", "纳斯达克", "America/New_York", "overnight"),
    "ndx": ("^NDX", "纳斯达克100", "America/New_York", "overnight"),
    "sox": ("^SOX", "费城半导体", "America/New_York", "overnight"),
    "hxc": ("^HXC", "纳斯达克金龙中国", "America/New_York", "overnight"),
    "usdcnh": ("CNH=X", "USD/CNH", "UTC", "continuous"),
    "us10y": ("^TNX", "美国10年期国债收益率", "America/New_York", "overnight"),
    "brent": ("BZ=F", "Brent原油", "America/New_York", "continuous"),
}

TENCENT_CROSS_FALLBACKS = {
    "hsi": ("hkHSI", "恒生指数", "Asia/Hong_Kong", "same_session"),
    "hscei": ("hkHSCEI", "恒生国企指数", "Asia/Hong_Kong", "same_session"),
    "sse": ("sh000001", "上证指数", "Asia/Shanghai", "same_session"),
    "szse": ("sz399001", "深证成指", "Asia/Shanghai", "same_session"),
    "chinext": ("sz399006", "创业板", "Asia/Shanghai", "same_session"),
    "star50": ("sh000688", "科创50", "Asia/Shanghai", "same_session"),
}


def _fetch_yahoo_series(item: tuple[str, tuple[str, str, str, str]]) -> tuple[str, dict[str, Any]]:
    key, (symbol, name, exchange_tz, relationship) = item
    fetched_at = iso_now()
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=60d&interval=5m"
    response = requests.get(url, headers=HTTP_HEADERS, timeout=20)
    response.raise_for_status()
    result = (response.json().get("chart", {}).get("result") or [None])[0]
    if not result:
        raise SourceError(f"Yahoo returned no data for {symbol}")
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    rows = []
    for index, stamp in enumerate(timestamps):
        close = (quote.get("close") or [None] * len(timestamps))[index]
        if close is None:
            continue
        rows.append(
            {
                "timestamp": datetime.fromtimestamp(stamp, UTC).isoformat().replace("+00:00", "Z"),
                "close": float(close),
                "volume": _float((quote.get("volume") or [None] * len(timestamps))[index]),
            }
        )
    return key, {
        "key": key,
        "symbol": symbol,
        "name": name,
        "exchangeTimezone": exchange_tz,
        "sessionRelationship": relationship,
        "bars": rows,
        "source": _source(
            "yahoo_finance_chart",
            "Yahoo Finance",
            "public_financial_vendor",
            url,
            rows[-1]["timestamp"] if rows else None,
            "vendor-defined; typically delayed",
            "delayed",
            "medium",
            fetched_at,
        ),
    }


def _fetch_tencent_cross_series(item: tuple[str, tuple[str, str, str, str]], trading_date: str) -> tuple[str, dict[str, Any]]:
    key, (symbol, name, exchange_tz, relationship) = item
    current = get_tencent_minutes(symbol, trading_date)
    prior: list[dict[str, Any]] = []
    cursor = datetime.strptime(trading_date, "%Y-%m-%d").date() - timedelta(days=1)
    for _ in range(7):
        try:
            prior = get_tencent_minutes(symbol, cursor.isoformat())
            if prior:
                break
        except Exception:
            pass
        cursor -= timedelta(days=1)
    if not current or not prior:
        raise SourceError(f"Tencent fallback lacks two sessions for {symbol}")
    source = current[-1]["source"]
    source = {
        **source,
        "sourceId": "tencent_finance_cross_market_fallback",
        "status": "fallback_after_primary_source_error",
    }
    bars = [{"timestamp": bar["timestamp"], "close": bar["close"], "volume": bar["volume"]} for bar in prior + current]
    return key, {
        "key": key,
        "symbol": symbol,
        "name": name,
        "exchangeTimezone": exchange_tz,
        "sessionRelationship": relationship,
        "bars": bars,
        "source": source,
    }


def get_cross_market_series(trading_date: str | None = None) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    result: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_yahoo_series, item): item[0] for item in YAHOO_SYMBOLS.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                result_key, data = future.result()
                result[result_key] = data
            except Exception as exc:
                errors.append({"sourceId": "yahoo_finance_chart", "instrument": key, "message": str(exc)})
    if trading_date:
        fallback_items = [(key, value) for key, value in TENCENT_CROSS_FALLBACKS.items() if key not in result]
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_fetch_tencent_cross_series, item, trading_date): item[0] for item in fallback_items}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    result_key, data = future.result()
                    result[result_key] = data
                except Exception as exc:
                    errors.append({"sourceId": "tencent_finance_cross_market_fallback", "instrument": key, "message": str(exc)})
        errors = [error for error in errors if error.get("instrument") not in result]
    return result, errors


def get_southbound_history() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fetched_at = iso_now()
    frame = ak.stock_hsgt_hist_em(symbol="南向资金")
    source = _source(
        "eastmoney_stock_connect_via_akshare",
        "Eastmoney via AKShare",
        "public_financial_vendor",
        "https://data.eastmoney.com/hsgt/index.html",
        str(frame.iloc[-1]["日期"]) if not frame.empty else None,
        "intraday vendor updates; daily final after close",
        "delayed",
        "medium",
        fetched_at,
    )
    rows = []
    for _, row in frame.tail(60).iterrows():
        rows.append(
            {
                "date": str(row["日期"]),
                "netBuy": _float(row["当日成交净买额"]),
                "buyTurnover": _float(row["买入成交额"]),
                "sellTurnover": _float(row["卖出成交额"]),
                "unit": "亿元人民币",
            }
        )
    return rows, source


def get_southbound_minutes() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fetched_at = iso_now()
    frame = ak.stock_hsgt_fund_min_em(symbol="南向资金")
    source = _source(
        "eastmoney_stock_connect_intraday_via_akshare",
        "Eastmoney via AKShare",
        "public_financial_vendor",
        "https://data.eastmoney.com/hsgt/hsgtDetail/scgk.html",
        f"{frame.iloc[-1]['日期']}T{frame.iloc[-1]['时间']}:00+08:00" if not frame.empty else None,
        "vendor intraday estimate",
        "delayed",
        "medium",
        fetched_at,
    )
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "date": str(row["日期"]),
                "time": str(row["时间"]),
                "shanghaiRoute": _float(row["港股通(沪)"]),
                "shenzhenRoute": _float(row["港股通(深)"]),
                "southbound": _float(row["南向资金"]),
                "unit": "万元人民币",
            }
        )
    return rows, source


def get_hkex_short_selling_daily(trading_date: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fetched_at = iso_now()
    compact_date = datetime.strptime(trading_date, "%Y-%m-%d").strftime("%y%m%d")
    url = f"https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{compact_date}e.htm"
    response = requests.get(url, headers=HTTP_HEADERS, timeout=45)
    response.raise_for_status()
    text = html.unescape(re.sub(r"<[^>]+>", " ", response.text))
    section_start = text.rfind("SHORT SELLING TURNOVER - DAILY REPORT")
    section_end = text.find("PREVIOUS DAY'S ADJUSTED SHORT SELLING TURNOVER", section_start)
    section = text[section_start:section_end if section_end > section_start else None]
    ratio_match = re.search(r"Short Selling of all Designated Securities as % total turnover\s*:\s*([\d.]+)%", section, re.I)
    value_match = re.search(r"\(C\) Short Selling of all Designated Securities.*?Short Selling Turnover Total Value \(\$\)\s*:\s*HKD\s*([\d,]+)", section, re.I | re.S)
    turnover_match = re.search(r"\(C\) Short Selling of all Designated Securities.*?Total market turnover\s*:\s*HKD\s*([\d,]+)", section, re.I | re.S)
    if not ratio_match:
        raise SourceError(f"HKEX daily quotation has no short-selling ratio for {trading_date}")
    observed = f"{trading_date}T16:30:00+08:00"
    source = _source(
        "hkex_official_short_selling",
        "Hong Kong Exchanges and Clearing Limited",
        "official_exchange",
        url,
        observed,
        "daily after market close; may receive next-day adjustments",
        "latest_available",
        "official",
        fetched_at,
    )
    return {
        "date": trading_date,
        "ratioPct": float(ratio_match.group(1)),
        "shortSellingTurnover": float(value_match.group(1).replace(",", "")) if value_match else None,
        "marketTurnover": float(turnover_match.group(1).replace(",", "")) if turnover_match else None,
        "scope": "all designated securities including ETP",
        "status": "official_daily",
    }, source


NEWS_QUERIES = [
    ("恒科与港股", '"恒生科技" OR "恒生科技指数" OR "港股科技"'),
    ("港股板块", "港股 科技 OR 互联网 OR AI OR 半导体 OR 晶片"),
    ("核心权重股", "腾讯 OR 阿里巴巴 OR 美团 OR 小米集团 港股"),
    ("其他成分股", "京东 OR 百度 OR 网易 OR 快手 OR 联想 OR 中芯 OR 华虹 港股"),
    ("宏观与利率", "美联储 OR FOMC OR 美债 OR 人民币 OR 美国零售销售 科技股"),
    ("资金与情绪", "南向资金 OR 港股通 OR 港股沽空 OR 恒生互联网 资金"),
    ("海外定价", '"China tech" OR "Hang Seng Tech" OR "Hong Kong stocks"'),
]

NEWS_EXCLUDE_TERMS = {"poco", "fold", "手机评测", "开箱", "三星galaxy", "拍照功能", "手机报价", "新品手机"}
NEWS_EXCLUDE_PUBLISHERS = {"moomoo", "富途牛牛", "大纪元", "pchome online 股市", "longbridge", "tradingview", "玩股網", "cmoney投資網誌"}
NEWS_MARKET_TERMS = {
    "恒生", "恒指", "恒科", "科指", "港股", "科技股", "股价", "股票", "指数", "市场", "资金", "南向", "港股通", "沽空", "腾讯", "阿里巴巴", "美团", "小米集团",
    "京东", "百度", "网易", "财报", "业绩", "回购", "监管", "政策", "宏观", "经济", "消费", "地产", "人民币", "美联储", "美债",
    "利率", "议息", "收益率", "通胀", "就业", "零售", "原油", "油价", "施政报告", "联想", "中芯", "华虹", "晶片", "芯片", "半导体",
    "nasdaq", "treasury", "federal reserve", "fomc", "yuan", "china tech", "hang seng tech", "semiconductor",
}

NEWS_HIGH_RELIABILITY_PUBLISHERS = {
    "reuters", "bloomberg", "香港電台新聞網", "香港电台新闻网", "香港交易所", "香港金融管理局", "美国联邦储备委员会",
    "明報財經網", "香港經濟日報hket", "信報網站", "证券时报", "中国证券报", "财联社", "第一财经",
}

NEWS_ASSET_ALIASES = {
    "恒生科技": ("恒生科技", "恒科", "科指", "hang seng tech"),
    "腾讯": ("腾讯", "騰訊"),
    "阿里巴巴": ("阿里巴巴", "阿里"),
    "小米集团": ("小米集团", "小米"),
    "美团": ("美团", "美團"),
    "京东": ("京东", "京東"),
    "百度": ("百度",),
    "网易": ("网易", "網易"),
    "快手": ("快手",),
    "联想集团": ("联想", "聯想"),
    "中芯国际": ("中芯",),
    "华虹半导体": ("华虹", "華虹"),
}


def _news_category(title: str) -> str:
    lowered = title.lower()
    rules = [
        ("央行 / 利率", ["fed", "美联储", "美聯儲", "美债", "美債", "殖利率", "yield", "利率"]),
        ("宏观数据", ["cpi", "就业", "就業", "零售", "消费", "消費", "通胀", "通脹", "gdp", "宏观", "宏觀"]),
        ("地缘 / 原油", ["oil", "原油", "地缘", "战争", "brent"]),
        ("政策", ["政策", "监管", "政府", "hkma", "金管局"]),
        ("公司 / 行业", ["腾讯", "阿里", "小米", "美团", "京东", "百度", "ai", "芯片"]),
        ("资金", ["南向", "港股通", "资金", "沽空"]),
    ]
    for category, keywords in rules:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "市场动态"


def _news_relevance(title: str) -> int:
    lowered = title.lower()
    if any(term in lowered for term in NEWS_EXCLUDE_TERMS) and not any(term in lowered for term in {"股价", "港股", "财报", "业绩", "回购"}):
        return -100
    score = sum(1 for term in NEWS_MARKET_TERMS if term in lowered)
    if any(term in lowered for term in {"恒生科技", "恒科", "港股", "南向", "美联储", "美债", "人民币"}):
        score += 3
    if any(term in lowered for term in {"财报", "业绩", "回购", "监管", "政策", "经济数据"}):
        score += 2
    return score


def _news_related_assets(title: str) -> list[str]:
    lowered = title.lower()
    return [name for name, aliases in NEWS_ASSET_ALIASES.items() if any(alias.lower() in lowered for alias in aliases)]


def _news_dedupe_key(title: str) -> str:
    cleaned = re.sub(r"\s*[-–—｜|]\s*(財經新聞|财经新闻|即時新聞|即时新闻|市場快訊|市场快讯).*$", "", title, flags=re.I)
    cleaned = re.sub(r"[〈《【\[].*?[〉》】\]]", "", cleaned)
    return re.sub(r"\W+", "", cleaned).lower()


def _news_relevance_reason(category: str, channel: str, related_assets: list[str]) -> str:
    if related_assets:
        return f"直接涉及{('、'.join(related_assets[:4]))}"
    if channel == "宏观与利率":
        return "可能通过美债、美元和风险偏好影响恒科估值"
    if category == "资金":
        return "反映港股资金承接与短期情绪"
    if category in {"公司 / 行业", "市场动态"}:
        return "反映恒科权重股或相关产业的当日表现"
    return "属于恒科需要联动观察的市场背景"


def _news_impact(title: str) -> tuple[str, str]:
    lowered = title.lower()
    negative = {"下跌", "走低", "制裁", "调查", "亏损", "放缓", "不及预期", "风险", "收益率上行", "油价上涨"}
    positive = {"上涨", "走高", "回购", "增长", "超预期", "降息", "刺激", "上调", "获批"}
    direction = "偏空" if any(term in lowered for term in negative) else "偏多" if any(term in lowered for term in positive) else "待验证"
    score = _news_relevance(title)
    weight = "高" if score >= 6 else "中" if score >= 3 else "低"
    return direction, weight


def _fetch_google_news_query(channel: str, base_query: str, after_date: str, before_date: str) -> tuple[str, list[Any]]:
    query = f"{base_query} after:{after_date} before:{before_date}"
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=zh-CN&gl=HK&ceid=HK:zh-Hans"
    )
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=12)
        response.raise_for_status()
        return channel, list(feedparser.parse(response.content).entries)
    except requests.RequestException:
        return channel, []


def get_news_feed(start: datetime, end: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fetched_at = iso_now()
    entries: dict[str, dict[str, Any]] = {}
    after_date = (start.date() - timedelta(days=1)).isoformat()
    before_date = (end.date() + timedelta(days=1)).isoformat()
    feeds: list[tuple[str, list[Any]]] = []
    with ThreadPoolExecutor(max_workers=len(NEWS_QUERIES)) as executor:
        futures = [executor.submit(_fetch_google_news_query, channel, query, after_date, before_date) for channel, query in NEWS_QUERIES]
        for future in as_completed(futures):
            feeds.append(future.result())
    for channel, feed_entries in feeds:
        for entry in feed_entries:
            published_struct = entry.get("published_parsed")
            if not published_struct:
                continue
            published = datetime(*published_struct[:6], tzinfo=UTC).astimezone(HKT)
            if not (start <= published <= end):
                continue
            raw_title = entry.get("title", "").strip()
            publisher = (entry.get("source") or {}).get("title") or "Unknown publisher"
            title = re.sub(rf"\s+-\s+{re.escape(publisher)}$", "", raw_title).strip()
            if publisher.lower() in NEWS_EXCLUDE_PUBLISHERS or any(term in title.lower() for term in {"討論區", "讨论区", "討論牆", "讨论墙", "股吧交流", "今日我咁睇"}):
                continue
            relevance = _news_relevance(title)
            if relevance < 2:
                continue
            related_assets = _news_related_assets(title)
            if any(marker in title.lower() for marker in {"港股異動", "港股异动"}) and not related_assets:
                continue
            dedupe_key = _news_dedupe_key(title)
            if not dedupe_key or dedupe_key in entries:
                continue
            publisher_url = (entry.get("source") or {}).get("href")
            direction, weight = _news_impact(title)
            category = _news_category(title)
            digest = hashlib.sha1(f"{title}|{published.isoformat()}".encode("utf-8")).hexdigest()[:12]
            entries[dedupe_key] = {
                "eventId": f"news-{digest}",
                "headline": title,
                "publisher": publisher,
                "url": entry.get("link"),
                "publisherUrl": publisher_url,
                "publishedAt": published.isoformat(),
                "fetchedAt": fetched_at,
                "category": category,
                "channel": channel,
                "relatedAssets": related_assets,
                "whyRelevant": _news_relevance_reason(category, channel, related_assets),
                "impactDirection": direction,
                "impactWeight": weight,
                "impactMethodology": "keyword-based preliminary classification; requires market-response validation",
                "relevanceScore": relevance,
                "sourceReliability": "high" if publisher.lower() in NEWS_HIGH_RELIABILITY_PUBLISHERS else "medium",
                "sourceType": "news_aggregator_with_original_publisher",
            }
    ranked = sorted(entries.values(), key=lambda item: (item["sourceReliability"] == "high", item["relevanceScore"], item["publishedAt"]), reverse=True)
    items: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    publisher_counts: dict[str, int] = {}
    for item in ranked:
        category = item["category"]
        publisher = item["publisher"].lower()
        if category_counts.get(category, 0) >= 4 or publisher_counts.get(publisher, 0) >= 2:
            continue
        items.append(item)
        category_counts[category] = category_counts.get(category, 0) + 1
        publisher_counts[publisher] = publisher_counts.get(publisher, 0) + 1
        if len(items) >= 12:
            break
    source = _source(
        "google_news_rss",
        "Google News RSS",
        "news_aggregator",
        "https://news.google.com/",
        items[0]["publishedAt"] if items else None,
        "continuous publisher-dependent feed",
        "latest_available",
        "medium",
        fetched_at,
    )
    return items[:12], source


OFFICIAL_CALENDAR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


def _official_event(
    identifier: str,
    name: str,
    event_at: datetime,
    category: str,
    importance: str,
    source_name: str,
    source_url: str,
    expected: str,
    positive: str,
    negative: str,
    action: str,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "name": name,
        "category": category,
        "eventAt": event_at.astimezone(HKT).isoformat(),
        "importance": importance,
        "expected": expected,
        "positive": positive,
        "negative": negative,
        "action": action,
        "sourceName": source_name,
        "sourceUrl": source_url,
        "sourceType": "government_release_calendar" if category != "央行政策" else "central_bank_calendar",
        "updateFrequency": "official schedule; refreshed for every report generation",
        "reliability": "official",
    }


def _get_bls_calendar_events(start: datetime, end: datetime) -> list[dict[str, Any]]:
    url = "https://www.bls.gov/schedule/news_release/bls.ics"
    response = requests.get(url, headers=OFFICIAL_CALENDAR_HEADERS, timeout=20)
    response.raise_for_status()
    if "BEGIN:VCALENDAR" not in response.text:
        raise SourceError("BLS calendar did not return iCalendar data")
    tracked = {
        "Employment Situation": ("美国非农就业报告", "critical"),
        "Consumer Price Index": ("美国消费者价格指数（CPI）", "critical"),
        "Producer Price Index": ("美国生产者价格指数（PPI）", "high"),
        "Job Openings and Labor Turnover Survey": ("美国JOLTS职位空缺", "high"),
        "Employment Cost Index": ("美国就业成本指数（ECI）", "high"),
    }
    events: list[dict[str, Any]] = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", response.text, re.S):
        summary_match = re.search(r"^SUMMARY:(.+)$", block, re.M)
        date_match = re.search(r"^DTSTART(?:;TZID=US-Eastern)?:([0-9]{8}T[0-9]{6})$", block, re.M)
        if not summary_match or not date_match:
            continue
        summary = summary_match.group(1).strip().replace("\\,", ",")
        if summary not in tracked:
            continue
        event_at = datetime.strptime(date_match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=ET)
        if not (start < event_at.astimezone(HKT) <= end):
            continue
        chinese_name, importance = tracked[summary]
        events.append(_official_event(
            f"bls-{summary.lower().replace(' ', '-')}-{event_at.date().isoformat()}",
            chinese_name,
            event_at,
            "经济数据",
            importance,
            "美国劳工统计局",
            url,
            "公布后比较实际值、市场预期与前值，并观察数据对利率路径定价的边际影响。",
            "数据组合有利于增长且未显著推高美债收益率与美元，科技股风险偏好改善。",
            "数据推动美债收益率和美元明显上行，或弱数据触发衰退交易，成长股估值承压。",
            "公布后联动检查美国10年期收益率、美元/离岸人民币、纳指和金龙指数。",
        ))
    return events


def _get_retail_calendar_events(start: datetime, end: datetime) -> list[dict[str, Any]]:
    url = "https://www.census.gov/retail/release_schedule.html"
    response = requests.get(url, headers=OFFICIAL_CALENDAR_HEADERS, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")
    if not table:
        raise SourceError("Census retail schedule table not found")
    events: list[dict[str, Any]] = []
    for row in table.find_all("tr")[1:]:
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        if len(cells) < 2 or "announced" in cells[1].lower():
            continue
        try:
            event_at = datetime.strptime(cells[1], "%B %d, %Y").replace(hour=8, minute=30, tzinfo=ET)
        except ValueError:
            continue
        if not (start < event_at.astimezone(HKT) <= end):
            continue
        events.append(_official_event(
            f"census-retail-{event_at.date().isoformat()}",
            f"美国{cells[0]}零售销售",
            event_at,
            "经济数据",
            "high",
            "美国人口普查局",
            url,
            "先比较实际值、市场预期和前值，再判断消费韧性与利率压力哪一项主导市场。",
            "数据温和改善且美债收益率、美元没有明显上行，科技股风险偏好保持稳定。",
            "数据过热推高利率预期，或显著走弱触发衰退担忧，均可能压制恒科估值。",
            "公布后联动观察美债、美元/离岸人民币、纳指期货和金龙指数。",
        ))
    return events


def _get_fomc_calendar_events(start: datetime, end: datetime) -> list[dict[str, Any]]:
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    response = requests.get(url, headers=OFFICIAL_CALENDAR_HEADERS, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    events: list[dict[str, Any]] = []
    for panel in soup.select("div.panel"):
        heading = panel.get_text(" ", strip=True)[:40]
        year_match = re.search(r"(20\d{2}) FOMC Meetings", heading)
        if not year_match:
            continue
        year = int(year_match.group(1))
        for meeting in panel.select("div.fomc-meeting"):
            month_node = meeting.select_one(".fomc-meeting__month")
            date_node = meeting.select_one(".fomc-meeting__date")
            if not month_node or not date_node:
                continue
            month_name = month_node.get_text(" ", strip=True).split("/")[-1]
            date_text = date_node.get_text(" ", strip=True).replace("*", "")
            end_day_match = re.search(r"(?:-|–)?(\d{1,2})$", date_text)
            if not end_day_match:
                continue
            try:
                event_at = datetime.strptime(
                    f"{month_name} {end_day_match.group(1)} {year} 14:00",
                    "%B %d %Y %H:%M",
                ).replace(tzinfo=ET)
            except ValueError:
                continue
            if not (start < event_at.astimezone(HKT) <= end):
                continue
            events.append(_official_event(
                f"fomc-decision-{event_at.date().isoformat()}",
                "FOMC利率决议与发布会",
                event_at,
                "央行政策",
                "critical",
                "美国联邦储备委员会",
                url,
                "重点不只看利率是否调整，还要比较声明、经济预测、点阵图和主席表态与市场原有定价的差异。",
                "政策路径较市场预期温和，美债收益率与美元回落，纳指和中概股风险偏好改善。",
                "政策路径偏鹰，美债收益率与美元上行，成长股估值继续承压。",
                "决议后分阶段核验声明、发布会、美债、美元、纳指、金龙指数及离岸人民币反应。",
            ))
    return events


def get_official_macro_events(start: datetime, end: datetime) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source_id, loader in (
        ("bls_official_calendar", _get_bls_calendar_events),
        ("census_retail_calendar", _get_retail_calendar_events),
        ("federal_reserve_fomc_calendar", _get_fomc_calendar_events),
    ):
        try:
            events.extend(loader(start, end))
        except Exception as exc:
            errors.append({"sourceId": source_id, "message": f"{type(exc).__name__}: {exc}"})
    deduplicated = {event["id"]: event for event in events}
    return sorted(deduplicated.values(), key=lambda event: event["eventAt"]), errors


def cutoff_for(trading_date: str, session: str) -> datetime:
    hhmm = {"morning": "08:30", "midday": "12:30", "evening": "17:00"}[session]
    return datetime.strptime(f"{trading_date} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=HKT)


def news_window(trading_date: str, session: str) -> tuple[datetime, datetime]:
    cutoff = cutoff_for(trading_date, session)
    if session == "morning":
        start = cutoff - timedelta(days=3 if cutoff.weekday() == 0 else 1)
    elif session == "midday":
        start = datetime.combine(cutoff.date(), time(8, 30), HKT)
    else:
        start = datetime.combine(cutoff.date(), time(0, 0), HKT)
    return start, cutoff
