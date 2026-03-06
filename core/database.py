from __future__ import annotations

import asyncio
import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.db_models import Base

def _default_db_path() -> Path:
    # Prefer mounted persistent paths in container deployments.
    for candidate_dir in (Path("/data"), Path("/app/data")):
        if candidate_dir.is_dir() and os.access(candidate_dir, os.W_OK):
            return candidate_dir / "botfriendly_shop.db"
    return Path("data/botfriendly_shop.db")


raw_db_path = os.getenv("BOTFRIENDLY_SHOP_DB_PATH")
DB_PATH = Path(raw_db_path).expanduser() if raw_db_path else _default_db_path()
if not DB_PATH.is_absolute():
    DB_PATH = Path.cwd() / DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


_init_lock = asyncio.Lock()
_initialized = False


async def init_db() -> None:
    global _initialized
    if _initialized:
        return

    async with _init_lock:
        if _initialized:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _migrate_sqlite_schema(conn)
        _initialized = True


async def _migrate_sqlite_schema(conn) -> None:
    if conn.dialect.name != "sqlite":
        return

    def _run_sqlite_migrations(sync_conn) -> None:
        table_rows = sync_conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        tables = {str(row[0]) for row in table_rows}

        if "scans" in tables:
            scan_columns = _sqlite_table_columns(sync_conn, "scans")
            missing_scan_columns = {
                "source": "ALTER TABLE scans ADD COLUMN source VARCHAR NOT NULL DEFAULT 'web'",
                "error": "ALTER TABLE scans ADD COLUMN error TEXT",
                "scanner_version": "ALTER TABLE scans ADD COLUMN scanner_version VARCHAR NOT NULL DEFAULT 'unknown'",
                "overall_score": "ALTER TABLE scans ADD COLUMN overall_score FLOAT",
                "grade": "ALTER TABLE scans ADD COLUMN grade VARCHAR",
                "duration_ms": "ALTER TABLE scans ADD COLUMN duration_ms INTEGER",
                "result_json": "ALTER TABLE scans ADD COLUMN result_json TEXT",
                "started_at": "ALTER TABLE scans ADD COLUMN started_at VARCHAR NOT NULL DEFAULT ''",
                "completed_at": "ALTER TABLE scans ADD COLUMN completed_at VARCHAR",
                "created_at": "ALTER TABLE scans ADD COLUMN created_at VARCHAR NOT NULL DEFAULT ''",
            }
            for column_name, ddl in missing_scan_columns.items():
                if column_name not in scan_columns:
                    sync_conn.exec_driver_sql(ddl)

        if "scan_checks" in tables:
            check_columns = _sqlite_table_columns(sync_conn, "scan_checks")
            missing_check_columns = {
                "severity": "ALTER TABLE scan_checks ADD COLUMN severity VARCHAR",
                "details_json": "ALTER TABLE scan_checks ADD COLUMN details_json TEXT",
                "signals_json": "ALTER TABLE scan_checks ADD COLUMN signals_json TEXT",
            }
            for column_name, ddl in missing_check_columns.items():
                if column_name not in check_columns:
                    sync_conn.exec_driver_sql(ddl)

            sync_conn.exec_driver_sql(
                """
                DELETE FROM scan_checks
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM scan_checks
                    GROUP BY scan_id, category
                )
                """
            )
            sync_conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_scan_checks_scan_category "
                "ON scan_checks (scan_id, category)"
            )

    await conn.run_sync(_run_sqlite_migrations)


def _sqlite_table_columns(sync_conn, table_name: str) -> set[str]:
    rows = sync_conn.exec_driver_sql(f"PRAGMA table_info('{table_name}')").fetchall()
    return {str(row[1]) for row in rows}
