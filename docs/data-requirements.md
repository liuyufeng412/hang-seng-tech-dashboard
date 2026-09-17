# Dashboard Data Requirements

Audit date: 2026-09-17

## Common provenance envelope

Every externally sourced or calculated field must include, directly or through a referenced observation:

- `sourceId`, `sourceName`, `sourceType`, `sourceUrl`
- `originalTimestamp`, `fetchedAt`, `updateFrequency`
- `freshness`: `realtime | delayed | latest_available | stale | unavailable`
- `valueType`: `observed | calculated | estimated | ai_analysis`
- `reliability`: `official | high | medium | low`
- `status`: `ok | partial | source_error | not_published`
- `unit`, `currency`, `timezone`, and a human-readable `methodology` when calculated

## Report identity and availability

- Trading date, report session (`morning | midday | evening`), nominal report time, generated time, market calendar state
- Available report dates and available sessions per date
- Snapshot version, pipeline run identifier, overall freshness, partial-data warnings, source errors

## Closing/period judgment

- Headline, intraday summary, short-term conclusion, medium-term conclusion
- Evidence references, confidence, analysis timestamp, analysis type
- Hypothesis/tracking ID and validation state

## Eight overview metrics

1. HSTECH last/reference level, point change, percent change, OHLC, previous close
2. Turnover/volume with prior-period comparison
3. Market breadth: advances, declines, unchanged, universe count
4. Southbound flow: gross/net definition, amount, period and publication state
5. Valuation: PE, PB, percentile, percentile lookback and methodology
6. Short-selling: amount/ratio, market/index scope and reporting delay
7. Technical state: position versus named moving averages and key levels
8. Derivatives/cross-market signal: HSTECH futures basis or the most relevant available driver, with contract and timestamp

Unavailable metrics remain visible with an explanation; they are not fabricated.

## Intraday trend, volume and reasons

- Minute bars: timestamp, open, high, low, close, volume, turnover, session, source status
- Previous close, VWAP if source fields support it, support/resistance and how each level was derived
- Comparable volume baseline and volume-ratio methodology
- Event markers: type/category/severity/time range/price and volume changes
- Hover detail: time, move, turnover change, event type, related constituents, cross-market moves, contemporaneous news, possible explanation, evidence, attribution tier/confidence
- Click state: selected event ID and a shared analysis window used by all linked modules

## Constituent contribution and drill-down

- Official constituent effective date, code, name, industry/theme and official weight when available
- Last price, previous close, percent change, turnover, observation time and freshness
- Contribution value, unit and `contributionType`: `exact | estimated | unavailable`
- Estimate methodology and confidence; never label an estimate as exact
- Event-window price move and anomaly note with evidence reference
- Breadth computed from the same constituent universe and timestamp

## Cross-market panel

For HSI, HSCEI, SSE Composite, Shenzhen Component, ChiNext, STAR-related index, Nikkei 225, KOSPI, Nasdaq Composite, Nasdaq 100, SOX, Nasdaq Golden Dragon China, USD/CNH, US 10-year yield, and Brent:

- Symbol, name, market/timezone, last/reference value, change percent, market status
- Observation time, session relationship (`same_session | overnight | prior_close`), freshness
- Minute bars where available and justified
- Event-window move, correlation value, correlation lookback/frequency/methodology when displayed

## Capital flows

- Southbound/Stock Connect direction and route, buy/sell/net definitions, currency and period
- Historical daily series and last comparable period
- HK market short-selling amount/ratio with scope and publication time
- Optional company-level short-selling only when the source and denominator are clear
- Each flow record must identify whether it is official published data or a vendor calculation

## Event Feed

- `eventId`, original headline, publisher/source, canonical URL
- Original publish time, fetched time, update time, language
- Related assets/topics, event category, geographic scope
- Source reliability and duplicate-cluster ID
- Direction/importance/time-horizon fields are calculations or AI analysis and must be labelled accordingly
- The original item is always retained alongside any summary

## Event Engine

- `rapidRise`, `rapidDrop`, `reversal`, `breakout`, `breakdown`, `volumeSpike`, `failedBreakout`, `failedBreakdown`
- Start/end time, start/end index, point and percent change, volume/turnover change
- Detection thresholds, volatility regime and technical context
- Related constituents, cross-market observations, related Event Feed items
- Possible explanation, evidence IDs, attribution tier (`confirmed | strongly_related | possible | structural | unknown`), confidence
- No fixed event count and no causal wording without evidence

## Watchlist and scenarios

- Condition type, subject/instrument, operator, threshold, duration and evaluation window
- Status: `pending | triggered | validated | failed | invalidated`
- Created source/session, trigger time, validation time, invalidation rule
- Expected outcome/range, interpretation guide, action text, risk/reward inputs where applicable
- Subsequent performance and validation result
- Inheritance links from morning hypothesis to midday check to evening result and next-day condition

## Unified Daily Market State

- One trading-day entity owns all observations, hypotheses, events, watch conditions and validations
- Morning: overnight observations, weekend carry for Monday, opening hypotheses and watch conditions
- Midday: morning observations/events, morning-hypothesis checks, afternoon watch conditions
- Evening: full-day observations/events, midday checks, daily review and next-session watch conditions
- Lineage is explicit: `hypothesisId -> conditionId -> triggerId -> validationId -> result`

## Source window rules

- 08:30 uses the most recent completed sessions. Monday morning includes Friday US close and weekend events.
- 12:30 only treats observations at or before the collection cutoff as available.
- 17:00 uses the completed Hong Kong cash session; sources published later are marked pending and may be backfilled without rewriting the original generation timestamp.
