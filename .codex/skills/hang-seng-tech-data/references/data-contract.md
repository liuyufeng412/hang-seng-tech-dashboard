# Snapshot data contract

Store immutable raw responses separately from normalized snapshots. A report may reference multiple datasets, but every displayed number must resolve to a dataset and observation.

## Dataset envelope

```json
{
  "datasetId": "hk-minute-2026-09-15-midday-akshare",
  "sourceId": "akshare_eastmoney",
  "role": "candidate",
  "market": "HK",
  "timezone": "Asia/Hong_Kong",
  "asOf": "2026-09-15T12:00:00+08:00",
  "retrievedAt": "2026-09-15T12:18:00+08:00",
  "quality": {
    "state": "provisional",
    "fresh": true,
    "coverage": 0.997,
    "issues": []
  },
  "instruments": []
}
```

## Instrument and bar

```json
{
  "symbol": "0700.HK",
  "name": "腾讯控股",
  "bars": [
    {
      "timestamp": "2026-09-15T09:30:00+08:00",
      "open": 0,
      "high": 0,
      "low": 0,
      "close": 0,
      "volume": 0,
      "turnover": 0
    }
  ]
}
```

Zero values above are schema placeholders only, not market examples.

## Report snapshot

Required top-level fields:

- `reportId`, `reportDate`, `session`, `cutoffAt`, `generatedAt`, `revision`;
- `datasets` containing referenced dataset IDs and quality states;
- `metrics`, `events`, `contributors`, `crossMarkets`, `watchlist`, `scenarios`, and `news`;
- `qualitySummary` with blocking, provisional, and missing sections;
- `previousReportId` for inheritance.

Each event must separate observation, correlation, attribution, evidence, and confidence. Each Watchlist item must retain its stable ID, prior state, new state, trigger condition, invalidation condition, and evidence IDs.
