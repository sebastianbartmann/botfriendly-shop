from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core import database
from core.db_models import Base, Scan, ScanCheck


@pytest_asyncio.fixture
async def db_session(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine, raising=True)
    monkeypatch.setattr(database, "async_session_factory", async_session, raising=True)
    monkeypatch.setattr(database, "_init_lock", asyncio.Lock(), raising=True)
    monkeypatch.setattr(database, "_initialized", False, raising=True)

    async with async_session() as session:
        yield session


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
