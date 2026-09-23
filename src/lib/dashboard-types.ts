export type SessionKey = "morning" | "midday" | "evening";

export type SourceMeta = {
  sourceId: string;
  sourceName: string;
  sourceType: string;
  sourceUrl: string;
  originalTimestamp: string | null;
  fetchedAt: string;
  updateFrequency: string;
  freshness: "realtime" | "delayed" | "latest_available" | "stale" | "unavailable";
  reliability: "official" | "high" | "medium" | "low";
  status: string;
};

export type MinuteBar = {
  timestamp: string;
  time: string;
  close: number;
  volume: number;
  turnover: number;
  cumulativeVolume: number;
  cumulativeTurnover: number;
};

export type MarketEvent = {
  id: string;
  startTime: string;
  endTime: string;
  indexStart: number;
  indexEnd: number;
  change: number;
  changePct: number;
  volumeChange: number | null;
  eventType: string;
  kind: "warning" | "turn" | "break";
  category: string;
  title: string;
  relatedStocks: Array<{ code: string; name: string; changePct: number }>;
  crossMarketMoves: Array<{ key: string; name: string; changePct: number }>;
  relatedNews: Array<{ eventId: string; headline: string; publisher: string; publishedAt: string }>;
  technicalContext: string;
  possibleExplanation: string;
  evidence: string[];
  attributionLevel: "confirmed" | "strongly_related" | "possible" | "structural" | "unknown";
  confidence: "high" | "medium" | "low";
  pointIndex: number;
};

export type Constituent = {
  code: string;
  name: string;
  officialName?: string;
  industry: string;
  weight: number;
  last: number | null;
  changePct: number | null;
  turnover?: number | null;
  timestamp?: string | null;
  contributionPoints: number | null;
  contributionType: "exact" | "estimated" | "unavailable";
  contributionMethodology?: string | null;
};

export type CrossMarket = {
  key: string;
  symbol: string;
  name: string;
  value: number;
  changePct: number | null;
  timestamp: string;
  marketSessionDate: string;
  sessionRelationship: "same_session" | "overnight" | "continuous";
  freshness: string;
  source: SourceMeta;
};

export type WatchItem = {
  id: string;
  conditionType: string;
  conditionTypeLabel?: string;
  group?: "message" | "capital" | "market";
  label: string;
  subject: string;
  operator: string;
  threshold: number;
  displayValue?: string;
  durationMinutes: number;
  status: "pending" | "triggered" | "validated" | "failed" | "invalidated";
  triggeredAt: string | null;
  expected: string;
  positive: string;
  negative: string;
  action: string;
  subsequentPerformance?: number | null;
  validationResult: string;
  valueType: string;
  importance?: "critical" | "high" | "medium" | "low";
  eventAt?: string | null;
  newsEventId?: string | null;
  impactDirection?: string | null;
  inheritedFromReportId?: string | null;
  source?: SourceMeta | null;
};

export type ScoreCard = {
  status: "calculated" | "unavailable";
  reason?: string;
  total?: number;
  label?: string;
  previousTotal?: number | null;
  delta?: number | null;
  movement?: "up" | "down" | "flat" | "baseline";
  confidence?: number;
  asOf?: string | null;
  judgment?: string;
  dimensions: Array<{ key: string; label: string; score: number; weight: number; reason: string; status: string }>;
  targets: {
    short: ScoreTarget;
    medium: ScoreTarget;
    long: ScoreTarget;
  };
  methodology?: string;
  valueType?: string;
};

export type ScoreTarget = {
  point: number;
  rangeLow: number;
  rangeHigh: number;
  horizon: string;
  direction: "up" | "down" | "flat";
  basis: string;
  invalidation: number;
};

export type DashboardSnapshot = {
  schemaVersion: number;
  reportId: string;
  tradingDate: string;
  session: SessionKey;
  sessionLabel: string;
  nominalTime: string;
  marketCutoff: string;
  generatedAt: string;
  timezone: string;
  overallStatus: "ok" | "partial" | "source_error";
  index: Record<string, unknown> & { last?: number; changePct?: number; high?: number; low?: number; timestamp?: string; source?: SourceMeta };
  minuteBars: MinuteBar[];
  constituents: Constituent[];
  breadth: { advances: number; declines: number; unchanged: number; available: number; universe: number; status: string; methodology: string };
  crossMarkets: CrossMarket[];
  capitalFlows: Array<{ key: string; label: string; value: number | null; unit: string; period: string; status: string; source: SourceMeta | null }>;
  news: Array<{ eventId: string; headline: string; publisher: string; url: string; publisherUrl: string | null; publishedAt: string; fetchedAt: string; category: string; channel?: string; relatedAssets: string[]; whyRelevant?: string; impactDirection: string; impactWeight: string; impactMethodology: string; sourceReliability: string; sourceType: string }>;
  events: MarketEvent[];
  watchlist: WatchItem[];
  scoreCard?: ScoreCard;
  technical: { movingAverages: Record<string, number | null>; below: string[]; state: string; valueType: string };
  judgment: { title: string; summary: string; short: string; medium: string; validation: string; analysisType: string; confidence: string };
  metrics: Array<{ key: string; label: string; value: string | number | null; unit: string; badge: string; tone: string; note: string; source: SourceMeta | null }>;
  sourceStatus: SourceMeta[];
  sourceErrors: Array<{ sourceId: string; instrument?: string; message: string }>;
  availability?: { latestDate: string; latestSession: SessionKey; available: Record<string, SessionKey[]>; updatedAt: string };
};
