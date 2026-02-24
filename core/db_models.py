from __future__ import annotations

from typing import List

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ScanRecord(Base):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    domain: Mapped[str] = mapped_column(String, nullable=False, index=True)
    normalized_url: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scanner_version: Mapped[str] = mapped_column(String, nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, server_default=text("(datetime('now'))"), index=True)

    checks: Mapped[List["ScanCheckRecord"]] = relationship(
        back_populates="scan",
        cascade="all, delete-orphan",
    )


class ScanCheckRecord(Base):
    __tablename__ = "scan_checks"
    __table_args__ = (UniqueConstraint("scan_id", "category", name="uq_scan_checks_scan_category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str | None] = mapped_column(String, nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    signals_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    scan: Mapped[ScanRecord] = relationship(back_populates="checks")


# Backward-compatible aliases used by tests and higher-level code.
Scan = ScanRecord
ScanCheck = ScanCheckRecord
