from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.collect import RUNTIME_ROOT, SESSIONS
from pipeline.sources import get_news_feed, iso_now, news_window


def refresh_news(trading_date: str, sessions: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for session in sessions:
        path = RUNTIME_ROOT / "reports" / trading_date / f"{session}.json"
        if not path.exists():
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        start, end = news_window(trading_date, session)
        news, source = get_news_feed(start, end)
        snapshot["news"] = news
        snapshot["newsRefreshedAt"] = iso_now()
        sources = [item for item in snapshot.get("sourceStatus", []) if item.get("sourceId") != "google_news_rss"]
        if source:
            sources.append(source)
        snapshot["sourceStatus"] = sources
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(path)
        if session == snapshot.get("availability", {}).get("latestSession", "evening") or session == "evening":
            (RUNTIME_ROOT / "latest.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh report news without refetching market data")
    parser.add_argument("--date", required=True)
    parser.add_argument("--session", choices=(*SESSIONS, "all"), default="all")
    args = parser.parse_args()
    sessions = SESSIONS if args.session == "all" else (args.session,)
    for path in refresh_news(args.date, sessions):
        print(path)


if __name__ == "__main__":
    main()
