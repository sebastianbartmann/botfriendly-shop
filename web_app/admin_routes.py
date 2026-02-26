from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.security import HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core.batch import BatchResult, run_batch_scan
from core.database import async_session_factory
from web_app.auth import require_admin

admin_router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_batch_task: asyncio.Task[BatchResult] | None = None
_cancel_token: asyncio.Event | None = None
_progress_queue: asyncio.Queue[dict[str, Any]] | None = None
_batch_summary: BatchResult | None = None


def _summary_payload(summary: BatchResult) -> dict[str, Any]:
    return asdict(summary)


def _default_db_stats() -> dict[str, Any]:
    return {
        "total_scans": 0,
        "unique_domains": 0,
        "oldest_scan": "N/A",
        "latest_scan": "N/A",
        "versions": [],
    }


def _format_scan_date(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value[:10] if value else "N/A"
    return str(value)[:10]


def _queue_put_nowait(item: dict[str, Any]) -> None:
    if _progress_queue is None:
        return
    try:
        _progress_queue.put_nowait(item)
    except asyncio.QueueFull:
        try:
            _progress_queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        try:
            _progress_queue.put_nowait(item)
        except asyncio.QueueFull:
            return


def _on_batch_done(task: asyncio.Task[BatchResult]) -> None:
    global _batch_summary

    try:
        result = task.result()
    except Exception:  # noqa: BLE001
        result = BatchResult(total=0, success=0, failed=0, skipped=0, duration_s=0.0)

    _batch_summary = result
    _queue_put_nowait({"finished": True, "summary": _summary_payload(result)})


@admin_router.get("", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(require_admin),
):
    del credentials

    url_file = Path(__file__).parent.parent / "data" / "ecom_urls.txt"
    url_list = url_file.read_text(encoding="utf-8") if url_file.exists() else ""

    db_stats = _default_db_stats()

    async def _fetch_stats() -> dict[str, Any]:
        async with async_session_factory() as session:
            total_scans = int((await session.scalar(text("SELECT COUNT(*) AS total_scans FROM scans"))) or 0)
            unique_domains = int((await session.scalar(text("SELECT COUNT(DISTINCT domain) AS unique_domains FROM scans"))) or 0)

            try:
                minmax_row = (
                    await session.execute(
                        text("SELECT MIN(scanned_at) AS oldest_scan, MAX(scanned_at) AS latest_scan FROM scans")
                    )
                ).first()
            except SQLAlchemyError:
                minmax_row = None

            if minmax_row is None or (minmax_row.oldest_scan is None and minmax_row.latest_scan is None):
                minmax_row = (
                    await session.execute(
                        text("SELECT MIN(completed_at) AS oldest_scan, MAX(completed_at) AS latest_scan FROM scans")
                    )
                ).first()

            versions = (
                await session.execute(
                    text(
                        """
                        SELECT scanner_version, COUNT(*) AS cnt
                        FROM scans
                        GROUP BY scanner_version
                        ORDER BY cnt DESC
                        """
                    )
                )
            ).all()
        return {
            "total_scans": total_scans,
            "unique_domains": unique_domains,
            "oldest_scan": _format_scan_date(minmax_row.oldest_scan if minmax_row else None),
            "latest_scan": _format_scan_date(minmax_row.latest_scan if minmax_row else None),
            "versions": [{"scanner_version": row.scanner_version, "cnt": int(row.cnt)} for row in versions],
        }

    try:
        db_stats = await asyncio.wait_for(_fetch_stats(), timeout=2.0)
    except (TimeoutError, SQLAlchemyError):
        db_stats = _default_db_stats()

    batch_running = _batch_task is not None and not _batch_task.done()
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "db_stats": db_stats,
            "url_list": url_list,
            "batch_running": batch_running,
            "batch_summary": _batch_summary,
        },
    )


@admin_router.post("/batch/start")
async def admin_batch_start(
    credentials: HTTPBasicCredentials = Depends(require_admin),
    urls: str = Form(""),
    concurrency: int = Form(5),
    force: bool = Form(False),
    stale_only: bool = Form(False),
):
    del credentials
    global _batch_task, _cancel_token, _progress_queue, _batch_summary

    url_list = [u.strip() for u in urls.splitlines() if u.strip() and not u.strip().startswith("#")]
    if not url_list:
        return JSONResponse({"error": "no URLs provided"}, status_code=400)

    if _batch_task is not None and not _batch_task.done():
        return JSONResponse({"error": "batch already running"}, status_code=409)

    _cancel_token = asyncio.Event()
    _progress_queue = asyncio.Queue(maxsize=1000)
    _batch_summary = None

    _batch_task = asyncio.create_task(
        run_batch_scan(
            url_list,
            concurrency,
            force,
            stale_only,
            _progress_queue,
            _cancel_token,
        )
    )
    _batch_task.add_done_callback(_on_batch_done)

    return JSONResponse({"status": "started", "total": len(url_list)})


@admin_router.get("/batch/status")
async def admin_batch_status(
    credentials: HTTPBasicCredentials = Depends(require_admin),
):
    del credentials

    async def event_generator():
        running = _batch_task is not None and not _batch_task.done()
        if not running and _progress_queue is None:
            yield {"data": json.dumps({"idle": True})}
            return

        queue = _progress_queue
        if queue is None:
            yield {"data": json.dumps({"idle": True})}
            return

        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                if _batch_task is not None and _batch_task.done() and _batch_summary is not None:
                    item = {"finished": True, "summary": _summary_payload(_batch_summary)}
                    yield {"data": json.dumps(item)}
                    return
                continue

            yield {"data": json.dumps(item)}
            if "finished" in item:
                return

    return EventSourceResponse(event_generator())


@admin_router.post("/batch/cancel")
async def admin_batch_cancel(
    credentials: HTTPBasicCredentials = Depends(require_admin),
):
    del credentials
    if _cancel_token is not None:
        _cancel_token.set()
    return JSONResponse({"status": "cancelling"})


@admin_router.get("/default-urls")
async def get_default_urls(
    credentials: HTTPBasicCredentials = Depends(require_admin),
):
    del credentials
    url_file = Path(__file__).parent.parent / "data" / "default_urls.txt"
    content = url_file.read_text(encoding="utf-8") if url_file.exists() else ""
    return PlainTextResponse(content)
