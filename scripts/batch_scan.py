from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.scanner import Scanner

DEFAULT_URL_FILE = PROJECT_ROOT / "data" / "ecom_urls.txt"
RESULTS_DIR = PROJECT_ROOT / "data" / "results"
ALL_RESULTS_FILE = RESULTS_DIR / "all_results.json"


def json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return str(value)


def normalize_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def load_urls(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


async def run_batch(url_file: Path) -> None:
    if not url_file.exists():
        raise FileNotFoundError(f"URL file not found: {url_file}")

    urls = load_urls(url_file)
    total = len(urls)
    if total == 0:
        print(f"No URLs found in {url_file}")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    scanner = Scanner()
    combined_results: list[dict] = []
    summary_rows: list[tuple[str, str, float | None]] = []

    for idx, url in enumerate(urls, start=1):
        domain = normalize_domain(url)
        started = time.perf_counter()

        try:
            result = await scanner.scan(url)
            duration = time.perf_counter() - started

            payload = asdict(result)
            per_site_file = RESULTS_DIR / f"{domain}.json"
            per_site_file.write_text(
                json.dumps(payload, indent=2, default=json_default),
                encoding="utf-8",
            )

            grade = str(result.metadata.get("grade", "N/A"))
            score = float(result.overall_score)
            print(f"Scanning {idx}/{total}: {domain}... Grade: {grade} ({score:.2f}) [{duration:.1f}s]")

            combined_results.append(
                {
                    "domain": domain,
                    "url": url,
                    "grade": grade,
                    "score": score,
                    "duration_seconds": round(duration, 3),
                    "status": "ok",
                    "result": payload,
                }
            )
            summary_rows.append((domain, grade, score))
        except Exception as err:
            duration = time.perf_counter() - started
            print(f"Scanning {idx}/{total}: {domain}... ERROR: {type(err).__name__}: {err} [{duration:.1f}s]")

            combined_results.append(
                {
                    "domain": domain,
                    "url": url,
                    "status": "error",
                    "error_type": type(err).__name__,
                    "error": str(err),
                    "duration_seconds": round(duration, 3),
                }
            )
            summary_rows.append((domain, "ERROR", None))

        if idx < total:
            await asyncio.sleep(2)

    ALL_RESULTS_FILE.write_text(
        json.dumps(combined_results, indent=2, default=json_default),
        encoding="utf-8",
    )

    print("\nSummary (sorted by score desc)")
    print("domain | grade | score")
    for domain, grade, score in sorted(
        summary_rows,
        key=lambda row: row[2] if row[2] is not None else -1.0,
        reverse=True,
    ):
        score_text = f"{score:.2f}" if isinstance(score, float) else "N/A"
        print(f"{domain} | {grade} | {score_text}")


if __name__ == "__main__":
    url_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_URL_FILE
    asyncio.run(run_batch(url_path))
