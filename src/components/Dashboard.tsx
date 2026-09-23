"use client";

import { useEffect, useMemo, useState } from "react";
import type { Constituent, DashboardSnapshot, MarketEvent, MinuteBar, SessionKey, WatchItem } from "@/lib/dashboard-types";

const sessionLabels: Record<SessionKey, string> = { morning: "早报", midday: "午报", evening: "晚报" };
const sessionTimes: Record<SessionKey, string> = { morning: "08:30", midday: "12:30", evening: "17:00" };
const freshnessLabels: Record<string, string> = { realtime: "实时", delayed: "延迟数据", latest_available: "最近可用", stale: "数据过期", unavailable: "不可用" };
const statusLabels: Record<string, string> = { pending: "待观察", triggered: "已触发", validated: "已验证", failed: "未触发", invalidated: "已失效" };
const attributionLabels: Record<string, string> = { confirmed: "已确认", strongly_related: "高度相关", possible: "可能相关", structural: "结构性", unknown: "未知" };
const conditionTypeLabels: Record<string, string> = { resistance: "压力位", support: "支撑位", marketBreadth: "市场宽度", capitalFlow: "南向资金", macroEvent: "宏观事件", newsCatalyst: "新闻催化" };
const focusGroupLabels: Record<string, string> = { message: "消息面关注", capital: "资金面关注", market: "市场条件" };

function latestDateForSession(availability: DashboardSnapshot["availability"], session: SessionKey) {
  return availability ? Object.keys(availability.available)
    .sort((left, right) => right.localeCompare(left))
    .find((date) => availability.available[date]?.includes(session)) ?? null : null;
}

function shortDate(value: string | null) {
  return value ? value.slice(5).replace("-", "/") : "暂无";
}

function defaultSession(): SessionKey {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  if (minutes < 510) return "evening";
  if (minutes < 750) return "morning";
  if (minutes < 1020) return "midday";
  return "evening";
}

function formatNumber(value: unknown, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "Data unavailable";
}

function formatMetric(value: string | number | null, unit: string) {
  if (value === null || value === undefined || value === "") return "Data unavailable";
  return `${typeof value === "number" ? formatNumber(value) : value}${unit ? ` ${unit}` : ""}`;
}

function localTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Hong_Kong", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

function EventBadge({ event }: { event: MarketEvent }) {
  return <span className={`event-badge ${event.kind}`}>{event.title}</span>;
}

