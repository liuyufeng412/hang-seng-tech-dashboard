---
name: hang-seng-tech-data
description: Collect, validate, and package Hang Seng TECH market, constituent, cross-market, macro, and news data for the dashboard's 08:30, 12:30, and 17:00 reports. Use for source onboarding, scheduled report data, source-health checks, Watchlist inheritance, and evidence-backed event attribution.
---

# Hang Seng TECH Data

Build reproducible report snapshots, not ad-hoc answers. Keep raw values, normalized values, source metadata, validation results, and narrative output separate.

## Non-negotiable rules

- Never obtain price, volume, index level, constituent weight, fund flow, or valuation numbers from search-result snippets or generated prose.
- Use structured sources for numerical series. Web search is for discovering news and original documents, then cite the original publisher.
- Record `sourceId`, `asOf`, `retrievedAt`, timezone, unit, and quality state for every dataset.
- Do not silently substitute one instrument for another. For example, Nasdaq 100 is not the Nasdaq Golden Dragon China Index.
- Never invent missing values. Mark them `unavailable`, `stale`, `conflicted`, or `pending_official`.
- Critical source failure blocks the affected calculation; it must not block unrelated report sections.
- Calculations are deterministic. Language models may summarize evidence but may not create or modify market numbers.

## Operating modes

1. **Source onboarding or audit:** Read [references/source-policy.md](references/source-policy.md), update the source registry, and run the snapshot validator before approving a provider.
2. **Report collection:** Read [references/report-windows.md](references/report-windows.md) and collect only information available before the requested cutoff.
3. **Snapshot or UI integration:** Read [references/data-contract.md](references/data-contract.md) and preserve the defined lineage and quality fields.
4. **News and event attribution:** Search within the session's coverage window. Prefer HKEXnews, company investor relations, government/statistical agencies, central banks, and original releases. Use media reporting as secondary context. Keep fact, correlation, and causal inference distinct.

## Provider policy

- Official HSI/HKEX material is canonical for index membership, published weights, exchange statistics, and official calendars.
- Public-data libraries such as AKShare are candidate adapters, not canonical sources. Validate coverage and values against an independent reference.
- Vendor Skills or APIs such as TickDB or FTShare remain candidates until latency, provenance, coverage, and stability pass acceptance testing.
- Yahoo/yfinance may provide global-market backup data but cannot be the only source for report-critical Hong Kong fields.
- FRED and original statistical agencies are preferred for macroeconomic history and release metadata.

## Output gate

Before a report snapshot is marked ready:

- required datasets pass freshness and schema checks;
- OHLC relationships and timestamps are valid;
- expected instrument coverage and bar coverage meet the session threshold;
- critical values either reconcile with a second source or carry an explicit provisional flag;
- every event attribution references evidence available before the cutoff;
- Watchlist state transitions are retained from the prior report rather than regenerated from scratch.
