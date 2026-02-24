from __future__ import annotations

import asyncio
import sqlite3

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core import database
from core.db_models import Base, ScanCheckRecord as ScanCheck, ScanRecord as Scan


@pytest_asyncio.fixture
async def db_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine, raising=True)
    monkeypatch.setattr(database, "async_session_factory", async_session, raising=True)
    monkeypatch.setattr(database, "_init_lock", asyncio.Lock(), raising=True)
    monkeypatch.setattr(database, "_initialized", False, raising=True)

    async with async_session() as session:
        yield session

    await engine.dispose()


def _scan(scan_id: str, domain: str) -> Scan:
    now = "2026-02-24T00:00:00+00:00"
    return Scan(
        id=scan_id,
        domain=domain,
        normalized_url=f"https://{domain}",
        source="test",
        status="complete",
        scanner_version="1.0.0",
        started_at=now,
        completed_at=now,
    )


@pytest.mark.asyncio
async def test_init_db_creates_both_tables(db_session: AsyncSession):
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await database.init_db()

    async with database.engine.begin() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "scans" in table_names
    assert "scan_checks" in table_names


@pytest.mark.asyncio
async def test_insert_scan_and_read_back(db_session: AsyncSession):
    scan = _scan("scan-1", "example.com")
    db_session.add(scan)
    await db_session.commit()

    result = await db_session.execute(select(Scan).where(Scan.id == "scan-1"))
    saved = result.scalar_one()

    assert saved.domain == "example.com"
    assert saved.normalized_url == "https://example.com"
    assert saved.status == "complete"


@pytest.mark.asyncio
async def test_insert_scan_checks_linked_to_scan(db_session: AsyncSession):
    db_session.add(_scan("scan-2", "example.com"))
    db_session.add_all(
        [
            ScanCheck(scan_id="scan-2", category="robots", score=1.0, severity="pass"),
            ScanCheck(scan_id="scan-2", category="structured_data", score=0.8, severity="warn"),
        ]
    )
    await db_session.commit()

    result = await db_session.execute(
        select(ScanCheck).where(ScanCheck.scan_id == "scan-2").order_by(ScanCheck.category)
    )
    checks = result.scalars().all()

    assert len(checks) == 2
    assert checks[0].category == "robots"
    assert checks[1].category == "structured_data"


@pytest.mark.asyncio
async def test_query_scans_by_domain(db_session: AsyncSession):
    db_session.add_all(
        [
            _scan("scan-3", "example.com"),
            _scan("scan-4", "example.com"),
            _scan("scan-5", "other.com"),
        ]
    )
    await db_session.commit()

    result = await db_session.execute(select(Scan).where(Scan.domain == "example.com").order_by(Scan.id))
    scans = result.scalars().all()

    assert [scan.id for scan in scans] == ["scan-3", "scan-4"]


@pytest.mark.asyncio
async def test_unique_constraint_on_scan_id_and_category(db_session: AsyncSession):
    db_session.add(_scan("scan-6", "example.com"))
    await db_session.flush()

    db_session.add_all(
        [
            ScanCheck(scan_id="scan-6", category="robots", score=1.0),
            ScanCheck(scan_id="scan-6", category="robots", score=0.5),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_init_db_migrates_legacy_sqlite_schema(monkeypatch, tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE scans (
            id VARCHAR PRIMARY KEY NOT NULL,
            domain VARCHAR NOT NULL,
            normalized_url VARCHAR NOT NULL,
            status VARCHAR NOT NULL
        );
        CREATE TABLE scan_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            scan_id VARCHAR NOT NULL,
            category VARCHAR NOT NULL,
            score FLOAT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine, raising=True)
    monkeypatch.setattr(database, "async_session_factory", async_session, raising=True)
    monkeypatch.setattr(database, "_init_lock", asyncio.Lock(), raising=True)
    monkeypatch.setattr(database, "_initialized", False, raising=True)

    await database.init_db()

    async with engine.begin() as db_conn:
        scan_columns = await db_conn.execute(text("PRAGMA table_info('scans')"))
        check_columns = await db_conn.execute(text("PRAGMA table_info('scan_checks')"))
        index_rows = await db_conn.execute(text("PRAGMA index_list('scan_checks')"))
        scan_column_names = {str(row[1]) for row in scan_columns.fetchall()}
        check_column_names = {str(row[1]) for row in check_columns.fetchall()}
        index_names = {str(row[1]) for row in index_rows.fetchall()}

        await db_conn.execute(
            text(
                """
                INSERT INTO scans (
                    id, domain, normalized_url, source, status, scanner_version, started_at, created_at
                ) VALUES (
                    'legacy-scan', 'example.com', 'https://example.com', 'web', 'running', '1.0.0', 'now', 'now'
                )
                """
            )
        )
        await db_conn.execute(
            text(
                """
                UPDATE scans
                SET overall_score = 0.5, grade = 'C', duration_ms = 100, result_json = '{}', completed_at = 'now'
                WHERE id = 'legacy-scan'
                """
            )
        )

    assert "source" in scan_column_names
    assert "scanner_version" in scan_column_names
    assert "overall_score" in scan_column_names
    assert "grade" in scan_column_names
    assert "started_at" in scan_column_names
    assert "completed_at" in scan_column_names
    assert "created_at" in scan_column_names
    assert "severity" in check_column_names
    assert "details_json" in check_column_names
    assert "signals_json" in check_column_names
    assert "uq_scan_checks_scan_category" in index_names

    await engine.dispose()
