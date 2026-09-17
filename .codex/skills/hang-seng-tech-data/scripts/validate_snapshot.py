#!/usr/bin/env python3
"""Validate a normalized market-data snapshot without making network requests."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED_ENVELOPE = ("datasetId", "sourceId", "market", "timezone", "asOf", "retrievedAt", "instruments")
REQUIRED_BAR = ("timestamp", "open", "high", "low", "close", "volume")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate(snapshot: dict[str, Any], minimum_instruments: int = 1) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    for field in REQUIRED_ENVELOPE:
        if field not in snapshot:
            errors.append(f"missing envelope field: {field}")

    instruments = snapshot.get("instruments")
    if not isinstance(instruments, list):
        errors.append("instruments must be a list")
        instruments = []
    if len(instruments) < minimum_instruments:
        errors.append(f"instrument coverage {len(instruments)} is below required {minimum_instruments}")

    seen_symbols: set[str] = set()
    bar_count = 0
    for instrument in instruments:
        symbol = instrument.get("symbol") if isinstance(instrument, dict) else None
        if not symbol:
            errors.append("instrument missing symbol")
            continue
        if symbol in seen_symbols:
            errors.append(f"duplicate instrument: {symbol}")
        seen_symbols.add(symbol)
        bars = instrument.get("bars", [])
        if not isinstance(bars, list):
            errors.append(f"{symbol}: bars must be a list")
            continue
        previous_timestamp: datetime | None = None
        for index, bar in enumerate(bars):
            bar_count += 1
            missing = [field for field in REQUIRED_BAR if field not in bar]
            if missing:
                errors.append(f"{symbol} bar {index}: missing {', '.join(missing)}")
                continue
            try:
                timestamp = datetime.fromisoformat(str(bar["timestamp"]).replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{symbol} bar {index}: invalid timestamp")
                continue
            if timestamp.tzinfo is None:
                errors.append(f"{symbol} bar {index}: timestamp has no timezone")
            if previous_timestamp and timestamp <= previous_timestamp:
                errors.append(f"{symbol} bar {index}: timestamps are not strictly increasing")
            previous_timestamp = timestamp

            numeric_fields = ("open", "high", "low", "close", "volume")
            if not all(_finite_number(bar[field]) for field in numeric_fields):
                errors.append(f"{symbol} bar {index}: non-finite numeric value")
                continue
            if bar["low"] > min(bar["open"], bar["close"]) or bar["high"] < max(bar["open"], bar["close"]):
                errors.append(f"{symbol} bar {index}: invalid OHLC relationship")
            if bar["volume"] < 0 or (_finite_number(bar.get("turnover")) and bar["turnover"] < 0):
                errors.append(f"{symbol} bar {index}: negative volume or turnover")

    if instruments and bar_count == 0:
        warnings.append("snapshot contains instruments but no bars")

    state = "failed" if errors else "passed_with_warnings" if warnings else "passed"
    return {
        "state": state,
        "instrumentCount": len(instruments),
        "barCount": bar_count,
        "errors": errors,
        "warnings": warnings,
    }


def self_test() -> int:
    sample = {
        "datasetId": "self-test",
        "sourceId": "fixture",
        "market": "HK",
        "timezone": "Asia/Hong_Kong",
        "asOf": "2026-09-15T12:00:00+08:00",
        "retrievedAt": "2026-09-15T12:15:00+08:00",
        "instruments": [{
            "symbol": "0700.HK",
            "bars": [{"timestamp": "2026-09-15T09:30:00+08:00", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10, "turnover": 20}],
        }],
    }
    result = validate(sample)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["state"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a normalized Hang Seng TECH dataset snapshot")
    parser.add_argument("snapshot", nargs="?", type=Path)
    parser.add_argument("--minimum-instruments", type=int, default=1)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.snapshot:
        parser.error("snapshot path is required unless --self-test is used")
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    result = validate(snapshot, args.minimum_instruments)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["state"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
