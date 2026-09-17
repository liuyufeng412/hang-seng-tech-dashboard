from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline.collect import _watchlist, rebuild_runtime_index
from pipeline.event_engine import detect_events
from pipeline.scheduler import expected_reports, report_quality
from pipeline.sources import _news_dedupe_key, _news_relevance, news_window


HKT = ZoneInfo("Asia/Hong_Kong")


class EventEngineTests(unittest.TestCase):
    def test_detects_dynamic_move_without_forcing_event_count(self) -> None:
        start = datetime(2026, 9, 16, 9, 30, tzinfo=HKT)
        bars = []
        cumulative_turnover = 0.0
        for index in range(80):
            price = 4300 + index * 0.1
            if 30 <= index <= 35:
                price -= (index - 29) * 5
            turnover = 100_000_000 if index == 35 else 10_000_000
            cumulative_turnover += turnover
            timestamp = start + timedelta(minutes=index)
            bars.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "time": timestamp.strftime("%H:%M"),
                    "close": price,
                    "turnover": turnover,
                    "cumulativeTurnover": cumulative_turnover,
                }
            )
        events = detect_events(bars, {}, [], [], [])
        self.assertTrue(any(event["eventType"] in {"rapidDrop", "volumeSpike", "breakdown"} for event in events))
        for event in events:
            self.assertIn(event["attributionLevel"], {"confirmed", "strongly_related", "possible", "structural", "unknown"})
            self.assertTrue(event["evidence"])


class NewsFeedTests(unittest.TestCase):
    def test_evening_news_window_covers_the_full_calendar_day(self) -> None:
        start, end = news_window("2026-09-16", "evening")
        self.assertEqual(start.strftime("%Y-%m-%d %H:%M"), "2026-09-16 00:00")
        self.assertEqual(end.strftime("%Y-%m-%d %H:%M"), "2026-09-16 17:00")

    def test_hang_seng_and_sector_headlines_pass_relevance_filter(self) -> None:
        self.assertGreaterEqual(_news_relevance("恒指高开，科指上涨，科技股个别发展"), 2)
        self.assertGreaterEqual(_news_relevance("港股高收，晶片及AI相关股份造好"), 2)

    def test_syndicated_headline_suffixes_are_deduplicated(self) -> None:
        title = "〈港股盤後〉恒指探底回升漲0.19% AI硬體與半導體股全線走強"
        syndicated = title + " - 財經新聞"
        self.assertEqual(_news_dedupe_key(title), _news_dedupe_key(syndicated))


class SnapshotContractTests(unittest.TestCase):
    def test_backfilling_morning_does_not_replace_newer_midday_as_latest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            report_dir = runtime / "reports" / "2026-09-17"
            report_dir.mkdir(parents=True)
            for session in ("morning", "midday"):
                (report_dir / f"{session}.json").write_text(
                    json.dumps({"session": session, "tradingDate": "2026-09-17"}),
                    encoding="utf-8",
                )
            rebuild_runtime_index(runtime)
            index = json.loads((runtime / "index.json").read_text(encoding="utf-8"))
            latest = json.loads((runtime / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(index["latestSession"], "midday")
            self.assertEqual(latest["session"], "midday")

    def test_watchlist_filters_out_non_material_daily_candidates(self) -> None:
        cutoff = datetime(2026, 11, 1, 17, 0, tzinfo=HKT)
        items = _watchlist(
            {"last": 5000, "changePct": 0.1, "timestamp": cutoff.isoformat()},
            [],
            [{"date": "2026-10-30", "high": 5600, "low": 4400}],
            "2026-11-01",
            "evening",
            {"advances": 15, "declines": 15, "unchanged": 0, "available": 30},
            [
                {"key": "southbound", "value": 1.2, "unit": "亿元人民币", "source": None},
                {"key": "shortSelling", "value": 15.0, "unit": "%", "source": None},
            ],
            cutoff,
        )
        self.assertEqual(items, [])

class SchedulerTests(unittest.TestCase):
    def test_expected_reports_include_only_due_sessions(self) -> None:
        before_open = datetime(2026, 9, 17, 8, 0, tzinfo=HKT)
        after_midday = datetime(2026, 9, 17, 12, 35, tzinfo=HKT)
        self.assertEqual(expected_reports(before_open), [("2026-09-16", "evening")])
        self.assertEqual(
            expected_reports(after_midday),
            [("2026-09-17", "morning"), ("2026-09-17", "midday")],
        )

    def test_report_quality_accepts_complete_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "morning.json"
            path.write_text(
                json.dumps(
                    {
                        "session": "morning",
                        "tradingDate": "2026-09-17",
                        "generatedAt": "2026-09-17T08:30:00+08:00",
                        "index": {"last": 5000},
                        "constituents": [{}] * 30,
                        "sourceStatus": [{"sourceId": "test"}],
                        "crossMarkets": [{}] * 10,
                        "news": [{"eventId": "test"}],
                    }
                ),
                encoding="utf-8",
            )
            quality, issues, _ = report_quality(path, "morning", "2026-09-17")
            self.assertEqual(quality, "ready", issues)


if __name__ == "__main__":
    unittest.main()
