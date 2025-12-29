from __future__ import annotations
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.services.audit_engine import audit_run

def job_run_audit(run_id: int) -> dict:
    db: Session = SessionLocal()
    try:
        return audit_run(db, run_id)
    finally:
        db.close()
