from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sse_starlette.sse import EventSourceResponse

from checks.api_surface import APISurfaceCheck
from checks.accessibility import AccessibilityCheck
from checks.discovery import DiscoveryCheck
from checks.feeds import FeedsCheck
from checks.product_parseability import ProductParseabilityCheck
from checks.robots import AI_BOTS, TIER_LABELS, RobotsCheck
from checks.semantic_html import SemanticHtmlCheck
from checks.seo_meta import SeoMetaCheck
from checks.sitemap import SitemapCheck
from checks.structured_data import StructuredDataCheck
from core.database import async_session_factory, init_db
from core.db_models import ScanCheckRecord, ScanRecord
from core.models import CheckResult
from core.scanner import Scanner
from core.scoring import calculate_overall_score, get_grade
from core.url_validator import validate_url
from core.version import SCANNER_VERSION

router = APIRouter()
logger = logging.getLogger(__name__)

CHECKS = [
    RobotsCheck(),
    DiscoveryCheck(),
    SitemapCheck(),
    StructuredDataCheck(),
    SeoMetaCheck(),
    FeedsCheck(),
    APISurfaceCheck(),
    ProductParseabilityCheck(),
    SemanticHtmlCheck(),
    AccessibilityCheck(),
]

CATEGORY_LABELS = {
    "robots": "Robots.txt AI Bot Access",
    "discovery": "AI Discovery Files",
    "sitemap": "Sitemap Quality",
    "structured_data": "Structured Data",
    "seo_meta": "SEO Metadata",
    "feeds": "Product Feed Availability",
    "api_surface": "API Surface",
    "product_parseability": "Product Parseability",
    "semantic_html": "Semantic HTML",
    "accessibility": "Accessibility",
}

scans: dict[str, dict[str, Any]] = {}
scan_tasks: dict[str, asyncio.Task[None]] = {}


def _client_ip_key_func(request: Request) -> str:
    forwarded_for = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip_key_func)


def _normalize_url(url: str) -> str:
    candidate = (url or "").strip()
    if candidate and not candidate.startswith(("http://", "https://")):
        return f"https://{candidate}"
    return candidate


