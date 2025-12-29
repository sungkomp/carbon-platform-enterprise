from __future__ import annotations
from sqlalchemy.orm import Session
from app.history.models import AuditEvent

def emit_event(db: Session, org_id: int, actor: str | None, action: str, payload: dict):
    ev = AuditEvent(org_id=org_id, actor=actor, action=action, payload=payload or {})
    db.add(ev)
    db.commit()
    return ev.id
