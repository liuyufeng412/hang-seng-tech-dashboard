# Phase 2 Implementation Report

Generated: 2026-09-17 HKT

## Completed

- Production dashboard reads versioned JSON snapshots through `/api/dashboard`; it has no runtime fallback to the former hardcoded demo.
- Three report snapshots exist for 2026-09-16: morning, midday and evening.
- HSTECH minute price and turnover bars: 151 morning-session bars in the midday report and 332 full-session bars in the evening report.
- Official 30-member universe and monthly weights, 30/30 quote coverage, market breadth and explicitly estimated contribution points.
- Fifteen cross-market instruments, including HSI, HSCEI, mainland growth indices, Nikkei, KOSPI, Nasdaq, NDX, SOX, HXC, USD/CNH, US 10-year yield and Brent.
- Southbound daily and intraday vendor series; HKEX official full-day short-selling ratio.
- Filtered news Event Feed retaining original title, publisher/domain, aggregator URL, published time and fetch time.
- Event Engine for rapid rise/drop, reversal, breakout/breakdown, volume spike and failed breakout/breakdown, with cautious attribution tiers and evidence.
- Chart Event Marker hover/click linkage, related-constituent highlighting, cross-market window evidence and event detail.
- Executable Watchlist conditions with pending/triggered/validated state, trigger time, longest duration and subsequent performance.
- Source lineage panel and visible unavailable/delayed/latest-available states.
- Active local scheduled runs at 08:30, 12:30 and 17:00; the runner uses the XHKG calendar and skips non-trading days.

## Verification

- Type check and optimized Next.js build passed.
- Python event and snapshot contract tests passed.
- All three API endpoints returned HTTP 200; invalid parameters returned HTTP 400.
- Browser verification found eight metric cards, 17 evening Event Markers, 30 modal constituent rows, working Event selection, working Watchlist selection and no page errors or failed network responses.
- 2026-09-16 HSTECH minute close `4325.45` matched the independent Sina daily close.

## Runtime sources

| Data | Source | Current label | Update/observation rule |
| --- | --- | --- | --- |
| Membership, weight, PE | Hang Seng Indexes Company factsheet | Official, latest available | Monthly factsheet; membership review quarterly |
| HSTECH and constituent minutes/quotes | Tencent Finance | Delayed | Approximately minute observations during the session; vendor has no public SLA |
| HSTECH daily history | Sina Finance through AKShare | Latest available | End of day |
| Southbound flow | Eastmoney through AKShare | Delayed estimate / latest available | Intraday vendor estimate and daily final series |
| HK short selling | HKEX Main Board Daily Quotations | Official, latest available | Full-day report after market close |
| Global and cross-market observations | Yahoo Finance chart endpoint | Delayed | Vendor-defined; each observation retains its own timestamp |
| News discovery | Google News RSS | Latest available, aggregator | Publisher-dependent; original publisher is retained |

## Not completed or deliberately unavailable

- Exact official constituent contribution: displayed estimates use official weight × constituent return × prior index close.
- HSTECH futures basis: no free source with stable contract/roll definitions has passed validation.
- Index PB and historical valuation percentile: no reliable free source has passed provenance checks.
- Historical midday HKEX short-selling ratio: the full-day report is available, but past half-day values cannot be reconstructed safely.
- Confirmed causal news attribution remains rare by design; most detected events are structural, possible or unknown until evidence is sufficient.

## Known limits

- Tencent, Sina, Yahoo, Eastmoney and Google News are public endpoints without a paid service-level agreement and can change or throttle access.
- Google News links are aggregator article URLs; the publisher domain and publisher identity are stored separately.
- The current archive begins on 2026-09-16. Historical date selection expands automatically as scheduled reports accumulate.

## Highest-value next work

1. Add a licensed market-data provider for HSTECH futures, exact index contribution and a documented latency SLA.
2. Add official macro-release calendars and direct official release feeds so news attribution can move from possible to strongly related/confirmed more often.
3. Accumulate at least 60 trading days, then add valuation percentiles, rolling correlations and event-pattern backtests without look-ahead bias.
