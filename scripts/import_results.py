from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "data" / "results"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "ecom_checker.db"
LEGACY_SCANNER_VERSION = "0.9.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_db_path(db_path: str | None) -> Path:
    candidate = Path(db_path).expanduser() if db_path else DEFAULT_DB_PATH
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def _extract_domain(url: str, fallback: str) -> str:
    host = (urlparse(url).hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host or fallback.lower()


def _normalize_url(url: str, domain: str) -> str:
    candidate = (url or "").strip()
    if not candidate:
        return f"https://{domain}"
    if not candidate.startswith(("http://", "https://")):
        return f"https://{candidate}"
    return candidate


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _duration_ms(metadata: dict[str, Any]) -> int | None:
    for key in ("duration_ms", "durationMillis", "duration_millis", "duration"):
        if key in metadata:
            value = metadata.get(key)
            try:
                if value is None:
                    return None
                return int(float(value))
            except (TypeError, ValueError):
                return None

    seconds = metadata.get("duration_seconds")
    try:
        if seconds is None:
            return None
        return int(float(seconds) * 1000)
    except (TypeError, ValueError):
        return None


def _ensure_schema(conn: sqlite3.Connection) -> None:
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


def _domain_exists(conn: sqlite3.Connection, domain: str) -> bool:
    row = conn.execute("SELECT 1 FROM scans WHERE domain = ? LIMIT 1", (domain,)).fetchone()
    return row is not None


def import_results(db_path: str | None = None) -> None:
    resolved_db = _resolve_db_path(db_path)
    files = sorted(p for p in RESULTS_DIR.glob("*.json") if p.name != "all_results.json")

    if not RESULTS_DIR.exists():
        raise FileNotFoundError(f"Results directory not found: {RESULTS_DIR}")

    imported = 0
    skipped = 0
    failed = 0

    conn = sqlite3.connect(str(resolved_db))
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)

    try:
        for file_path in files:
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("result payload is not a JSON object")

                url = str(payload.get("url", "")).strip()
                domain = _extract_domain(url, file_path.stem)
                normalized_url = _normalize_url(url, domain)

                if _domain_exists(conn, domain):
                    skipped += 1
                    continue

                metadata = payload.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}

                check_results = payload.get("check_results")
                if not isinstance(check_results, list):
                    check_results = []

                now = _now_iso()
                scan_id = str(uuid4())

                conn.execute(
                    """
                    INSERT INTO scans (
                        id, domain, normalized_url, source, status,
                        scanner_version, overall_score, grade, duration_ms,
                        result_json, started_at, completed_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
                        domain,
                        normalized_url,
                        "batch",
                        "complete",
                        LEGACY_SCANNER_VERSION,
                        _as_float(payload.get("overall_score")),
                        str(metadata.get("grade")) if metadata.get("grade") is not None else None,
                        _duration_ms(metadata),
                        json.dumps(payload),
                        now,
                        now,
                        now,
                    ),
                )

                for check in check_results:
                    if not isinstance(check, dict):
                        continue
                    category = str(check.get("category", "")).strip()
                    if not category:
                        continue

                    score = _as_float(check.get("score"))
                    if score is None:
                        score = 0.0

                    conn.execute(
                        """
                        INSERT INTO scan_checks (
                            scan_id, category, score, severity, details_json, signals_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            scan_id,
                            category,
                            score,
                            str(check.get("severity")) if check.get("severity") is not None else None,
                            json.dumps(check.get("details", {})),
                            json.dumps(check.get("signals", [])),
                        ),
                    )

                conn.commit()
                imported += 1
            except Exception as exc:
                conn.rollback()
                failed += 1
                print(f"failed {file_path.name}: {type(exc).__name__}: {exc}")
    finally:
        conn.close()

    print(f"imported={imported} skipped={skipped} failed={failed}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import per-domain scan results JSON into SQLite")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Path to SQLite DB")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    import_results(db_path=args.db_path)
