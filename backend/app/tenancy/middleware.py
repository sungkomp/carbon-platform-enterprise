from __future__ import annotations
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.tenancy.models import Org

ORG_HEADER = "X-Org-Slug"

async def org_context_middleware(request: Request, call_next):
    # allow login without org header
    if request.url.path.startswith("/api/auth/"):
        return await call_next(request)

    slug = request.headers.get(ORG_HEADER)
    if not slug:
        raise HTTPException(400, f"{ORG_HEADER} header required")
    db: Session = SessionLocal()
    try:
        org = db.query(Org).filter(Org.slug == slug).one_or_none()
        if not org:
            raise HTTPException(404, "Org not found")
        request.state.org = org
        return await call_next(request)
    finally:
        db.close()
