from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core import database
from core.db_models import Base
from web_app import routes
from web_app.main import app


@pytest_asyncio.fixture
async def stats_test_db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///file::memory:?cache=shared",
        connect_args={"uri": True},
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine, raising=True)
    monkeypatch.setattr(database, "async_session_factory", async_session, raising=True)
    monkeypatch.setattr(database, "_init_lock", asyncio.Lock(), raising=True)
    monkeypatch.setattr(database, "_initialized", False, raising=True)

    monkeypatch.setattr(routes, "async_session_factory", async_session, raising=True)
    monkeypatch.setattr(routes, "init_db", database.init_db, raising=True)

    yield async_session
    await engine.dispose()


@pytest.mark.asyncio
async def test_stats_page_returns_200(stats_test_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/stats")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_stats_page_contains_dashboard_elements(stats_test_db):
    async with stats_test_db() as session:
        await session.execute(
            text(
                """
                INSERT INTO scans (id, domain, normalized_url, source, status, scanner_version, overall_score, grade, started_at, completed_at, created_at)
                VALUES (:id, :domain, :normalized_url, :source, :status, :scanner_version, :overall_score, :grade, :started_at, :completed_at, :created_at)
                """
            ),
            {
                "id": "scan-stats-1",
                "domain": "example.com",
                "normalized_url": "https://example.com",
                "source": "test",
                "status": "complete",
                "scanner_version": "1.0.0",
                "overall_score": 0.91,
                "grade": "A",
                "started_at": "2026-02-24T00:00:00+00:00",
                "completed_at": "2026-02-24T00:01:00+00:00",
                "created_at": "2026-02-24T00:00:00+00:00",
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO scan_checks (scan_id, category, score, severity, details_json, signals_json)
                VALUES (:scan_id, :category, :score, :severity, :details_json, :signals_json)
                """
            ),
            {
                "scan_id": "scan-stats-1",
                "category": "robots",
                "score": 0.7,
                "severity": "fail",
                "details_json": "{}",
                "signals_json": json.dumps(
                    [
                        {"name": "gptbot_disallow", "severity": "fail"},
                        {"name": "robots_exists", "severity": "pass"},
                    ]
                ),
            },
        )
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/stats")

    assert response.status_code == 200
    assert 'id="gradeChart"' in response.text
    assert 'id="categoryChart"' in response.text
    assert 'id="histogramChart"' in response.text
    assert 'id="top-domains-table"' in response.text
    assert 'id="bottom-domains-table"' in response.text
    assert 'id="recent-scans-table"' in response.text


@pytest.mark.asyncio
async def test_stats_page_empty_db_returns_200(stats_test_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/stats")

    assert response.status_code == 200
    assert "Scan Statistics" in response.text
