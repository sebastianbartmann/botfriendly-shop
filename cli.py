from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from enum import Enum
from urllib.parse import urlparse

import httpx

from core.models import CheckResult, ScanResult, Severity, Signal
from core.scanner import Scanner

COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_GRAY = "\033[90m"
COLOR_CYAN = "\033[96m"
COLOR_BOLD = "\033[1m"

SEVERITY_COLORS = {
    Severity.PASS: COLOR_GREEN,
    Severity.PARTIAL: COLOR_YELLOW,
    Severity.FAIL: COLOR_RED,
    Severity.INCONCLUSIVE: COLOR_GRAY,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan an ecommerce site for LLM readiness.",
        usage="python cli.py <url> [--json]",
    )
    parser.add_argument("url", help="Target URL, for example: https://example.com")
    parser.add_argument("--json", action="store_true", help="Output full ScanResult as JSON")
    return parser.parse_args()


def normalize_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Invalid URL. Use an absolute URL like https://example.com")
    return raw_url


async def ensure_reachable(url: str) -> None:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            await client.get(url)
    except httpx.HTTPError as err:
        raise ConnectionError(f"Connection failed for {url}: {err}") from err


async def run_scan(url: str) -> ScanResult:
    await ensure_reachable(url)
    return await Scanner().scan(url)


def bar_for_score(score: float, width: int = 10) -> str:
    filled = max(0, min(width, round(score * width)))
    return "█" * filled + "░" * (width - filled)


def score_to_severity(score: float) -> Severity:
    if score >= 0.8:
        return Severity.PASS
    if score >= 0.5:
        return Severity.PARTIAL
    return Severity.FAIL


def format_signal_value(signal: Signal) -> str:
    value = signal.value
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def top_signals(signals: list[Signal], limit: int = 3) -> list[Signal]:
    preferred = [s for s in signals if s.severity is not Severity.INCONCLUSIVE]
    return (preferred or signals)[:limit]


def print_check(check: CheckResult) -> None:
    severity_color = SEVERITY_COLORS.get(check.severity, COLOR_GRAY)
    score_color = SEVERITY_COLORS.get(score_to_severity(check.score), COLOR_GRAY)
    indicator = f"{severity_color}●{COLOR_RESET}"
    bar = f"{score_color}{bar_for_score(check.score)}{COLOR_RESET}"

    print(f"{indicator} {check.category:22} {bar}  {check.score:.2f}  {severity_color}{check.severity.value.upper()}{COLOR_RESET}")

    signals = top_signals(check.signals)
    if signals:
        rendered = ", ".join(f"{s.name}={format_signal_value(s)}" for s in signals)
        print(f"   Top signals: {rendered}")
    else:
        print("   Top signals: none")

    if check.recommendations:
        print(f"   Recommendations: {'; '.join(check.recommendations[:3])}")
    else:
        print("   Recommendations: none")


def print_report(result: ScanResult) -> None:
    grade = result.metadata.get("grade", "N/A")
    print(f"{COLOR_BOLD}{COLOR_CYAN}botfriendly.shop AI Readiness Report{COLOR_RESET}")
    print(f"URL: {result.url}")
    print(f"Overall: Grade: {grade} ({result.overall_score:.2f})")
    print("")

    for check in result.check_results:
        print_check(check)
        print("")


def json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return str(value)


def main() -> None:
    args = parse_args()

    try:
        url = normalize_url(args.url)
        result = asyncio.run(run_scan(url))
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        raise SystemExit(1)
    except ConnectionError as err:
        print(f"Error: {err}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as err:
        print(f"Error: Scan failed: {err}", file=sys.stderr)
        raise SystemExit(1)

    if args.json:
        print(json.dumps(asdict(result), indent=2, default=json_default))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