function PriceChart({ bars, events, active, onActive, levels }: { bars: MinuteBar[]; events: MarketEvent[]; active: MarketEvent | null; onActive: (event: MarketEvent) => void; levels: WatchItem[] }) {
  if (!bars.length) return <div className="chart-empty"><b>早报尚无当日分时</b><span>开盘后由午报接入真实分钟行情和事件标记。</span></div>;
  const width = 940, height = 390;
  const pad = { left: 58, right: 18, top: 24 }, priceBottom = 262, volumeTop = 294, volumeBottom = 360;
  const prices = bars.map((bar) => bar.close), rawMin = Math.min(...prices), rawMax = Math.max(...prices), margin = Math.max((rawMax - rawMin) * 0.12, 5);
  const min = rawMin - margin, max = rawMax + margin;
  const x = (index: number) => pad.left + (index / Math.max(1, bars.length - 1)) * (width - pad.left - pad.right);
  const y = (price: number) => pad.top + ((max - price) / Math.max(1, max - min)) * (priceBottom - pad.top);
  const path = bars.map((bar, index) => `${index ? "L" : "M"}${x(index)},${y(bar.close)}`).join(" ");
  const area = `${path} L ${x(bars.length - 1)},${priceBottom} L ${x(0)},${priceBottom} Z`;
  const maxTurnover = Math.max(...bars.map((bar) => bar.turnover), 1);
  const gridValues = Array.from({ length: 6 }, (_, index) => min + ((max - min) * index) / 5);
  const labelIndexes = Array.from(new Set([0, Math.floor((bars.length - 1) * .25), Math.floor((bars.length - 1) * .5), Math.floor((bars.length - 1) * .75), bars.length - 1]));
  const barWidth = Math.max(1, (width - pad.left - pad.right) / bars.length - .4);
  return <div className="chart-wrap"><svg viewBox={`0 0 ${width} ${height}`} aria-label="恒生科技真实日内价格与成交额">
    <defs><linearGradient id="real-area" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#16835d" stopOpacity=".2"/><stop offset="100%" stopColor="#16835d" stopOpacity="0"/></linearGradient></defs>
    {gridValues.map((value) => <g key={value}><line x1={pad.left} x2={width - pad.right} y1={y(value)} y2={y(value)} className="grid"/><text x="7" y={y(value) + 4} className="axis-label">{value.toFixed(0)}</text></g>)}
    <path d={area} fill="url(#real-area)"/><path d={path} className="price-line"/>
    {levels.filter((item) => ["support", "resistance"].includes(item.conditionType)).slice(0, 3).map((item) => <g key={item.id}><line x1={pad.left} x2={width - pad.right} y1={y(item.threshold)} y2={y(item.threshold)} className={`level-line ${item.conditionType === "resistance" ? "resistance" : ""}`}/><text x={width - pad.right - 2} y={y(item.threshold) - 5} textAnchor="end" className={`level-label ${item.conditionType === "resistance" ? "resistance-label" : ""}`}>{item.threshold.toFixed(0)} · {item.label}</text></g>)}
    <line x1={pad.left} x2={width - pad.right} y1={volumeTop - 9} y2={volumeTop - 9} className="volume-separator"/><text x={pad.left} y={volumeTop - 14} className="volume-label">分钟成交额</text>
    {bars.map((bar, index) => { const h = (bar.turnover / maxTurnover) * (volumeBottom - volumeTop); const down = index > 0 && bar.close < bars[index - 1].close; return <rect key={bar.timestamp} x={x(index) - barWidth / 2} y={volumeBottom - h} width={barWidth} height={h} className={down ? "volume-bar sell" : "volume-bar"}/>; })}
    {labelIndexes.map((index) => <text key={index} x={x(index)} y={height - 11} textAnchor="middle" className="axis-label">{bars[index].time}</text>)}
    {events.map((event) => { const index = Math.min(event.pointIndex, bars.length - 1), cx = x(index), cy = y(bars[index].close), selected = active?.id === event.id; return <g key={event.id} className="event-dot" onMouseEnter={() => onActive(event)} onClick={() => onActive(event)}>{selected && <line x1={cx} x2={cx} y1={pad.top} y2={volumeBottom} className="active-guide"/>}<circle cx={cx} cy={cy} r={selected ? 9 : 5.5} className={`dot ${event.kind}`}/><circle cx={cx} cy={cy} r="1.8" className="dot-core"/></g>; })}
  </svg><div className="chart-note"><span className="dot-legend warning"/>异常 <span className="dot-legend turn"/>转折/突破　Hover 快看，Click 锁定并联动右侧成分股</div></div>;
}

function MarketBoard({ snapshot }: { snapshot: DashboardSnapshot }) {
  const priority = snapshot.session === "morning" ? ["hxc", "nasdaq", "ndx", "us10y", "usdcnh", "nikkei", "kospi", "brent"] : ["hsi", "sse", "chinext", "star50", "nikkei", "kospi", "usdcnh", "us10y"];
  const markets = priority.map((key) => snapshot.crossMarkets.find((item) => item.key === key)).filter(Boolean) as DashboardSnapshot["crossMarkets"];
  return <div className="market-cards">{markets.map((item) => <article key={item.key} title={`${item.source.sourceName} · ${localTime(item.timestamp)}`}><span>{item.name}</span><b className={(item.changePct ?? 0) > 0 ? "up" : (item.changePct ?? 0) < 0 ? "down" : "neutral"}>{item.changePct === null ? "—" : `${item.changePct > 0 ? "+" : ""}${item.changePct.toFixed(2)}%`}</b><small>{item.sessionRelationship === "overnight" ? "隔夜收盘" : item.sessionRelationship === "continuous" ? "连续市场" : "同日市场"} · {freshnessLabels[item.freshness] ?? item.freshness} · {localTime(item.timestamp)}</small></article>)}</div>;
}

