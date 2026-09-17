# Source policy

## Source roles

| Role | Meaning | May drive report numbers |
|---|---|---|
| canonical | Exchange, index compiler, regulator, central bank, or original statistical agency | Yes |
| primary | Accepted structured provider with measured freshness and reconciliation history | Yes |
| secondary | Independent check or fallback | Yes, with quality flag |
| discovery | Search engine, news aggregation, or unverified community source | No |

## Current registry decisions

- HSI official: canonical for HSTECH constituents, published weights, methodology, and index facts.
- HKEX official: canonical for trading calendar, exchange statistics, short-selling publications, Connect statistics, and official end-of-day files.
- AKShare/Eastmoney: candidate for Hong Kong intraday bars and snapshots. It must pass daily structural validation and periodic official reconciliation.
- TickDB: candidate for intraday and cross-market data. Do not approve until its free-key coverage, timestamps, HSTECH symbols, constituent coverage, latency, and source provenance are measured.
- FTShare: candidate for structured Hong Kong, Connect, macro, and news endpoints. Access and usable fields depend on its account tier.
- yfinance/Yahoo: secondary source for overseas equities and benchmarks; not sufficient alone for report-critical HK fields.
- FRED: canonical/primary for published US macro series, subject to the series' own release lag.
- Web search: discovery channel for news and original documents only.

## Acceptance thresholds

Evaluate a candidate over at least five Hong Kong trading days.

- Critical instrument coverage: 100% for HSTECH plus the current 30 constituents when the source claims that coverage.
- Minute-bar completeness: at least 99% of expected in-session bars after accounting for suspensions and provider timestamp conventions.
- OHLC consistency: `low <= open/close <= high`; volume and turnover must be non-negative.
- Timestamp correctness: Asia/Hong_Kong for HK sessions, with no lunch-break bars unless explicitly labeled.
- Freshness: data required for the 12:30 report should be available by 12:20–12:25; closing data should be available with sufficient margin before 17:00.
- Reconciliation: report-critical closing prices and index levels must match an independent accepted source within the instrument's rounding convention.
- Reliability: failed or incomplete runs must be visible; retries must be bounded and recorded.

Passing technical checks does not prove redistribution rights. Keep the dashboard local and review provider terms before any public or commercial deployment.

## Search and news policy

For each discovered item retain:

- original URL and publisher;
- published time and timezone;
- discovery time;
- report coverage window;
- affected assets or indicators;
- factual summary separated from inferred market impact;
- evidence strength and any conflicting reports.

Search snippets are never evidence by themselves. Open the source. If no original or reputable corroboration is available, label the item unverified and exclude it from high-confidence attribution.
