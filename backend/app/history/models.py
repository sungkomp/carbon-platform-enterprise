from __future__ import annotations
from datetime import datetime, date
from sqlalchemy import Date, DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

class EmissionFactorVersion(Base):
    __tablename__ = "emission_factor_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    ef_key: Mapped[str] = mapped_column(String, index=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_hash: Mapped[str] = mapped_column(String, index=True)
    changed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    change_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class RunSignature(Base):
    __tablename__ = "run_signatures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    algo: Mapped[str] = mapped_column(String, default="ed25519")
    run_hash: Mapped[str] = mapped_column(String, index=True)
    signature_b64: Mapped[str] = mapped_column(String)
    public_key_pem: Mapped[str] = mapped_column(String)
    signed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
