from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline.collect import _flow_snapshot, _inherited_message_watchlist, _news_watch_items, _score_card, _watchlist, rebuild_runtime_index
from pipeline.event_engine import detect_events
from pipeline.scheduler import expected_reports, report_quality
from pipeline.sources import _news_category, _news_dedupe_key, _news_relevance, news_window


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

    def test_material_company_news_becomes_a_message_watch_item(self) -> None:
        cutoff = datetime(2026, 9, 22, 16, 0, tzinfo=HKT)
        items = _news_watch_items([{
            "eventId": "news-alibaba-ai",
            "headline": "阿里巴巴将投入AI基础设施并发布新一代AI芯片",
            "publisher": "测试财经媒体",
            "url": "https://example.com/alibaba-ai",
            "publishedAt": "2026-09-22T15:36:00+08:00",
            "fetchedAt": "2026-09-22T16:00:00+08:00",
            "category": "公司 / 行业",
            "relatedAssets": ["阿里巴巴"],
            "impactDirection": "偏多",
            "impactWeight": "高",
            "relevanceScore": 7,
            "sourceReliability": "high",
            "sourceType": "news_aggregator_with_original_publisher",
        }], cutoff)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["group"], "message")
        self.assertEqual(items[0]["conditionType"], "newsCatalyst")
        self.assertIn("量价", items[0]["positive"])
        self.assertEqual(items[0]["source"]["sourceUrl"], "https://example.com/alibaba-ai")

    def test_plain_market_recap_does_not_become_future_focus(self) -> None:
        cutoff = datetime(2026, 9, 22, 16, 0, tzinfo=HKT)
        items = _news_watch_items([{
            "eventId": "news-recap",
            "headline": "恒指走势：港股高开后升逾百点",
            "publisher": "测试财经媒体",
            "url": "https://example.com/recap",
            "publishedAt": "2026-09-22T10:00:00+08:00",
            "category": "市场动态",
            "relatedAssets": [],
            "impactDirection": "待验证",
            "impactWeight": "中",
            "relevanceScore": 4,
            "sourceReliability": "high",
        }], cutoff)
        self.assertEqual(items, [])

    def test_traditional_chinese_fed_headline_is_classified_as_rates(self) -> None:
        self.assertEqual(_news_category("美聯儲加息預期增強，美債殖利率上升"), "央行 / 利率")


class SnapshotContractTests(unittest.TestCase):
    def test_weak_score_projects_targets_below_current_price(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=HKT)
        daily = []
        for index in range(130):
            close = 5200 - index * 8
            daily.append({
                "date": (start + timedelta(days=index)).strftime("%Y-%m-%d"),
                "open": close + 15,
                "high": close + 30,
                "low": close - 35,
                "close": close,
                "turnover": 80_000_000_000,
            })
        card = _score_card(
            {"last": 4000, "changePct": -2.0, "timestamp": "2026-05-20T16:00:00+08:00"},
            daily,
            "2026-05-20",
            "evening",
            {"advances": 5, "declines": 25, "unchanged": 0, "available": 30},
            [{"weight": 1, "changePct": -2.0} for _ in range(30)],
            [{"key": "southbound", "value": -50}],
            [
                {"key": "hxc", "changePct": -2.0}, {"key": "ndx", "changePct": -1.0},
                {"key": "nasdaq", "changePct": -1.0}, {"key": "us10y", "changePct": 2.0},
                {"key": "usdcnh", "changePct": 0.5}, {"key": "kospi", "changePct": -1.0},
                {"key": "brent", "changePct": 2.0},
            ],
            {"peRatio": 35.0},
            {"movingAverages": {"ma5": 4200, "ma20": 4400, "ma60": 4700, "ma120": 5000}, "state": "位于 MA20/MA60/MA120 下方"},
            [{"conditionType": "macroEvent", "importance": "critical"}],
            None,
        )
        self.assertLess(card["total"], 45)
        self.assertEqual(card["targets"]["short"]["direction"], "down")
        self.assertLess(card["targets"]["short"]["point"], 4000)
        self.assertLess(card["targets"]["medium"]["point"], card["targets"]["short"]["point"])

    def test_capital_flow_uses_three_available_southbound_measures(self) -> None:
        source = {"sourceId": "southbound", "sourceName": "test"}
        flows = _flow_snapshot(
            "2026-09-17",
            "evening",
            [],
            [{
                "date": "2026-09-17",
                "time": "16:00",
                "southbound": 320000,
                "shanghaiRoute": 180000,
                "shenzhenRoute": 140000,
            }],
            None,
            source,
        )
        self.assertEqual([item["key"] for item in flows], ["southbound", "southboundShanghai", "southboundShenzhen"])
        self.assertEqual([item["value"] for item in flows], [32.0, 18.0, 14.0])
        self.assertTrue(all(item["value"] is not None for item in flows))

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

    def test_unresolved_news_focus_is_inherited_by_the_next_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            report_dir = runtime / "reports" / "2026-09-22"
            report_dir.mkdir(parents=True)
            (report_dir / "evening.json").write_text(json.dumps({
                "reportId": "2026-09-22-evening-v1",
                "tradingDate": "2026-09-22",
                "session": "evening",
                "watchlist": [{
                    "id": "watch-news-ai",
                    "conditionType": "newsCatalyst",
                    "group": "message",
                    "status": "pending",
                    "newsEventId": "news-ai",
                    "source": {"originalTimestamp": "2026-09-22T15:30:00+08:00"},
                }],
            }), encoding="utf-8")
            items = _inherited_message_watchlist(
                "2026-09-23",
                "morning",
                datetime(2026, 9, 23, 8, 30, tzinfo=HKT),
                runtime,
            )
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["inheritedFromReportId"], "2026-09-22-evening-v1")
            self.assertIn("承接自", items[0]["validationResult"])

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
