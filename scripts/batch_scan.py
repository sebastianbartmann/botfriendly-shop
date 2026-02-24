from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.scanner import Scanner
from core.version import SCANNER_VERSION

DEFAULT_URL_FILE = PROJECT_ROOT / "data" / "ecom_urls.txt"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "ecom_checker.db"
FRESHNESS_WINDOW = timedelta(hours=24)


class ScanHTTPError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(message or f"HTTP {status_code}")


class ScanTimeoutError(Exception):
    pass


class ScanNetworkError(Exception):
    pass


def json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return str(value)


def normalize_domain(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or parsed.netloc or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_url(url: str) -> str:
    candidate = url.strip()
    if not candidate:
        return ""
    if candidate.startswith(("http://", "https://")):
        return candidate
    return f"https://{candidate}"


def load_urls(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_db_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    text = value.strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_db_path(db_path: str) -> Path:
    resolved = Path(db_path).expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS scans (
            id TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            normalized_url TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            scanner_version TEXT NOT NULL,
            overall_score REAL,
            grade TEXT,
            duration_ms INTEGER,
            result_json TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS ix_scans_domain ON scans(domain);
        CREATE INDEX IF NOT EXISTS ix_scans_status ON scans(status);
        CREATE INDEX IF NOT EXISTS ix_scans_created_at ON scans(created_at);

        CREATE TABLE IF NOT EXISTS scan_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id TEXT NOT NULL,
            category TEXT NOT NULL,
            score REAL NOT NULL,
            severity TEXT,
            details_json TEXT,
            signals_json TEXT,
            FOREIGN KEY(scan_id) REFERENCES scans(id),
            UNIQUE(scan_id, category)
        );

        CREATE INDEX IF NOT EXISTS ix_scan_checks_scan_id ON scan_checks(scan_id);
        CREATE INDEX IF NOT EXISTS ix_scan_checks_category ON scan_checks(category);
        """
    )


def get_latest_scan(conn: sqlite3.Connection, domain: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT scanner_version, completed_at
        FROM scans
        WHERE domain = ? AND status = 'complete' AND completed_at IS NOT NULL
        ORDER BY datetime(completed_at) DESC, created_at DESC
        LIMIT 1
        """,
        (domain,),
    ).fetchone()


def is_fresh_for_version(row: sqlite3.Row | None, now: datetime, scanner_version: str) -> bool:
    if row is None:
        return False
    if row["scanner_version"] != scanner_version:
        return False

    completed_at = parse_db_datetime(row["completed_at"])
    if completed_at is None:
        return False
    return (now - completed_at) <= FRESHNESS_WINDOW


def should_scan_domain(
    conn: sqlite3.Connection,
    domain: str,
    *,
    force: bool,
    stale_only: bool,
    now: datetime,
    scanner_version: str,
) -> tuple[bool, str | None]:
    if force:
        return True, None

    latest = get_latest_scan(conn, domain)
    fresh_for_current = is_fresh_for_version(latest, now, scanner_version)

    if stale_only:
        if latest is None:
            return False, "no previous scan"
        if fresh_for_current:
            return False, "fresh cache"
        return True, None

    if fresh_for_current:
        return False, "fresh cache"

    return True, None


def classify_error(exc: Exception) -> Exception:
    if isinstance(exc, ScanHTTPError):
        return exc
    if isinstance(exc, ScanTimeoutError):
        return exc
    if isinstance(exc, ScanNetworkError):
        return exc

    if isinstance(exc, httpx.TimeoutException):
        return ScanTimeoutError(str(exc))
    if isinstance(exc, (httpx.NetworkError, httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)):
        return ScanNetworkError(str(exc))
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else 0
        return ScanHTTPError(status, str(exc))
    if isinstance(exc, asyncio.TimeoutError):
        return ScanTimeoutError(str(exc))
    if isinstance(exc, OSError):
        return ScanNetworkError(str(exc))

    message = str(exc)
    if "HTTP " in message:
        for code in (403, 429, 500, 502, 503, 504):
            if str(code) in message:
                return ScanHTTPError(code, message)

    return exc


async def run_scan_with_retries(scanner: Scanner, url: str, domain: str) -> tuple[Any, int]:
    attempts = 0
    while True:
        attempts += 1
        try:
            result = await scanner.scan(url)
            return result, attempts
        except Exception as raw_exc:  # noqa: BLE001
            exc = classify_error(raw_exc)

            if isinstance(exc, (ScanTimeoutError, ScanNetworkError)):
                if attempts <= 2:
                    backoff = 2 ** attempts
                    print(
                        f"Retry {attempts}/2 for {domain} after {type(exc).__name__}: waiting {backoff}s"
                    )
                    await asyncio.sleep(backoff)
                    continue

            if isinstance(exc, ScanHTTPError) and exc.status_code in {403, 429, 500, 502, 503, 504}:
                if attempts <= 1:
                    print(
                        f"Retry {attempts}/1 for {domain} after HTTP {exc.status_code}: waiting 3s"
                    )
                    await asyncio.sleep(3)
                    continue

            raise raw_exc


def serialize_result(result: Any) -> str:
    return json.dumps(asdict(result), default=json_default)


def extract_grade(result: Any) -> str | None:
    grade = result.metadata.get("grade") if isinstance(result.metadata, dict) else None
    return str(grade) if grade is not None else None


def insert_scan_success(
    conn: sqlite3.Connection,
    *,
    domain: str,
    normalized_url: str,
    started_at: str,
    completed_at: str,
    duration_ms: int,
    result: Any,
) -> str:
    scan_id = str(uuid4())
    grade = extract_grade(result)
    result_json = serialize_result(result)

    conn.execute(
        """
        INSERT INTO scans (
            id, domain, normalized_url, source, status, error,
            scanner_version, overall_score, grade, duration_ms,
            result_json, started_at, completed_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan_id,
            domain,
            normalized_url,
            "batch",
            "complete",
            None,
            SCANNER_VERSION,
            float(result.overall_score),
            grade,
            duration_ms,
            result_json,
            started_at,
            completed_at,
            completed_at,
        ),
    )

    for check in result.check_results:
        severity = check.severity.value if isinstance(check.severity, Enum) else str(check.severity)
        conn.execute(
            """
            INSERT INTO scan_checks (
                scan_id, category, score, severity, details_json, signals_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                check.category,
                float(check.score),
                severity,
                json.dumps(check.details, default=json_default),
                json.dumps([asdict(signal) for signal in check.signals], default=json_default),
            ),
        )

    conn.commit()
    return scan_id


def insert_scan_failure(
    conn: sqlite3.Connection,
    *,
    domain: str,
    normalized_url: str,
    started_at: str,
    completed_at: str,
    duration_ms: int,
    error: Exception,
) -> str:
    scan_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO scans (
            id, domain, normalized_url, source, status, error,
            scanner_version, overall_score, grade, duration_ms,
            result_json, started_at, completed_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan_id,
            domain,
            normalized_url,
            "batch",
            "error",
            f"{type(error).__name__}: {error}",
            SCANNER_VERSION,
            None,
            None,
            duration_ms,
            None,
            started_at,
            completed_at,
            completed_at,
        ),
    )
    conn.commit()
    return scan_id


