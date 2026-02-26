from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select

from core.database import async_session_factory, init_db
from core.db_models import ScanCheckRecord, ScanRecord
from core.scanner import Scanner
from core.version import SCANNER_VERSION

FRESHNESS_WINDOW = timedelta(hours=24)


class ScanHTTPError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(message or f"HTTP {status_code}")


class ScanTimeoutError(Exception):
    pass


class ScanNetworkError(Exception):
    pass


@dataclass
class BatchResult:
    total: int
    success: int
    failed: int
    skipped: int
    duration_s: float


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


async def get_latest_scan(domain: str) -> ScanRecord | None:
    async with async_session_factory() as session:
        result = await session.execute(
            select(ScanRecord)
            .where(
                ScanRecord.domain == domain,
                ScanRecord.status == "complete",
                ScanRecord.completed_at.is_not(None),
            )
            .order_by(ScanRecord.completed_at.desc(), ScanRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


def is_fresh_for_version(row: ScanRecord | None, now: datetime, scanner_version: str) -> bool:
    if row is None:
        return False
    if row.scanner_version != scanner_version:
        return False

    completed_at = parse_db_datetime(row.completed_at)
    if completed_at is None:
        return False
    return (now - completed_at) <= FRESHNESS_WINDOW


async def should_scan_domain(
    domain: str,
    *,
    force: bool,
    stale_only: bool,
    now: datetime,
    scanner_version: str,
) -> tuple[bool, str | None]:
    if force:
        return True, None

    latest = await get_latest_scan(domain)
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
    if isinstance(exc, (ScanHTTPError, ScanTimeoutError, ScanNetworkError)):
        return exc

    if isinstance(exc, httpx.TimeoutException):
        return ScanTimeoutError(str(exc))
    if isinstance(
        exc,
        (
            httpx.NetworkError,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
        ),
    ):
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


async def run_scan_with_retries(scanner: Scanner, url: str) -> tuple[Any, int]:
    attempts = 0
    while True:
        attempts += 1
        try:
            result = await scanner.scan(url)
            return result, attempts
        except Exception as raw_exc:  # noqa: BLE001
            exc = classify_error(raw_exc)

            if isinstance(exc, (ScanTimeoutError, ScanNetworkError)) and attempts <= 2:
                await asyncio.sleep(2 ** attempts)
                continue

            if isinstance(exc, ScanHTTPError) and exc.status_code in {403, 429, 500, 502, 503, 504} and attempts <= 1:
                await asyncio.sleep(3)
                continue

            raise raw_exc


def serialize_result(result: Any) -> str:
    return json.dumps(asdict(result), default=json_default)


def extract_grade(result: Any) -> str | None:
    grade = result.metadata.get("grade") if isinstance(result.metadata, dict) else None
    return str(grade) if grade is not None else None


async def insert_scan_success(
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

    async with async_session_factory() as session:
        session.add(
            ScanRecord(
                id=scan_id,
                domain=domain,
                normalized_url=normalized_url,
                source="batch",
                status="complete",
                error=None,
                scanner_version=SCANNER_VERSION,
                overall_score=float(result.overall_score) if result.overall_score is not None else None,
                grade=grade,
                duration_ms=duration_ms,
                result_json=serialize_result(result),
                started_at=started_at,
                completed_at=completed_at,
                created_at=completed_at,
            )
        )

        for check in result.check_results:
            severity = check.severity.value if isinstance(check.severity, Enum) else str(check.severity)
            session.add(
                ScanCheckRecord(
                    scan_id=scan_id,
                    category=check.category,
                    score=float(check.score),
                    severity=severity,
                    details_json=json.dumps(check.details, default=json_default),
                    signals_json=json.dumps([asdict(signal) for signal in check.signals], default=json_default),
                )
            )

        await session.commit()

    return scan_id


async def insert_scan_failure(
    *,
    domain: str,
    normalized_url: str,
    started_at: str,
    completed_at: str,
    duration_ms: int,
    error: Exception,
) -> str:
    scan_id = str(uuid4())
    async with async_session_factory() as session:
        session.add(
            ScanRecord(
                id=scan_id,
                domain=domain,
                normalized_url=normalized_url,
                source="batch",
                status="error",
                error=f"{type(error).__name__}: {error}",
                scanner_version=SCANNER_VERSION,
                overall_score=None,
                grade=None,
                duration_ms=duration_ms,
                result_json=None,
                started_at=started_at,
                completed_at=completed_at,
                created_at=completed_at,
            )
        )
        await session.commit()
    return scan_id


async def _queue_put(progress_queue: asyncio.Queue[dict[str, Any]] | None, item: dict[str, Any]) -> None:
    if progress_queue is None:
        return
    try:
        progress_queue.put_nowait(item)
    except asyncio.QueueFull:
        try:
            progress_queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        try:
            progress_queue.put_nowait(item)
        except asyncio.QueueFull:
            return


async def run_batch_scan(
    urls: list[str],
    concurrency: int = 5,
    force: bool = False,
    stale_only: bool = False,
    progress_queue: asyncio.Queue[dict[str, Any]] | None = None,
    cancel_token: asyncio.Event | None = None,
) -> BatchResult:
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    if force and stale_only:
        raise ValueError("force and stale_only cannot both be true")

    await init_db()

    started_batch = time.perf_counter()
    total = len(urls)
    if total == 0:
        return BatchResult(total=0, success=0, failed=0, skipped=0, duration_s=0.0)

    scanner = Scanner()
    semaphore = asyncio.Semaphore(concurrency)
    counters_lock = asyncio.Lock()

    done = 0
    success = 0
    failed = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    candidates: list[tuple[str, str]] = []

    async def emit(url: str, status: str, grade: str | None = None, error: str | None = None) -> None:
        nonlocal done
        async with counters_lock:
            done += 1
            event = {
                "done": done,
                "total": total,
                "url": url,
                "status": status,
                "grade": grade,
                "error": error,
            }
        await _queue_put(progress_queue, event)

    for raw_url in urls:
        if cancel_token is not None and cancel_token.is_set():
            break

        normalized_url = normalize_url(raw_url)
        domain = normalize_domain(normalized_url)
        if not domain:
            skipped += 1
            await emit(raw_url, status="skipped", error="invalid_url")
            continue

        should_scan, reason = await should_scan_domain(
            domain,
            force=force,
            stale_only=stale_only,
            now=now,
            scanner_version=SCANNER_VERSION,
        )
        if not should_scan:
            skipped += 1
            await emit(normalized_url, status="skipped", error=reason)
            continue

        candidates.append((domain, normalized_url))

    async def scan_task(domain: str, url: str) -> None:
        nonlocal success, failed
        async with semaphore:
            if cancel_token is not None and cancel_token.is_set():
                return

            started_wall = now_iso()
            started_perf = time.perf_counter()
            try:
                result, _attempts = await run_scan_with_retries(scanner, url)
                duration_ms = int((time.perf_counter() - started_perf) * 1000)
                completed_wall = now_iso()

                await insert_scan_success(
                    domain=domain,
                    normalized_url=url,
                    started_at=started_wall,
                    completed_at=completed_wall,
                    duration_ms=duration_ms,
                    result=result,
                )

                success += 1
                grade = extract_grade(result)
                await emit(url, status="ok", grade=grade)
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((time.perf_counter() - started_perf) * 1000)
                completed_wall = now_iso()
                await insert_scan_failure(
                    domain=domain,
                    normalized_url=url,
                    started_at=started_wall,
                    completed_at=completed_wall,
                    duration_ms=duration_ms,
                    error=exc,
                )
                failed += 1
                await emit(url, status="error", error=f"{type(exc).__name__}: {exc}")

    tasks: list[asyncio.Task[None]] = []
    for domain, url in candidates:
        if cancel_token is not None and cancel_token.is_set():
            break
        tasks.append(asyncio.create_task(scan_task(domain, url)))

    if tasks:
        await asyncio.gather(*tasks)

    duration = time.perf_counter() - started_batch
    return BatchResult(
        total=total,
        success=success,
        failed=failed,
        skipped=skipped,
        duration_s=duration,
    )
