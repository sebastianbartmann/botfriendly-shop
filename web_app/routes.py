from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sse_starlette.sse import EventSourceResponse

from checks.api_surface import APISurfaceCheck
from checks.discovery import DiscoveryCheck
from checks.feeds import FeedsCheck
from checks.product_parseability import ProductParseabilityCheck
from checks.robots import RobotsCheck
from checks.seo_meta import SeoMetaCheck
from checks.sitemap import SitemapCheck
from checks.structured_data import StructuredDataCheck
from core.models import CheckResult
from core.scanner import Scanner
from core.scoring import calculate_overall_score, get_grade

router = APIRouter()

CHECKS = [
    RobotsCheck(),
    DiscoveryCheck(),
    SitemapCheck(),
    StructuredDataCheck(),
    SeoMetaCheck(),
    FeedsCheck(),
    APISurfaceCheck(),
    ProductParseabilityCheck(),
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
}

scans: dict[str, dict[str, Any]] = {}


def _is_valid_url(url: str) -> bool:
    candidate = (url or "").strip()
    return candidate.startswith("http://") or candidate.startswith("https://")


def _normalize_url(url: str) -> str:
    candidate = (url or "").strip()
    if candidate and not candidate.startswith(("http://", "https://")):
        return f"https://{candidate}"
    return candidate


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


@router.get("/")
async def home(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("index.html", {"request": request})


@router.post("/scan")
async def start_scan(request: Request):
    form = await request.form()
    raw_url = _normalize_url(str(form.get("url", "")))

    if not _is_valid_url(raw_url):
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "error": "Please enter a valid URL that starts with http:// or https://",
                "url": raw_url,
            },
            status_code=400,
        )

    scan_id = str(uuid4())
    scans[scan_id] = {
        "url": raw_url,
        "status": "pending",
        "results": [],
        "overall": None,
        "grade": None,
        "error": None,
    }
    return RedirectResponse(url=f"/results/{scan_id}", status_code=303)


@router.get("/results/{scan_id}")
async def results_page(request: Request, scan_id: str):
    scan = scans.get(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "scan_id": scan_id,
            "url": scan["url"],
            "check_count": len(CHECKS),
            "categories": [check.__class__.__name__ for check in CHECKS],
            "category_labels": CATEGORY_LABELS,
        },
    )


@router.get("/api/stream/{scan_id}")
async def stream_scan(request: Request, scan_id: str):
    scan = scans.get(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    async def event_generator():
        url = scan["url"]
        start_event = {"type": "start", "url": url, "check_count": len(CHECKS)}
        yield {"data": json.dumps(start_event)}

        if scan.get("status") == "complete" and scan.get("results"):
            for prior in scan["results"]:
                if await request.is_disconnected():
                    return
                yield {"data": json.dumps(prior)}
            yield {
                "data": json.dumps(
                    {
                        "type": "complete",
                        "overall_score": scan.get("overall"),
                        "grade": scan.get("grade"),
                        "check_count": len(scan["results"]),
                    }
                )
            }
            return

        scan["status"] = "running"
        scan["results"] = []
        scan["overall"] = None
        scan["grade"] = None
        scan["error"] = None
        check_results: list[CheckResult] = []

        try:
            scanner = Scanner(checks=[])
            artifacts = await scanner._http_pass(url)

            for check in CHECKS:
                if await request.is_disconnected():
                    return

                result = await check.run(url, artifacts)
                check_results.append(result)

                result_payload = _serialize_check_result(result)
                check_event = {
                    "type": "check",
                    "category": result.category,
                    "category_label": result_payload["category_label"],
                    "score": result.score,
                    "severity": result.severity.value,
                    "signals": result_payload["signals"],
                    "details": result_payload["details"],
                    "recommendations": result.recommendations,
                }
                scan["results"].append(check_event)
                yield {"data": json.dumps(check_event)}

            overall_score = calculate_overall_score(check_results)
            grade = get_grade(overall_score)
            complete_event = {
                "type": "complete",
                "overall_score": overall_score,
                "grade": grade,
                "check_count": len(check_results),
            }

            scan["status"] = "complete"
            scan["overall"] = overall_score
            scan["grade"] = grade
            yield {"data": json.dumps(complete_event)}

        except Exception as exc:
            scan["status"] = "error"
            scan["error"] = str(exc)
            error_event = {"type": "error", "message": f"Scan failed: {exc}"}
            yield {"data": json.dumps(error_event)}

    return EventSourceResponse(event_generator())


@router.get("/api/v1/scan")
async def scan_json(url: str = Query(..., description="Site URL to scan")):
    if not _is_valid_url(url):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid URL. It must start with http:// or https://"},
        )

    result = await Scanner().scan(url.strip())
    payload = {
        "url": result.url,
        "overall_score": result.overall_score,
        "metadata": _json_safe(result.metadata),
        "check_results": [_serialize_check_result(item) for item in result.check_results],
    }
    return JSONResponse(content=payload)