function WatchPanel({ items, selectedId, onSelect }: { items: WatchItem[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const groupOrder = ["message", "capital", "market"];
  const selected = items.find((item) => item.id === selectedId) ?? items.find((item) => item.group === "message") ?? items[0];
  if (!selected) return <div className="data-unavailable">后续关注暂无可执行条件</div>;
  return <div className="outlook-body"><div className="watch-items">{groupOrder.map((group) => {
    const groupedItems = items.filter((item) => (item.group ?? "market") === group);
    if (!groupedItems.length) return null;
    return <section className={`watch-group ${group}`} key={group}><div className="watch-group-title"><b>{focusGroupLabels[group]}</b><span>{groupedItems.length} 项</span></div>{groupedItems.map((item) => <button key={item.id} className={`watch-item ${selected.id === item.id ? "selected" : ""}`} onClick={() => onSelect(item.id)}><span className={`watch-state ${item.status}`}>{statusLabels[item.status] ?? item.status}</span><span><small>{item.conditionTypeLabel ?? conditionTypeLabels[item.conditionType] ?? "观察条件"}{item.importance === "critical" ? " · 最高" : item.importance === "high" ? " · 重要" : ""}</small><b>{item.displayValue ?? `${item.operator} ${item.threshold}`}</b><em>{item.label}</em></span></button>)}</section>;
  })}</div><div className="interpretation"><p className="eyebrow">{focusGroupLabels[selected.group ?? "market"]} · 预期与行动</p><h3>{selected.label}</h3>{selected.eventAt && <p className="focus-time">公布时点：{localTime(selected.eventAt)}（香港时间）</p>}<dl><div><dt>预计情况 / 该怎么看</dt><dd>{selected.expected}</dd></div><div><dt>偏多 / 有效信号</dt><dd>{selected.positive}</dd></div><div><dt>偏空 / 失效信号</dt><dd>{selected.negative}</dd></div><div><dt>当前状态</dt><dd>{selected.validationResult}</dd></div><div><dt>对应行动</dt><dd>{selected.action}</dd></div></dl>{selected.source && <a className="focus-source" href={selected.source.sourceUrl} target="_blank" rel="noreferrer">来源：{selected.source.sourceName}{selected.conditionType === "macroEvent" ? " · 官方日程" : " · 原始报道"} ↗</a>}</div></div>;
}

function ScenarioPanel({ items }: { items: WatchItem[] }) {
  const resistance = items.find((item) => item.conditionType === "resistance"), support = items.find((item) => item.conditionType === "support");
  return <><div className="branch positive"><b>A · 站稳 {resistance?.threshold ?? "上方压力"}</b><span>确认：连续30分钟 + 市场宽度改善</span><strong>条件验证后再提高风险敞口</strong><small>{resistance?.validationResult ?? "等待数据"}</small></div><div className="branch neutral-branch"><b>B · 区间震荡</b><span>确认：支撑与压力条件均未验证</span><strong>保持观察，不用单一价格点下结论</strong><small>同时检查成交、宽度和南向流向</small></div><div className="branch negative"><b>C · 有效跌破 {support?.threshold ?? "下方支撑"}</b><span>确认：连续30分钟 + 反抽失败</span><strong>重新评估风险并等待下一时点报告</strong><small>{support?.validationResult ?? "等待数据"}</small></div></>;
}

const reportModes: Record<SessionKey, { reviewTitle: string; reviewDescription: string; followTitle: string; followDescription: string; crossTitle: string; flow: Array<{ label: string; text: string }> }> = {
  morning: {
    reviewTitle: "隔夜复盘与盘前研判",
    reviewDescription: "承接上一交易日晚报，核验隔夜市场、宏观事件与开盘前风险。",
    followTitle: "今日开盘与上午关注",
    followDescription: "把隔夜结果转化成今天需要验证的价位、资金和市场条件。",
    crossTitle: "隔夜定价与亚洲早盘",
    flow: [
      { label: "承接上一晚报", text: "读取后续事件与待验证条件" },
      { label: "当前早报", text: "核验隔夜结果并重建今日假设" },
      { label: "午报验证", text: "用开盘与上午行情检查假设" },
    ],
  },
  midday: {
    reviewTitle: "上午行情复盘",
    reviewDescription: "核验早报提出的条件，集中解释上午价格、量能、成分股和资金变化。",
    followTitle: "午后关注与验证",
    followDescription: "将上午已经发生的结果转化为下午需要继续验证的条件。",
    crossTitle: "上午跨市场联动",
    flow: [
      { label: "承接早报", text: "逐项检查盘前假设是否触发" },
      { label: "当前午报", text: "复盘上午走势与驱动证据" },
      { label: "晚报验证", text: "检验午后条件并形成全天结论" },
    ],
  },
  evening: {
    reviewTitle: "全天市场复盘",
    reviewDescription: "先完成全天结论、走势归因、板块结构、跨市场与资金面的统一复盘。",
    followTitle: "后续关注与下一时点验证",
    followDescription: "把全天结论连接到夜间事件和下一份早报，不把待验证信息混入复盘。",
    crossTitle: "全天跨市场联动",
    flow: [
      { label: "承接午报", text: "核验午后观察条件与情景分支" },
      { label: "当前晚报", text: "形成全天复盘与收盘判断" },
      { label: "后续报告", text: "夜间事件结果进入下一早报" },
    ],
  },
};

function ReportLifecycle({ session }: { session: SessionKey }) {
  return <div className="report-lifecycle">{reportModes[session].flow.map((step, index) => <div className={index === 1 ? "current" : ""} key={step.label}><span>{index + 1}</span><section><b>{step.label}</b><small>{step.text}</small></section>{index < 2 && <i>→</i>}</div>)}</div>;
}

function ScoreCard({ card }: { card: DashboardSnapshot["scoreCard"] }) {
  if (!card || card.status !== "calculated" || card.total === undefined) return <section className="panel score-preview score-unavailable"><p className="eyebrow">HSTECH SCORE</p><h2>该历史报告尚未计算综合评分</h2><p>新生成的早报、午报和晚报会自动加入评分与动态目标点位。</p></section>;
  const movement = card.movement === "up" ? "上升" : card.movement === "down" ? "下降" : card.movement === "flat" ? "持平" : "首期基准";
  const targets = [card.targets.short, card.targets.medium, card.targets.long];
  const targetLabels = ["短期目标", "中期目标", "长期目标"];
  return <section className="panel score-preview">
    <div className="score-preview-head"><div><p className="eyebrow">HSTECH SCORE · RULE-BASED MODEL</p><h2>恒科综合评分与动态目标点位</h2><p>{card.methodology}</p></div><span>计算数据 · 有效覆盖 {card.confidence}/100</span></div>
    <div className="score-preview-body">
      <div className="score-hero"><div className="score-ring" style={{ "--score": `${card.total * 3.6}deg` } as React.CSSProperties}><strong>{card.total.toFixed(1)}</strong><span>/ 100</span></div><div><span className="score-grade">{card.label}</span><b className={card.movement === "up" ? "up" : card.movement === "down" ? "down" : "neutral"}>较上一期 {movement}{card.delta === null || card.delta === undefined ? "" : ` ${card.delta > 0 ? "+" : ""}${card.delta.toFixed(1)} 分`}</b><p>{card.judgment}</p></div></div>
      <div className="score-dimensions">{card.dimensions.map((item) => <div key={item.key} title={item.reason}><span>{item.label}<small>{item.score} / {item.weight}</small></span><i><em style={{ width: `${(item.score / item.weight) * 100}%` }}/></i></div>)}</div>
      <div className="target-zones">{targets.map((target, index) => <article key={targetLabels[index]}><span>{targetLabels[index]} · {target.direction === "up" ? "向上" : target.direction === "down" ? "向下" : "横向"}</span><b className={target.direction === "up" ? "up" : target.direction === "down" ? "down" : "neutral"}>{formatNumber(target.point, 0)} 点</b><small>参考区间 {formatNumber(target.rangeLow, 0)}–{formatNumber(target.rangeHigh, 0)} · {target.horizon}</small><em>{target.basis}</em><em>失效参考 {formatNumber(target.invalidation, 0)}</em></article>)}<p>目标点位每份报告重新计算；区间仅表示模型容许误差，不代表收益承诺。</p></div>
    </div>
  </section>;
}

export default function Dashboard() {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [session, setSession] = useState<SessionKey>(() => defaultSession());
  const [reportDate, setReportDate] = useState("");
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [selectedWatchId, setSelectedWatchId] = useState<string | null>(null);
  const [showConstituents, setShowConstituents] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ session });
    if (reportDate) params.set("date", reportDate);
    setLoading(true); setError(null);
    fetch(`/api/dashboard?${params}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => { const body = await response.json(); if (!response.ok) throw new Error(body.error ?? "Data unavailable"); return body as DashboardSnapshot; })
      .then((data) => { setSnapshot(data); setReportDate(data.tradingDate); setSelectedEventId(data.events[0]?.id ?? null); setSelectedWatchId(data.watchlist.find((item) => item.conditionType === "macroEvent")?.id ?? data.watchlist.find((item) => item.conditionType !== "newsCatalyst")?.id ?? null); })
      .catch((reason) => { if (reason.name !== "AbortError") setError(reason.message); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [session, reportDate]);

  const selectedEvent = snapshot?.events.find((event) => event.id === selectedEventId) ?? snapshot?.events[0] ?? null;
  const relatedNames = useMemo(() => new Set(selectedEvent?.relatedStocks.map((item) => item.name) ?? []), [selectedEvent]);
  const contributors = useMemo(() => snapshot ? [...snapshot.constituents].filter((item) => item.changePct !== null).sort((a, b) => Math.abs(b.contributionPoints ?? 0) - Math.abs(a.contributionPoints ?? 0)).slice(0, 8) : [], [snapshot]);

  const switchSession = (next: SessionKey) => {
    const latestDate = latestDateForSession(snapshot?.availability, next);
    if (!latestDate) { setError(`尚无可用的${sessionLabels[next]}`); return; }
    setError(null);
    setSession(next);
    setReportDate(latestDate);
  };
  const switchDate = (nextDate: string) => {
    const available = snapshot?.availability?.available[nextDate] ?? [];
    if (!available.length) { setError(`${nextDate} 尚无已生成的报告`); return; }
    const nextSession = available.includes(session)
      ? session
      : (["evening", "midday", "morning"] as SessionKey[]).find((item) => available.includes(item)) ?? available[0];
    setError(null);
    setReportDate(nextDate);
    setSession(nextSession);
  };
  const returnLatest = () => {
    setError(null);
    setReportDate(snapshot?.availability?.latestDate ?? "");
    setSession(snapshot?.availability?.latestSession ?? "evening");
  };

  if (!snapshot && loading) return <main className="shell"><section className="panel empty-report"><p className="eyebrow">LOADING REAL MARKET DATA</p><h2>正在读取最近一次真实报告</h2><p>页面不会用演示值填补等待中的数据。</p></section></main>;
  if (!snapshot) return <main className="shell"><section className="panel empty-report"><p className="eyebrow">DATA UNAVAILABLE</p><h2>报告暂时不可用</h2><p>{error ?? "尚未生成真实数据快照"}</p></section></main>;

  const titlePrefix = snapshot.session === "morning" ? "盘前" : snapshot.session === "midday" ? "上午" : "全天";
  const sourceFreshness = snapshot.index.source?.freshness ?? "unavailable";
  const flowSummary = snapshot.capitalFlows.find((item) => item.key === "southbound");
  const reportMode = reportModes[snapshot.session];
  const planningWatchlist = snapshot.watchlist.filter((item) => item.conditionType !== "newsCatalyst");
  const availableDates = snapshot.availability ? Object.keys(snapshot.availability.available).sort((left, right) => right.localeCompare(left)) : [snapshot.tradingDate];
  const latestBySession = Object.fromEntries((["morning", "midday", "evening"] as SessionKey[]).map((item) => [item, latestDateForSession(snapshot.availability, item)])) as Record<SessionKey, string | null>;
  const isLatestOfType = reportDate === latestBySession[session];

  return <main className="shell">
    <header className="topbar"><div><p className="eyebrow">HANG SENG TECH · RESEARCH WORKBENCH</p><h1>恒生科技投资工作台</h1></div><div className="header-tools"><span className={`data-status ${snapshot.overallStatus}`}>{snapshot.overallStatus === "ok" ? "真实数据完整" : "真实数据 · 部分字段不可用"}</span><div className="date-block"><span>{snapshot.tradingDate}</span><small>{snapshot.sessionLabel} · {freshnessLabels[sourceFreshness] ?? sourceFreshness} · 截止 {snapshot.marketCutoff.slice(11, 16)}</small></div></div></header>
    <nav className="report-toolbar"><div className="report-switcher"><div className="report-tabs">{(["morning", "midday", "evening"] as const).map((item) => <button key={item} className={session === item ? "active" : ""} onClick={() => switchSession(item)} title={`打开最近一份${sessionLabels[item]}`}>{sessionLabels[item]}<small>{sessionTimes[item]} · 最新 {shortDate(latestBySession[item])}</small></button>)}</div><small className="switch-hint">切换报告类型会自动打开该类型最近一份</small></div><div className="date-filter"><label htmlFor="report-date">历史日期</label><select id="report-date" value={reportDate} onChange={(event) => switchDate(event.target.value)}>{availableDates.map((date) => <option value={date} key={date}>{date}</option>)}</select><button onClick={returnLatest}>返回全站最新</button><span>{loading ? "正在更新…" : `当前：${snapshot.tradingDate} ${snapshot.sessionLabel}${isLatestOfType ? " · 该类型最新" : " · 历史报告"}｜生成于 ${localTime(snapshot.generatedAt)}`}</span></div></nav>
    {error && <div className="source-warning"><b>Data unavailable</b><span>{error}</span><button onClick={() => setError(null)}>关闭</button></div>}
    <div className="utility-row"><div><span className="source-pill">主行情：{snapshot.index.source?.sourceName ?? "不可用"}</span><span className="source-pill">成分股：恒生指数公司官方名单与权重</span></div><span>每项数据均保留原始时间和抓取时间</span></div>

    <ScoreCard card={snapshot.scoreCard}/>

    <section className="workspace-stage review-stage">
      <header className="stage-heading"><span>01</span><div><p className="eyebrow">REVIEW · {snapshot.sessionLabel}</p><h2>{reportMode.reviewTitle}</h2><small>{reportMode.reviewDescription}</small></div><b>先复盘，再决策</b></header>
      <ReportLifecycle session={snapshot.session}/>

      <section className="panel closing-panel top-judgment"><div><p className="eyebrow">{snapshot.session.toUpperCase()} JUDGMENT · {snapshot.reportId}</p><h2>{snapshot.judgment.title}</h2><p>{snapshot.judgment.summary}</p></div><div className="judgment"><span>{snapshot.sessionLabel} · 短线</span><b>{snapshot.judgment.short}</b></div><div className="judgment"><span>技术状态</span><b>{snapshot.judgment.medium}</b></div><div className="judgment"><span>后续验证</span><b>{snapshot.judgment.validation}</b></div></section>
      <section className="metrics">{snapshot.metrics.map((metric) => <article className={`metric ${metric.key === "price" ? "primary" : ""}`} key={metric.key} title={`${metric.note}${metric.source ? ` · ${metric.source.sourceName} · ${localTime(metric.source.originalTimestamp)}` : " · 计算数据"}`}><span>{metric.label}</span><strong className={metric.value === null ? "unavailable-value" : ""}>{formatMetric(metric.value, metric.unit)}</strong><em className={metric.tone}>{metric.badge}</em><small>{metric.note}</small></article>)}</section>

      <section className="core-grid">
        <article className="panel replay-panel"><div className="panel-head"><div><p className="eyebrow">{snapshot.session === "morning" ? "PRE-MARKET MAP" : "INTRADAY REPLAY"}</p><h2>{titlePrefix}关键走势、量能与原因</h2></div>{selectedEvent && <div className="event-status"><EventBadge event={selectedEvent}/><span>{selectedEvent.endTime}</span></div>}</div><PriceChart bars={snapshot.minuteBars} events={snapshot.events} active={selectedEvent} onActive={(event) => setSelectedEventId(event.id)} levels={snapshot.watchlist}/>{snapshot.events.length > 0 && <><div className="event-strip" style={{ gridTemplateColumns: `repeat(${snapshot.events.length}, minmax(110px, 1fr))`, overflowX: "auto" }}>{snapshot.events.map((event) => <button key={event.id} className={selectedEvent?.id === event.id ? "selected" : ""} onMouseEnter={() => setSelectedEventId(event.id)} onClick={() => setSelectedEventId(event.id)}><time>{event.endTime}</time><span className="category flow">{event.eventType}</span><b>{event.title}</b></button>)}</div>{selectedEvent && <div className="event-analysis"><div><span>指数与量能</span><b>{selectedEvent.indexStart} → {selectedEvent.indexEnd}（{selectedEvent.changePct > 0 ? "+" : ""}{selectedEvent.changePct}%）</b><small>{selectedEvent.volumeChange === null ? "成交基准不可用" : `相对基准 ${selectedEvent.volumeChange > 0 ? "+" : ""}${selectedEvent.volumeChange}%`}</small></div><div><span>谨慎归因</span><b>{attributionLabels[selectedEvent.attributionLevel]} · {selectedEvent.possibleExplanation}</b><small>{selectedEvent.crossMarketMoves.length ? selectedEvent.crossMarketMoves.map((item) => `${item.name} ${item.changePct > 0 ? "+" : ""}${item.changePct}%`).join("；") : "未发现同窗口跨市场强证据"}</small></div><div><span>证据与置信度</span><b>{selectedEvent.confidence === "high" ? "高" : selectedEvent.confidence === "medium" ? "中" : "低"}</b><small>{selectedEvent.evidence.join("；")}</small></div></div>}</>}</article>
        <article className="panel contribution-panel"><div className="panel-head"><div><p className="eyebrow">CONSTITUENT IMPACT</p><h2>{titlePrefix}成分股贡献与板块结构</h2></div><button className="secondary-button" onClick={() => setShowConstituents(true)}>查看全部 30 只 →</button></div><div className="contribution-head"><span>成分股 / 官方权重</span><span>涨跌幅</span><span>估算影响</span><span>贡献点数</span></div><div className="contribution-list">{contributors.length ? contributors.map((item) => <div className={`contribution ${relatedNames.has(item.name) ? "related" : ""}`} key={item.code}><div><b>{item.name}</b><small>{item.industry} · 权重 {item.weight.toFixed(2)}%</small></div><span className={(item.changePct ?? 0) > 0 ? "up" : "down"}>{item.changePct === null ? "—" : `${item.changePct > 0 ? "+" : ""}${item.changePct.toFixed(2)}%`}</span><div className="bar-track"><i className={(item.contributionPoints ?? 0) > 0 ? "bar upbar" : "bar downbar"} style={{ width: `${Math.min(100, Math.abs(item.contributionPoints ?? 0) * 18)}%` }}/></div><em>{item.contributionPoints === null ? "不可用" : `${item.contributionPoints > 0 ? "+" : ""}${item.contributionPoints.toFixed(2)}`}</em></div>) : <div className="data-unavailable">开盘前无当日成分股涨跌，不使用收盘数据回填。</div>}</div><div className="sector-summary"><div><span>市场宽度</span><b>{snapshot.breadth.advances}涨 / {snapshot.breadth.declines}跌 / {snapshot.breadth.unchanged}平</b></div><div><span>数据覆盖</span><b>{snapshot.breadth.available} / {snapshot.breadth.universe}</b></div><div><span>贡献口径</span><b>estimated</b></div></div><p className="data-note">贡献点数为官方月度权重 × 成分股时点收益 × 指数昨收的估算值；页面明确标为 estimated，不冒充官方精确贡献。</p></article>
      </section>

      <section className="panel cross-panel"><div className="panel-head"><div><p className="eyebrow">CROSS-MARKET</p><h2>{reportMode.crossTitle}</h2></div><span className="hint">每张卡片保留市场时区和观测时间</span></div><MarketBoard snapshot={snapshot}/></section>
      <article className="panel capital-panel capital-wide"><div className="panel-head"><div><p className="eyebrow">CAPITAL FLOW</p><h2>{titlePrefix}资金面</h2></div><span className="permanent-tag">复盘模块 · 每日存档</span></div><div className="fund-summary"><span>资金主线</span><b>{flowSummary?.value === null || !flowSummary ? "南向数据不可用" : `南向 ${flowSummary.value > 0 ? "净流入" : "净流出"} ${Math.abs(flowSummary.value).toFixed(2)} ${flowSummary.unit}`}</b></div><div className="fund-list">{snapshot.capitalFlows.map((item) => <article key={item.key}><div><span>{item.label}</span><b className={(item.value ?? 0) > 0 ? "up" : item.value === null ? "neutral" : "down"}>{item.value === null ? "Data unavailable" : `${item.value.toFixed(2)} ${item.unit}`}</b><p>{item.source ? `${item.source.sourceName} · ${freshnessLabels[item.source.freshness] ?? item.source.freshness}` : "尚无可靠公开数据"}</p></div><aside><strong>{item.status}</strong><small>{item.period}</small></aside></article>)}</div><p className="capital-note">资金面只展示可追溯的南向总额与沪、深港股通分项；延迟估算会明确标注，不使用无法稳定取得的沽空比率或恒科期货基差。</p></article>
    </section>

    <section className="workspace-stage followup-stage">
      <header className="stage-heading"><span>02</span><div><p className="eyebrow">FORWARD WATCH · {snapshot.sessionLabel}</p><h2>{reportMode.followTitle}</h2><small>{reportMode.followDescription}</small></div><b>由复盘产生条件</b></header>
      <section className="plan-grid"><article className="panel outlook-panel"><div className="panel-head"><div><p className="eyebrow">WATCH · EXPECT · ACT</p><h2>后续关注、预期与行动</h2></div><span className="live-dot">仅保留有明确节点的重大事件与市场条件 · 共 {planningWatchlist.length} 项</span></div><WatchPanel items={planningWatchlist} selectedId={selectedWatchId} onSelect={setSelectedWatchId}/></article><article className="panel branch-panel"><div className="panel-head"><div><p className="eyebrow">SCENARIO BRANCHES</p><h2>情景分支与验证规则</h2></div><span className="hint">基于当日有效条件生成</span></div><ScenarioPanel items={planningWatchlist}/></article></section>
      <article className="panel news-panel news-wide"><div className="panel-head"><div><p className="eyebrow">EVENT FEED</p><h2>{titlePrefix}消息面与市场动态</h2></div><span className="hint">{snapshot.news.length} 条相关信息 · 多通道检索并限制重复来源</span></div><div className="news-list">{snapshot.news.length ? snapshot.news.map((item) => <article key={item.eventId}><div><span className="news-tag industry">{item.category}</span>{item.channel && <span className="news-channel">{item.channel}</span>}<h3><a href={item.url} target="_blank" rel="noreferrer">{item.headline}</a></h3><p>{item.publisher} · {item.whyRelevant ?? (item.relatedAssets.length ? `涉及 ${item.relatedAssets.join("、")}` : "市场背景")}</p></div><aside><b className={item.impactDirection === "偏空" ? "down" : item.impactDirection === "偏多" ? "up" : "neutral"}>{item.impactDirection}</b><span>影响权重 {item.impactWeight} · 初步规则</span><small>{localTime(item.publishedAt)}</small></aside></article>) : <div className="data-unavailable">该报告窗口未发现满足检索条件的新闻。</div>}</div></article>
    </section>

    <section className="panel source-panel"><div className="panel-head"><div><p className="eyebrow">DATA LINEAGE</p><h2>数据来源、时点与状态</h2></div><span className="hint">抓取于 {localTime(snapshot.generatedAt)}</span></div><div className="source-grid">{snapshot.sourceStatus.map((source) => <a key={source.sourceId} href={source.sourceUrl} target="_blank" rel="noreferrer"><b>{source.sourceName}</b><span>{freshnessLabels[source.freshness] ?? source.freshness} · {source.reliability}</span><small>原始时点 {localTime(source.originalTimestamp)} · 抓取 {localTime(source.fetchedAt)}</small></a>)}</div>{snapshot.sourceErrors.length > 0 && <div className="source-errors">{snapshot.sourceErrors.map((item, index) => <span key={`${item.sourceId}-${index}`}>{item.sourceId}: {item.message}</span>)}</div>}</section>
    <footer className="risk-banner"><b>风险提示</b><span>本工作台仅用于交易复盘与研究，不构成投资建议。计算数据、估算贡献和规则判断均有明确标识。</span></footer>

    {showConstituents && <div className="modal-backdrop" onClick={() => setShowConstituents(false)}><section className="constituent-modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}><div className="panel-head"><div><p className="eyebrow">CONSTITUENT DRILLDOWN</p><h2>恒生科技 30 只成分股 · {snapshot.sessionLabel}</h2></div><button className="close-button" onClick={() => setShowConstituents(false)}>关闭 ×</button></div><p className="modal-note">名单与权重来自恒生指数公司官方事实表；价格来自报告截止时点的分钟行情。贡献为 estimated 时会明确标注。</p><div className="constituent-table"><div className="table-head"><span>名称 / 代码</span><span>官方权重</span><span>涨跌幅</span><span>估算贡献</span><span>状态</span></div>{snapshot.constituents.map((item: Constituent) => <div className="table-row" key={item.code}><b>{item.name}<small>{item.code}</small></b><span>{item.weight.toFixed(2)}%</span><span className={(item.changePct ?? 0) > 0 ? "up" : (item.changePct ?? 0) < 0 ? "down" : "neutral"}>{item.changePct === null ? "—" : `${item.changePct > 0 ? "+" : ""}${item.changePct.toFixed(2)}%`}</span><span>{item.contributionPoints === null ? "—" : `${item.contributionPoints > 0 ? "+" : ""}${item.contributionPoints.toFixed(2)} 点`}</span><span className={item.contributionType === "estimated" ? "verified" : "pending-text"}>{item.contributionType}</span></div>)}</div></section></div>}
  </main>;
}
