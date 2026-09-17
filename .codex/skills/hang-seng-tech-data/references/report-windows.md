# Report windows and inheritance

All cutoffs use `Asia/Hong_Kong`.

## 08:30 morning report

- Market-data cutoff: 08:20 unless a source has a later explicit cutoff.
- News window begins at the previous generated Hong Kong report's cutoff, not at midnight.
- Select the latest fully completed US session before 08:20.
- Include the first approximately 30 minutes of Japan and Korea trading when available.
- On Monday, the default news window is Friday 17:00 through Monday 08:20, so weekend policy, corporate, and geopolitical developments are included.
- When US and Hong Kong holidays differ, use each exchange's own calendar. Never infer the previous session using calendar-day subtraction.
- Output today's opening hypotheses, invalidation conditions, and Watchlist items. Do not show same-day HK intraday bars before the session occurs.

## 12:30 midday report

- Price window: 09:30–12:00 Hong Kong morning session.
- Collection should begin after the morning close and complete with margin before 12:30.
- Validate morning OHLC, minute-bar completeness, volume, component coverage, market breadth, and cross-market comparisons.
- Reconcile every morning Watchlist item to `triggered`, `not_triggered`, `invalidated`, or `pending` and keep the evidence.
- Produce afternoon scenarios and conditions; do not use afternoon data.

## 17:00 evening report

- Price window: the completed Hong Kong cash session, normally 09:30–12:00 and 13:00–16:00.
- Use only values available before the report cutoff. Mark late official files `pending_official` rather than backfilling them invisibly.
- Close morning and midday Watchlist items, preserve unresolved items, and create the next-session Watchlist.
- Preserve the original 17:00 snapshot. Later official corrections create a new revision with lineage.

## Non-standard days

- Skip Hong Kong market reports on full holidays, while optionally producing a dated event brief if material news exists.
- On half-days, use the official session calendar and adapt the midday/evening workflow rather than assuming a 16:00 close.
- If the Mac was asleep at a cutoff, run a catch-up job on wake and label the snapshot with actual generation time.