def _extract_domain(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: _json_safe(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_json_safe(item) for item in payload]
    if hasattr(payload, "value"):
        return payload.value
    return payload


def _serialize_check_result(result: CheckResult) -> dict[str, Any]:
    raw = asdict(result)
    data = _json_safe(raw)
    data["category_label"] = CATEGORY_LABELS.get(result.category, result.category.replace("_", " ").title())
    return data


def _check_event_from_result(result: CheckResult) -> dict[str, Any]:
    result_payload = _serialize_check_result(result)
    return {
        "type": "check",
        "category": result.category,
        "category_label": result_payload["category_label"],
        "score": result.score,
        "severity": result.severity.value,
        "signals": result_payload["signals"],
        "details": result_payload["details"],
        "recommendations": result.recommendations,
    }


def _events_from_result_json(result_json: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(result_json)
    except (TypeError, json.JSONDecodeError):
        return []

    check_results = payload.get("check_results")
    if not isinstance(check_results, list):
        return []

    events: list[dict[str, Any]] = []
    for check in check_results:
        if not isinstance(check, dict):
            continue
        category = str(check.get("category", ""))
        events.append(
            {
                "type": "check",
                "category": category,
                "category_label": check.get(
                    "category_label",
                    CATEGORY_LABELS.get(category, category.replace("_", " ").title()),
                ),
                "score": float(check.get("score", 0.0)),
                "severity": str(check.get("severity", "inconclusive")),
                "signals": check.get("signals", []),
                "details": check.get("details", {}),
                "recommendations": check.get("recommendations", []),
            }
        )
    return events


async def _insert_scan(scan_id: str, url: str, source: str, status: str) -> None:
    now = _now_iso()
    async with async_session_factory() as session:
        session.add(
            ScanRecord(
                id=scan_id,
                domain=_extract_domain(url),
                normalized_url=url,
                source=source,
                status=status,
                scanner_version=SCANNER_VERSION,
                started_at=now,
                created_at=now,
            )
        )
        await session.commit()


async def _upsert_scan_check(scan_id: str, event: dict[str, Any]) -> None:
    stmt = (
        sqlite_insert(ScanCheckRecord)
        .values(
            scan_id=scan_id,
            category=event["category"],
            score=event["score"],
            severity=event.get("severity"),
            details_json=json.dumps(event.get("details", {})),
            signals_json=json.dumps(event.get("signals", [])),
        )
        .on_conflict_do_update(
            index_elements=["scan_id", "category"],
            set_={
                "score": event["score"],
                "severity": event.get("severity"),
                "details_json": json.dumps(event.get("details", {})),
                "signals_json": json.dumps(event.get("signals", [])),
            },
        )
    )
    async with async_session_factory() as session:
        await session.execute(stmt)
        await session.commit()


async def _complete_scan(scan_id: str, overall_score: float, grade: str, duration_ms: int, result_payload: dict[str, Any]) -> None:
    await _update_scan(
        scan_id,
        {
            "status": "complete",
            "overall_score": overall_score,
            "grade": grade,
            "duration_ms": duration_ms,
            "result_json": json.dumps(_json_safe(result_payload)),
            "completed_at": _now_iso(),
            "error": None,
        },
    )


async def _fail_scan(scan_id: str, error: str, duration_ms: int | None = None) -> None:
    values: dict[str, Any] = {
        "status": "error",
        "error": error,
        "completed_at": _now_iso(),
    }
    if duration_ms is not None:
        values["duration_ms"] = duration_ms
    await _update_scan(scan_id, values)


async def _update_scan(scan_id: str, values: dict[str, Any]) -> None:
    async with async_session_factory() as session:
        await session.execute(update(ScanRecord).where(ScanRecord.id == scan_id).values(**values))
        await session.commit()


async def _load_scan_record(scan_id: str) -> ScanRecord | None:
    async with async_session_factory() as session:
        result = await session.execute(select(ScanRecord).where(ScanRecord.id == scan_id))
        return result.scalar_one_or_none()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def _find_cached_complete_scan(domain: str) -> ScanRecord | None:
    threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    async with async_session_factory() as session:
        result = await session.execute(
            select(ScanRecord)
            .where(
                ScanRecord.domain == domain,
                ScanRecord.scanner_version == SCANNER_VERSION,
                ScanRecord.status == "complete",
                ScanRecord.completed_at.is_not(None),
            )
            .order_by(ScanRecord.completed_at.desc())
        )
        for record in result.scalars():
            completed_at = _parse_iso_datetime(record.completed_at)
            if completed_at is not None and completed_at >= threshold:
                return record
    return None


async def _load_scan_state(scan_id: str) -> dict[str, Any] | None:
    if scan_id in scans:
        return scans[scan_id]

    record = await _load_scan_record(scan_id)
    if record is None:
        return None

    state = {
        "url": record.normalized_url,
        "status": record.status,
        "results": _events_from_result_json(record.result_json or "") if record.status == "complete" else [],
        "overall": record.overall_score,
        "grade": record.grade,
        "error": record.error,
    }
    scans[scan_id] = state
    return state


def _complete_event(scan: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "complete",
        "overall_score": scan.get("overall"),
        "grade": scan.get("grade"),
        "check_count": len(scan.get("results", [])),
    }


def _error_event(error: str | None) -> dict[str, Any]:
    message = (error or "Scan failed").strip()
    if not message.startswith("Scan failed:"):
        message = f"Scan failed: {message}"
    return {"type": "error", "message": message}


async def _stream_from_scan_state(request: Request, scan_id: str) -> Any:
    emitted = 0
    while True:
        if await request.is_disconnected():
            return

        scan = scans.get(scan_id)
        if scan is None:
            return

        while emitted < len(scan["results"]):
            if await request.is_disconnected():
                return
            yield {"data": json.dumps(scan["results"][emitted])}
            emitted += 1

        status = scan.get("status")
        if status == "complete":
            yield {"data": json.dumps(_complete_event(scan))}
            return
        if status == "error":
            yield {"data": json.dumps(_error_event(scan.get("error")))}
            return

        await asyncio.sleep(0.1)


async def _run_web_scan(scan_id: str, url: str) -> None:
    check_results: list[CheckResult] = []
    started = time.perf_counter()

    try:
        scanner = Scanner(checks=[])
        artifacts = await scanner._http_pass(url)

        for check in CHECKS:
            result = await check.run(url, artifacts)
            check_results.append(result)

            check_event = _check_event_from_result(result)
            scans[scan_id]["results"].append(check_event)
            await _upsert_scan_check(scan_id, check_event)

        overall_score = calculate_overall_score(check_results)
        grade = get_grade(overall_score)
        duration_ms = int((time.perf_counter() - started) * 1000)
        scan_result_payload = {
            "url": url,
            "overall_score": overall_score,
            "check_results": [_serialize_check_result(item) for item in check_results],
            "metadata": {"check_count": len(check_results), "grade": grade},
        }

        scans[scan_id]["status"] = "complete"
        scans[scan_id]["overall"] = overall_score
        scans[scan_id]["grade"] = grade
        await _complete_scan(scan_id, overall_score, grade, duration_ms, scan_result_payload)
        logger.info(
            "scan_completed scan_id=%s source=web url=%s score=%.4f grade=%s duration_ms=%d",
            scan_id,
            url,
            overall_score,
            grade,
            duration_ms,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        scans[scan_id]["status"] = "error"
        scans[scan_id]["error"] = str(exc)
        await _fail_scan(scan_id, str(exc), duration_ms)
        logger.exception(
            "scan_error scan_id=%s source=web url=%s duration_ms=%d error=%s",
            scan_id,
            url,
            duration_ms,
            str(exc),
        )
    finally:
        scan_tasks.pop(scan_id, None)


def _ensure_scan_task(scan_id: str, url: str) -> None:
    existing = scan_tasks.get(scan_id)
    if existing is not None and not existing.done():
        return
    scan_tasks[scan_id] = asyncio.create_task(_run_web_scan(scan_id, url))


@router.get("/")
async def home(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/robots.txt")
async def robots_txt():
    return PlainTextResponse("User-agent: *\nAllow: /\nSitemap: https://botfriendly.shop/sitemap.xml")


@router.get("/bots")
async def bots_page(request: Request):
    templates = request.app.state.templates
    tier_descriptions = {
        "agent": "These bots browse stores and can complete shopping steps on behalf of users, so allowing them can directly impact assisted commerce conversion.",
        "crawler": "These bots index and retrieve your content for AI search, answers, and training, which affects discoverability and product visibility.",
    }
    tier_order = ["agent", "crawler"]
    sections = [
        {
            "key": tier,
            "label": TIER_LABELS.get(tier, tier),
            "description": tier_descriptions.get(tier, ""),
            "bots": [bot for bot in AI_BOTS if bot.tier == tier],
        }
        for tier in tier_order
    ]
    return templates.TemplateResponse(
        "bots.html",
        {
            "request": request,
            "sections": sections,
            "bot_count": len(AI_BOTS),
        },
    )


@router.get("/stats")
async def stats_page(request: Request):
    await init_db()
    templates = request.app.state.templates

    grade_order = ["A+", "A", "B", "C", "D", "F"]
    category_order = list(CATEGORY_LABELS.keys())
    category_averages = {category: 0.0 for category in category_order}

    async with async_session_factory() as session:
        total_unique_domains = (
            await session.scalar(
                text(
                    """
                    SELECT COUNT(DISTINCT domain)
                    FROM scans
                    """
                )
            )
            or 0
        )
        total_scans = (await session.scalar(text("SELECT COUNT(*) FROM scans"))) or 0

        grade_rows = (
            await session.execute(
                text(
                    """
                    SELECT grade, COUNT(*) AS grade_count
                    FROM scans
                    WHERE status = 'complete' AND grade IN ('A+', 'A', 'B', 'C', 'D', 'F')
                    GROUP BY grade
                    ORDER BY CASE grade
                        WHEN 'A+' THEN 1
                        WHEN 'A' THEN 2
                        WHEN 'B' THEN 3
                        WHEN 'C' THEN 4
                        WHEN 'D' THEN 5
                        WHEN 'F' THEN 6
                        ELSE 7
                    END
                    """
                )
            )
        ).all()
        grade_distribution = {grade: 0 for grade in grade_order}
        for grade, grade_count in grade_rows:
            grade_distribution[grade] = grade_count

        score_stats_row = (
            await session.execute(
                text(
                    """
                    WITH ranked_scores AS (
                        SELECT
                            overall_score,
                            ROW_NUMBER() OVER (ORDER BY overall_score) AS row_num,
                            COUNT(*) OVER () AS total_count
                        FROM scans
                        WHERE status = 'complete' AND overall_score IS NOT NULL
                    ),
                    median_scores AS (
                        SELECT overall_score
                        FROM ranked_scores
                        WHERE row_num IN (
                            CAST((total_count + 1) / 2 AS INTEGER),
                            CAST((total_count + 2) / 2 AS INTEGER)
                        )
                    )
                    SELECT
                        MIN(overall_score) AS min_score,
                        MAX(overall_score) AS max_score,
                        AVG(overall_score) AS avg_score,
                        (SELECT AVG(overall_score) FROM median_scores) AS median_score
                    FROM scans
                    WHERE status = 'complete' AND overall_score IS NOT NULL
                    """
                )
            )
        ).first()
        if score_stats_row:
            min_score = float(score_stats_row.min_score) if score_stats_row.min_score is not None else 0.0
            max_score = float(score_stats_row.max_score) if score_stats_row.max_score is not None else 0.0
            avg_score = float(score_stats_row.avg_score) if score_stats_row.avg_score is not None else 0.0
            median_score = float(score_stats_row.median_score) if score_stats_row.median_score is not None else 0.0
        else:
            min_score = max_score = avg_score = median_score = 0.0

        category_rows = (
            await session.execute(
                text(
                    """
                    SELECT sc.category, AVG(sc.score) AS avg_score
                    FROM scan_checks sc
                    INNER JOIN scans s ON s.id = sc.scan_id
                    WHERE s.status = 'complete'
                    GROUP BY sc.category
                    """
                )
            )
        ).all()
        for category, category_avg in category_rows:
            if category in category_averages:
                category_averages[category] = float(category_avg or 0.0)

        top_domains_rows = (
            await session.execute(
                text(
                    """
                    SELECT domain, AVG(overall_score) AS avg_score, COUNT(*) AS scan_count
                    FROM scans
                    WHERE status = 'complete' AND overall_score IS NOT NULL
                    GROUP BY domain
                    ORDER BY avg_score DESC, scan_count DESC, domain ASC
                    LIMIT 10
                    """
                )
            )
        ).all()
        top_domains = [
            {
                "domain": row.domain,
                "overall_score": float(row.avg_score or 0.0),
                "grade": get_grade(float(row.avg_score or 0.0)),
                "scan_count": row.scan_count,
            }
            for row in top_domains_rows
        ]

        bottom_domains_rows = (
            await session.execute(
                text(
                    """
                    SELECT domain, AVG(overall_score) AS avg_score, COUNT(*) AS scan_count
                    FROM scans
                    WHERE status = 'complete' AND overall_score IS NOT NULL
                    GROUP BY domain
                    ORDER BY avg_score ASC, scan_count DESC, domain ASC
                    LIMIT 10
                    """
                )
            )
        ).all()
        bottom_domains = [
            {
                "domain": row.domain,
                "overall_score": float(row.avg_score or 0.0),
                "grade": get_grade(float(row.avg_score or 0.0)),
                "scan_count": row.scan_count,
            }
            for row in bottom_domains_rows
        ]

        recent_rows = (
            await session.execute(
                text(
                    """
                    SELECT id, domain, grade, overall_score, completed_at
                    FROM scans
                    WHERE status = 'complete'
                    ORDER BY completed_at DESC
                    LIMIT 20
                    """
                )
            )
        ).all()
        recent_scans = [
            {
                "scan_id": row.id,
                "domain": row.domain,
                "grade": row.grade or "N/A",
                "overall_score": float(row.overall_score or 0.0),
                "completed_at": row.completed_at or "",
            }
            for row in recent_rows
        ]

        histogram_rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        CASE
                            WHEN overall_score >= 1 THEN 9
                            WHEN overall_score < 0 THEN 0
                            ELSE CAST(overall_score * 10 AS INTEGER)
                        END AS bucket_index,
                        COUNT(*) AS bucket_count
                    FROM scans
                    WHERE status = 'complete' AND overall_score IS NOT NULL
                    GROUP BY bucket_index
                    ORDER BY bucket_index
                    """
                )
            )
        ).all()
        histogram_counts = [0] * 10
        for row in histogram_rows:
            idx = int(row.bucket_index)
            if 0 <= idx < 10:
                histogram_counts[idx] = int(row.bucket_count)

        failing_signal_rows: list[Any] = []
        try:
            failing_signal_rows = (
                await session.execute(
                    text(
                        """
                        SELECT json_extract(j.value, '$.name') AS signal_name, COUNT(*) AS fail_count
                        FROM scan_checks sc,
                             json_each(sc.signals_json) AS j
                        WHERE json_valid(sc.signals_json)
                          AND LOWER(COALESCE(json_extract(j.value, '$.severity'), '')) = 'fail'
                          AND json_extract(j.value, '$.name') IS NOT NULL
                        GROUP BY signal_name
                        ORDER BY fail_count DESC, signal_name ASC
                        LIMIT 15
                        """
                    )
                )
            ).all()
        except Exception:
            failing_signal_rows = []
        failing_signals = [
            {"name": str(row.signal_name), "count": int(row.fail_count)}
            for row in failing_signal_rows
        ]

    dominant_grade = "N/A"
    dominant_grade_count = 0
    for grade in grade_order:
        grade_count = grade_distribution.get(grade, 0)
        if grade_count > dominant_grade_count:
            dominant_grade = grade
            dominant_grade_count = grade_count

    histogram_labels = [f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10)]

    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "total_unique_domains": total_unique_domains,
            "total_scans": total_scans,
            "avg_score": avg_score,
            "dominant_grade": dominant_grade,
            "dominant_grade_count": dominant_grade_count,
            "grade_distribution": grade_distribution,
            "score_stats": {
                "min": min_score,
                "max": max_score,
                "avg": avg_score,
                "median": median_score,
            },
            "category_labels": [CATEGORY_LABELS[category] for category in category_order],
            "category_averages": [category_averages[category] for category in category_order],
            "top_domains": top_domains,
            "bottom_domains": bottom_domains,
            "recent_scans": recent_scans,
            "failing_signals": failing_signals,
            "histogram_labels": histogram_labels,
            "histogram_counts": histogram_counts,
        },
    )


@router.post("/scan")
@limiter.limit("10/minute")
async def start_scan(
    request: Request,
    force: bool = Query(False),
    rescan: bool = Query(False),
):
    await init_db()
    form = await request.form()
    raw_url = _normalize_url(str(form.get("url", "")))

    is_valid, error_message = validate_url(raw_url)
    if not is_valid:
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "error": error_message or "Please enter a valid URL that starts with http:// or https://",
                "url": raw_url,
            },
            status_code=400,
        )

    bypass_cache = force or rescan
    domain = _extract_domain(raw_url)
    if not bypass_cache and domain:
        cached_record = await _find_cached_complete_scan(domain)
        if cached_record is not None:
            return RedirectResponse(url=f"/results/{cached_record.id}", status_code=303)

    scan_id = str(uuid4())
    scans[scan_id] = {
        "url": raw_url,
        "status": "running",
        "results": [],
        "overall": None,
        "grade": None,
        "error": None,
    }
    await _insert_scan(scan_id, raw_url, source="web", status="running")
    logger.info("scan_started scan_id=%s source=web url=%s", scan_id, raw_url)
    return RedirectResponse(url=f"/results/{scan_id}", status_code=303)


@router.get("/results/{scan_id}")
async def results_page(request: Request, scan_id: str):
    await init_db()
    scan = await _load_scan_state(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "scan_id": scan_id,
            "scan_data": scan,
            "url": scan["url"],
            "check_count": len(CHECKS),
            "categories": [check.__class__.__name__ for check in CHECKS],
            "category_labels": CATEGORY_LABELS,
            "preloaded_complete": scan["status"] == "complete",
            "preloaded_results": scan["results"] if scan["status"] == "complete" else [],
            "preloaded_overall": scan["overall"] if scan["status"] == "complete" else None,
            "preloaded_grade": scan["grade"] if scan["status"] == "complete" else None,
        },
    )


@router.get("/api/stream/{scan_id}")
@limiter.limit("30/minute")
async def stream_scan(request: Request, scan_id: str):
    await init_db()
    scan = await _load_scan_state(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    async def event_generator():
        start_event = {"type": "start", "url": scan["url"], "check_count": len(CHECKS)}
        yield {"data": json.dumps(start_event)}

        latest = scans.get(scan_id)
        if latest is None:
            return

        if latest.get("status") == "complete":
            for prior in latest["results"]:
                if await request.is_disconnected():
                    return
                yield {"data": json.dumps(prior)}
            yield {"data": json.dumps(_complete_event(latest))}
            return

        if latest.get("status") == "error":
            yield {"data": json.dumps(_error_event(latest.get("error")))}
            return

        _ensure_scan_task(scan_id, latest["url"])
        async for event in _stream_from_scan_state(request, scan_id):
            yield event

    return EventSourceResponse(event_generator())


@router.get("/api/v1/scan")
@limiter.limit("10/minute")
async def scan_json(
    request: Request,
    url: str = Query(..., description="Site URL to scan"),
    force: bool = Query(False),
    rescan: bool = Query(False),
):
    await init_db()
    normalized_url = url.strip()
    is_valid, error_message = validate_url(normalized_url)
    if not is_valid:
        return JSONResponse(
            status_code=400,
            content={"error": error_message or "Invalid URL"},
        )

    bypass_cache = force or rescan
    domain = _extract_domain(normalized_url)
    if not bypass_cache and domain:
        cached_record = await _find_cached_complete_scan(domain)
        if cached_record is not None:
            try:
                payload = json.loads(cached_record.result_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            return JSONResponse(content=payload)

    scan_id = str(uuid4())
    await _insert_scan(scan_id, normalized_url, source="api", status="running")
    logger.info("scan_started scan_id=%s source=api url=%s", scan_id, normalized_url)

    started = time.perf_counter()
    check_results: list[CheckResult] = []

    try:
        scanner = Scanner(checks=[])
        artifacts = await scanner._http_pass(normalized_url)

        for check in CHECKS:
            result = await check.run(normalized_url, artifacts)
            check_results.append(result)
            await _upsert_scan_check(scan_id, _check_event_from_result(result))

        overall_score = calculate_overall_score(check_results)
        grade = get_grade(overall_score)
        duration_ms = int((time.perf_counter() - started) * 1000)

        payload = {
            "url": normalized_url,
            "overall_score": overall_score,
            "metadata": {"check_count": len(check_results), "grade": grade},
            "check_results": [_serialize_check_result(item) for item in check_results],
        }
        await _complete_scan(scan_id, overall_score, grade, duration_ms, payload)
        logger.info(
            "scan_completed scan_id=%s source=api url=%s score=%.4f grade=%s duration_ms=%d",
            scan_id,
            normalized_url,
            overall_score,
            grade,
            duration_ms,
        )

        return JSONResponse(content=payload)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        await _fail_scan(scan_id, str(exc), duration_ms)
        logger.exception(
            "scan_error scan_id=%s source=api url=%s duration_ms=%d error=%s",
            scan_id,
            normalized_url,
            duration_ms,
            str(exc),
        )
        raise
