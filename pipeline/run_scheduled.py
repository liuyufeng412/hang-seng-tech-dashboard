from __future__ import annotations

import argparse
from datetime import datetime

import exchange_calendars as xcals
import pandas as pd

from pipeline.collect import SESSIONS, collect
from pipeline.sources import HKT


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate one scheduled Hang Seng TECH report")
    parser.add_argument("--session", choices=SESSIONS, required=True)
    parser.add_argument("--date", help="Optional YYYY-MM-DD override for backfills")
    args = parser.parse_args()
    trading_date = args.date or datetime.now(HKT).date().isoformat()
    calendar = xcals.get_calendar("XHKG")
    if not calendar.is_session(pd.Timestamp(trading_date)):
        print(f"SKIPPED {trading_date}: not an XHKG trading session")
        return
    paths = collect(trading_date, (args.session,))
    print(f"GENERATED {trading_date} {args.session}")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
