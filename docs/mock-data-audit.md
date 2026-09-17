# Mock Data Audit

Audit date: 2026-09-17

## Current implementation

The application is a single Next.js client component (`src/components/Dashboard.tsx`). It has no API routes, persistence layer, scheduled collector, or production data adapter. Every displayed market value is currently a hardcoded demonstration value.

## Mock data locations

| Constant/state | Current purpose | Production replacement |
| --- | --- | --- |
| `points` | HSTECH intraday line | Normalized minute bars for the selected report window |
| `volumes` | Intraday volume bars | Minute turnover/volume from the same market-data source and time grid |
| `events` | Chart event markers and event detail | Event Engine output with source evidence and attribution tier |
| `watchItems` | Watchlist cards | Persisted executable conditions and evaluation records |
| `contributors`, `morningContributors`, `middayContributors` | Component contribution preview | Constituent snapshot, official weights where available, and exact/estimated contribution status |
| `constituentRows` | 30-stock drill-down modal | Current official constituent universe plus latest quote fields |
| `markets`, `marketBySession` | Cross-market panel | Timestamped normalized cross-market observations |
| `newsBySession` | News and market context | Event Feed retaining original headline, publisher, URL, publish time, fetch time, and related assets |
| `fundFlowsBySession` | Capital-flow panel | Timestamped Stock Connect and short-selling observations with definitions and units |
| `metricsBySession` | Eight summary cards | Derived view model backed by normalized observations |
| `summaries` | Closing/period judgment | Rule-derived facts plus explicitly labelled AI analysis |
| `branches` and hardcoded scenario markup | Scenario/position plan | Daily Market State hypotheses, conditions, invalidation, and result tracking |
| `reportDate === "2026-09-15"` | Only available date | Snapshot index from storage |

## Non-production behaviours to remove

- “演示数据已载入” does not identify a source or timestamp.
- The 08:30 and 12:30 views reconstruct data from a single evening-report sample.
- Missing data is replaced by copy rather than represented as unavailable.
- Contribution points, correlations, valuations, futures basis, and fund flows have no machine-verifiable lineage.
- News text has no original URL or publisher record.
- Watchlist states are labels rather than executable conditions.
- The chart linkage uses one static event collection for all report sessions.

## Production rule

Mock data may remain only in explicit development fixtures. A production snapshot must never fall back silently to mock values. Missing or stale fields must carry a visible state: `unavailable`, `delayed`, `stale`, or `source_error`, including the last successful timestamp when known.