async def run_batch(args: argparse.Namespace) -> dict[str, Any]:
    url_file = Path(args.url_file)
    if not url_file.is_absolute():
        url_file = Path.cwd() / url_file

    if not url_file.exists():
        raise FileNotFoundError(f"URL file not found: {url_file}")

    urls = load_urls(url_file)
    total = len(urls)
    if total == 0:
        print(f"No URLs found in {url_file}")
        return {
            "total": 0,
            "scanned": 0,
            "failed": 0,
            "skipped": 0,
            "cached": 0,
            "results": [],
        }

    db_path = resolve_db_path(args.db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_schema(conn)

    now = datetime.now(timezone.utc)
    scanner = Scanner()
    semaphore = asyncio.Semaphore(args.concurrency)
    db_lock = asyncio.Lock()

    scanned = 0
    failed = 0
    skipped = 0
    cached = 0

    summary_rows: list[dict[str, Any]] = []
    json_output_rows: list[dict[str, Any]] = []

    targets: list[tuple[int, str, str, str]] = []
    for idx, raw_url in enumerate(urls, start=1):
        normalized_url = normalize_url(raw_url)
        domain = normalize_domain(normalized_url)
        if not domain:
            skipped += 1
            print(f"[{idx}/{total}] Skipping invalid URL: {raw_url}")
            json_output_rows.append(
                {
                    "index": idx,
                    "url": raw_url,
                    "status": "skipped",
                    "reason": "invalid_url",
                }
            )
            continue

        should_scan, reason = should_scan_domain(
            conn,
            domain,
            force=args.force,
            stale_only=args.stale_only,
            now=now,
            scanner_version=SCANNER_VERSION,
        )
        if not should_scan:
            skipped += 1
            if reason == "fresh cache":
                cached += 1
            print(f"[{idx}/{total}] Skipping {domain}: {reason}")
            json_output_rows.append(
                {
                    "index": idx,
                    "domain": domain,
                    "url": normalized_url,
                    "status": "skipped",
                    "reason": reason,
                }
            )
            continue

        targets.append((idx, domain, normalized_url, raw_url))

    async def scan_task(index: int, domain: str, url: str, original_url: str) -> None:
        nonlocal scanned, failed
        async with semaphore:
            started_wall = now_iso()
            started_perf = time.perf_counter()
            print(f"[{index}/{total}] Scanning {domain}...")
            try:
                result, _attempts = await run_scan_with_retries(scanner, url, domain)
                duration_ms = int((time.perf_counter() - started_perf) * 1000)
                completed_wall = now_iso()

                async with db_lock:
                    insert_scan_success(
                        conn,
                        domain=domain,
                        normalized_url=url,
                        started_at=started_wall,
                        completed_at=completed_wall,
                        duration_ms=duration_ms,
                        result=result,
                    )

                scanned += 1
                grade = extract_grade(result) or "N/A"
                score = float(result.overall_score)
                summary_rows.append(
                    {
                        "domain": domain,
                        "grade": grade,
                        "score": score,
                        "duration_s": duration_ms / 1000,
                    }
                )
                json_output_rows.append(
                    {
                        "index": index,
                        "domain": domain,
                        "url": url,
                        "status": "ok",
                        "grade": grade,
                        "score": score,
                        "duration_ms": duration_ms,
                    }
                )
                print(
                    f"[{index}/{total}] Completed {domain}: {grade} ({score:.2f}) [{duration_ms / 1000:.2f}s]"
                )
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((time.perf_counter() - started_perf) * 1000)
                completed_wall = now_iso()
                async with db_lock:
                    insert_scan_failure(
                        conn,
                        domain=domain,
                        normalized_url=url,
                        started_at=started_wall,
                        completed_at=completed_wall,
                        duration_ms=duration_ms,
                        error=exc,
                    )
                failed += 1
                summary_rows.append(
                    {
                        "domain": domain,
                        "grade": "ERROR",
                        "score": None,
                        "duration_s": duration_ms / 1000,
                    }
                )
                json_output_rows.append(
                    {
                        "index": index,
                        "domain": domain,
                        "url": url,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "duration_ms": duration_ms,
                    }
                )
                print(f"[{index}/{total}] Failed {domain}: {type(exc).__name__}: {exc}")

    tasks: list[asyncio.Task[None]] = []
    for i, (index, domain, normalized_url, original_url) in enumerate(targets):
        tasks.append(asyncio.create_task(scan_task(index, domain, normalized_url, original_url)))
        if i < len(targets) - 1:
            await asyncio.sleep(1)

    if tasks:
        await asyncio.gather(*tasks)

    conn.close()

    print("\nSummary")
    print("domain | grade | score | duration")
    for row in sorted(summary_rows, key=lambda item: (item["score"] is None, -(item["score"] or -1))):
        score_text = f"{row['score']:.2f}" if isinstance(row["score"], float) else "N/A"
        print(f"{row['domain']} | {row['grade']} | {score_text} | {row['duration_s']:.2f}s")

    print("\nTotals")
    print(f"scanned={scanned} skipped={skipped} failed={failed} cached={cached}")

    payload = {
        "total": total,
        "queued": len(targets),
        "scanned": scanned,
        "failed": failed,
        "skipped": skipped,
        "cached": cached,
        "results": sorted(json_output_rows, key=lambda item: item.get("index", 0)),
    }

    if args.json:
        print(json.dumps(payload, default=json_default))

    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch scan e-commerce URLs and persist results to SQLite")
    parser.add_argument(
        "url_file",
        nargs="?",
        default=str(DEFAULT_URL_FILE),
        help="Path to newline-delimited URL file (default: data/ecom_urls.txt)",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path to SQLite DB (default: data/ecom_checker.db)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Maximum concurrent scans (default: 5)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore cache and rescan all domains",
    )
    parser.add_argument(
        "--stale-only",
        action="store_true",
        help="Only scan domains with stale/outdated previous results",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON summary to stdout",
    )
    args = parser.parse_args()

    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")
    if args.force and args.stale_only:
        parser.error("--force and --stale-only cannot be used together")

    return args


if __name__ == "__main__":
    asyncio.run(run_batch(parse_args()))
