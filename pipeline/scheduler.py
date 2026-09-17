from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import pandas as pd

from pipeline.sources import HKT


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "data" / "runtime"
REPORT_ROOT = RUNTIME_ROOT / "reports"
STATE_PATH = RUNTIME_ROOT / "scheduler-state.json"
STATUS_PATH = RUNTIME_ROOT / "scheduler-status.json"
LOCK_PATH = RUNTIME_ROOT / "scheduler.lock"
# The local setup uses .venv, while the shareable Docker setup uses the Python
# interpreter provided by its container.  Keeping this configurable means the
# scheduler runs identically in either environment.
PYTHON = Path(os.environ.get("PYTHON_EXECUTABLE", sys.executable))
RETRY_INTERVAL = timedelta(minutes=15)
MAX_PARTIAL_ATTEMPTS = 3


@dataclass(frozen=True)
class ReportSpec:
    session: str
    publish_at: time


REPORT_SPECS = (
    ReportSpec("morning", time(8, 30)),
    ReportSpec("midday", time(12, 30)),
    ReportSpec("evening", time(17, 0)),
)


def _iso_now(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def report_quality(path: Path, session: str, trading_date: str) -> tuple[str, list[str], dict[str, Any] | None]:
    if not path.exists():
        return "missing", ["报告文件不存在"], None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return "invalid", [f"报告无法读取：{exc}"], None

    hard_issues: list[str] = []
    if report.get("session") != session:
        hard_issues.append("报告时段不匹配")
    if report.get("tradingDate") != trading_date:
        hard_issues.append("交易日期不匹配")
    if not report.get("generatedAt"):
        hard_issues.append("缺少生成时间")
    if report.get("index", {}).get("last") is None:
        hard_issues.append("缺少恒科指数点位")
    if len(report.get("constituents") or []) < 30:
        hard_issues.append("成分股不足30只")
    if not report.get("sourceStatus"):
        hard_issues.append("缺少数据来源记录")
    if hard_issues:
        return "invalid", hard_issues, report

    partial_issues: list[str] = []
    if len(report.get("crossMarkets") or []) < 10:
        partial_issues.append("跨市场指标不足10项")
    if len(report.get("news") or []) < 1:
        partial_issues.append("没有相关消息")
    if report.get("sourceErrors"):
        partial_issues.append(f"存在{len(report['sourceErrors'])}项数据源异常")
    if session != "morning":
        if len(report.get("minuteBars") or []) < 100:
            partial_issues.append("分钟行情不足100条")
        if int(report.get("breadth", {}).get("available") or 0) < 24:
            partial_issues.append("市场宽度覆盖不足24只")
    return ("partial", partial_issues, report) if partial_issues else ("ready", [], report)


def _calendar_date(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%d")


def expected_reports(now: datetime) -> list[tuple[str, str]]:
    calendar = xcals.get_calendar("XHKG")
    today = now.date().isoformat()
    today_stamp = pd.Timestamp(today)
    expected: list[tuple[str, str]] = []
    if calendar.is_session(today_stamp):
        for spec in REPORT_SPECS:
            if now.timetz().replace(tzinfo=None) >= spec.publish_at:
                expected.append((today, spec.session))
        if now.timetz().replace(tzinfo=None) < REPORT_SPECS[0].publish_at:
            previous = calendar.previous_session(today_stamp)
            expected.append((_calendar_date(previous), "evening"))
    else:
        previous = calendar.date_to_session(today_stamp, direction="previous")
        expected.append((_calendar_date(previous), "evening"))
    return expected


def _attempt_key(trading_date: str, session: str) -> str:
    return f"{trading_date}:{session}"


def _can_attempt(state: dict[str, Any], key: str, quality: str, now: datetime) -> bool:
    record = state.get("attempts", {}).get(key, {})
    attempts = int(record.get("count") or 0)
    if quality == "partial" and attempts >= MAX_PARTIAL_ATTEMPTS:
        return False
    last_attempt = record.get("lastAttemptAt")
    if last_attempt:
        try:
            if now - datetime.fromisoformat(last_attempt) < RETRY_INTERVAL:
                return False
        except ValueError:
            pass
    return True


def _run_report(trading_date: str, session: str) -> subprocess.CompletedProcess[str]:
    command = [
        str(PYTHON),
        "-m",
        "pipeline.run_scheduled",
        "--session",
        session,
        "--date",
        trading_date,
    ]
    return subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=240)


def run_once(now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(HKT)).astimezone(HKT)
    state = _read_json(STATE_PATH, {"attempts": {}})
    state.setdefault("attempts", {})
    checks: list[dict[str, Any]] = []

    for trading_date, session in expected_reports(current):
        path = REPORT_ROOT / trading_date / f"{session}.json"
        quality, issues, report = report_quality(path, session, trading_date)
        key = _attempt_key(trading_date, session)
        attempted = False
        process_result: subprocess.CompletedProcess[str] | None = None

        if quality != "ready" and _can_attempt(state, key, quality, current):
            attempted = True
            logging.info("Generating %s %s because status is %s", trading_date, session, quality)
            try:
                process_result = _run_report(trading_date, session)
            except (subprocess.SubprocessError, OSError) as exc:
                process_result = subprocess.CompletedProcess([], 1, "", str(exc))
            record = state["attempts"].setdefault(key, {"count": 0})
            record["count"] = int(record.get("count") or 0) + 1
            record["lastAttemptAt"] = _iso_now(current)
            record["lastExitCode"] = process_result.returncode
            record["lastOutput"] = (process_result.stdout + process_result.stderr)[-4000:]
            quality, issues, report = report_quality(path, session, trading_date)

        check = {
            "tradingDate": trading_date,
            "session": session,
            "status": quality,
            "issues": issues,
            "attempted": attempted,
            "reportGeneratedAt": report.get("generatedAt") if report else None,
            "sourceErrorCount": len(report.get("sourceErrors") or []) if report else None,
        }
        if process_result is not None:
            check["exitCode"] = process_result.returncode
        checks.append(check)
        logging.info("Report check: %s", check)

    status = {
        "updatedAt": _iso_now(current),
        "timezone": "Asia/Hong_Kong",
        "scheduler": os.environ.get("SCHEDULER_NAME", "local_watchdog"),
        "checks": checks,
        "healthy": all(item["status"] in {"ready", "partial"} for item in checks),
    }
    state["updatedAt"] = status["updatedAt"]
    _write_json(STATE_PATH, state)
    _write_json(STATUS_PATH, status)
    return status


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("Another scheduler process is still running; skipping this tick")
            return
        status = run_once()
    if not status["healthy"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
