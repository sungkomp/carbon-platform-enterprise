from __future__ import annotations
import json, hashlib
from datetime import date
from sqlalchemy.orm import Session
from app.models import EmissionFactor
from app.history.models import EmissionFactorVersion

def canonical_hash(payload: dict) -> str:
    b = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(b).hexdigest()

def snapshot_ef_payload(ef: EmissionFactor) -> dict:
    return {
        "key": ef.key,
        "name": ef.name,
        "unit": ef.unit,
        "value": ef.value,
        "scope": ef.scope,
        "category": ef.category,
        "tags": ef.tags,
        "region": ef.region,
        "country": ef.country,
        "sector": ef.sector,
        "lifecycle_stage": ef.lifecycle_stage,
        "activity_type": ef.activity_type,
        "methodology": ef.methodology,
        "gwp_version": ef.gwp_version,
        "publisher": ef.publisher,
        "source_url": ef.source_url,
        "document_title": ef.document_title,
        "page": ef.page,
        "table": ef.table,
        "valid_from": ef.valid_from.isoformat() if ef.valid_from else None,
        "valid_to": ef.valid_to.isoformat() if ef.valid_to else None,
        "status": ef.status,
        "lifecycle_status": getattr(ef, "lifecycle_status", None),
        "uncertainty_value": ef.uncertainty_value,
        "uncertainty_type": ef.uncertainty_type,
        "gas_breakdown": ef.gas_breakdown,
        "activity_id_fields": ef.activity_id_fields,
        "data_quality": ef.data_quality,
        "meta": ef.meta,
        "description": ef.description,
        "extra": ef.extra,
    }

def create_new_version(
    db: Session,
    *,
    org_id: int,
    ef_key: str,
    payload: dict,
    changed_by: str | None,
    change_reason: str | None,
    effective_from: date | None = None,
) -> str:
    effective_from = effective_from or date.today()
    h = canonical_hash(payload)

    prev = (db.query(EmissionFactorVersion)
              .filter(EmissionFactorVersion.org_id==org_id,
                      EmissionFactorVersion.ef_key==ef_key,
                      EmissionFactorVersion.effective_to==None)
              .order_by(EmissionFactorVersion.id.desc())
              .first())
    if prev:
        prev.effective_to = effective_from
        db.add(prev)

    v = EmissionFactorVersion(
        org_id=org_id,
        ef_key=ef_key,
        effective_from=effective_from,
        effective_to=None,
        payload=payload,
        payload_hash=h,
        changed_by=changed_by,
        change_reason=change_reason,
    )
    db.add(v)
    db.commit()
    return h
