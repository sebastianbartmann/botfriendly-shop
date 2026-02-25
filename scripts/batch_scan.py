from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.batch import BatchResult, run_batch_scan
from core.database import DB_PATH

DEFAULT_URL_FILE = PROJECT_ROOT / "data" / "ecom_urls.txt"
DEFAULT_DB_PATH = DB_PATH


def load_urls(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


async def run_batch(args: argparse.Namespace) -> dict[str, Any]:
    url_file = Path(args.url_file)
    if not url_file.is_absolute():
        url_file = PROJECT_ROOT / url_file

    if not url_file.exists():
        raise FileNotFoundError(f"URL file not found: {url_file}")

    urls = load_urls(url_file)
    total = len(urls)
    if total == 0:
        print(f"No URLs found in {url_file}")
        return {"total": 0, "success": 0, "failed": 0, "skipped": 0, "duration_s": 0.0}

    progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

    runner = asyncio.create_task(
        run_batch_scan(
            urls,
            concurrency=args.concurrency,
            force=args.force,
            stale_only=args.stale_only,
            progress_queue=progress_queue,
        )
    )

    while not runner.done() or not progress_queue.empty():
        try:
            event = await asyncio.wait_for(progress_queue.get(), timeout=0.25)
        except asyncio.TimeoutError:
            continue
        grade = event.get("grade") or "-"
        error = event.get("error")
        suffix = f" ({error})" if error else ""
        print(f"[{event['done']}/{event['total']}] {event['url']} -> {event['status']} {grade}{suffix}")

    result: BatchResult = await runner

    payload = {
        "total": result.total,
        "success": result.success,
        "failed": result.failed,
        "skipped": result.skipped,
        "duration_s": result.duration_s,
    }

    print("\nTotals")
    print(
        "total={total} success={success} failed={failed} skipped={skipped} duration_s={duration:.2f}".format(
            total=result.total,
            success=result.success,
            failed=result.failed,
            skipped=result.skipped,
            duration=result.duration_s,
        )
    )

    if args.json:
        print(json.dumps(payload))

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
        help="Deprecated. DB path is configured via ECOM_CHECKER_DB_PATH environment variable.",
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
