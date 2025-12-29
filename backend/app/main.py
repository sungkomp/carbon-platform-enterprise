from __future__ import annotations

import io, json, os, datetime
import pandas as pd
import redis
from rq import Queue

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.config import settings
from app.db import Base, engine, get_db
from app.models import EmissionFactor, Activity, CalculationRun, CarbonCreditProject
from app.history.models import RunSignature
from app.tenancy.middleware import org_context_middleware
from app.tenancy.models import Org, OrgMember

from app.services.ef_service import upsert_seed_efs
from app.services.calc_service import compute_run
from app.services.credit_service import calc_carbon_credit
from app.services.audit_engine import audit_run
from app.services.report_export import export_run_pdf, export_run_excel
from app.services.audit_events import emit_event
from app.services.ef_versioning import snapshot_ef_payload, create_new_version
from app.services.signing import load_or_generate_keypair, run_hash as calc_run_hash, sign_hash, verify_hash

from app.auth.routes import router as auth_router
from app.auth.security import require_org_roles, hash_password
from app.auth.models import User

from app.rate_limit import build_limiter
from app.observability import configure_logging, REQ_COUNTER, REQ_LATENCY

from app.jobs import job_run_audit

configure_logging()

app = FastAPI(title="Carbon Platform", version="3.2.0-enterprise")

# tenancy middleware (requires X-Org-Slug for most routes)
app.middleware("http")(org_context_middleware)

# rate limiting
limiter = build_limiter()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# cors
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def metrics_mw(request: Request, call_next):
    path = request.url.path
    with REQ_LATENCY.labels(path=path).time():
        resp = await call_next(request)
    REQ_COUNTER.labels(method=request.method, path=path, status=str(resp.status_code)).inc()
    return resp

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.on_event("startup")
def startup():
    # In production: use Alembic migrations
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        org = db.query(Org).filter(Org.slug == "kmutt").one_or_none()
        if not org:
            org = Org(slug="kmutt", name="KMUTT")
            db.add(org)
            db.commit()
            db.refresh(org)

        n, warnings = upsert_seed_efs(db)
        if warnings:
            print("[seed warnings]", *warnings, sep="\n- ")
        print(f"[seed] upserted {n} EF rows")

        admin = db.query(User).filter(User.username == "admin").one_or_none()
        if not admin:
            db.add(User(username="admin", password_hash=hash_password("admin1234"), roles=["ADMIN"]))
            db.commit()
            admin = db.query(User).filter(User.username == "admin").one()

        mem = db.query(OrgMember).filter(OrgMember.org_id == org.id, OrgMember.user_id == admin.id).one_or_none()
        if not mem:
            db.add(OrgMember(org_id=org.id, user_id=admin.id, roles=[
                "EXPERT","CALCULATOR","POLICY_ADVISOR","VERIFIER","AUDITOR","PROJECT_DEVELOPER"
            ]))
            db.commit()

    finally:
        db.close()

app.include_router(auth_router)

# -------- EF --------
@app.get("/api/efs")
def list_efs(request: Request, q: str | None = None, limit: int = 500, db: Session = Depends(get_db)):
    org_id = request.state.org.id
    qry = db.query(EmissionFactor).filter(EmissionFactor.org_id == org_id)
    if q:
        like = f"%{q}%"
        qry = qry.filter((EmissionFactor.name.ilike(like)) | (EmissionFactor.key.ilike(like)))
    rows = qry.limit(limit).all()
    return [{
        "key": r.key, "name": r.name, "unit": r.unit, "value": r.value,
        "scope": r.scope, "category": r.category, "tags": r.tags,
        "valid_from": r.valid_from.isoformat() if r.valid_from else None,
        "valid_to": r.valid_to.isoformat() if r.valid_to else None,
        "region": r.region,
        "lifecycle_status": r.lifecycle_status,
        "activity_id_fields": r.activity_id_fields, "gas_breakdown": r.gas_breakdown,
        "gwp_version": r.gwp_version, "meta": r.meta
    } for r in rows]

@app.get("/api/efs/{key}")
def get_ef(request: Request, key: str, db: Session = Depends(get_db)):
    org_id = request.state.org.id
    r = db.query(EmissionFactor).filter(EmissionFactor.org_id==org_id, EmissionFactor.key == key).one_or_none()
    if not r:
        raise HTTPException(404, "EF not found")
    return {
        "key": r.key, "name": r.name, "unit": r.unit, "value": r.value,
        "scope": r.scope, "category": r.category, "tags": r.tags,
        "activity_id_fields": r.activity_id_fields, "gas_breakdown": r.gas_breakdown,
        "methodology": r.methodology, "gwp_version": r.gwp_version,
        "publisher": r.publisher, "document_title": r.document_title,
        "valid_from": r.valid_from.isoformat() if r.valid_from else None,
        "valid_to": r.valid_to.isoformat() if r.valid_to else None,
        "uncertainty_value": r.uncertainty_value,
        "uncertainty_type": r.uncertainty_type,
        "lifecycle_status": r.lifecycle_status,
        "review_notes": r.review_notes,
        "meta": r.meta
    }

@app.post("/api/efs")
def upsert_ef(request: Request, payload: dict, db: Session = Depends(get_db), user=Depends(require_org_roles("EXPERT"))):
    org_id = request.state.org.id
    key = payload.get("key")
    if not key:
        raise HTTPException(400, "key required")

    obj = db.query(EmissionFactor).filter(EmissionFactor.org_id==org_id, EmissionFactor.key == key).one_or_none()
    if obj:
        for k, v in payload.items():
            setattr(obj, k, v)
    else:
        payload["org_id"] = org_id
        db.add(EmissionFactor(**payload))
    db.commit()

    ef = db.query(EmissionFactor).filter(EmissionFactor.org_id==org_id, EmissionFactor.key==key).one()
    h = create_new_version(db, org_id=org_id, ef_key=key, payload=snapshot_ef_payload(ef), changed_by=user.username, change_reason=payload.get("review_notes") or "upsert")
    emit_event(db, org_id, user.username, "EF_UPSERT", {"ef_key": key, "payload_hash": h})
    return {"ok": True, "key": key, "payload_hash": h}

@app.post("/api/efs/import")
async def import_efs(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(require_org_roles("EXPERT"))):
    org_id = request.state.org.id
    content = await file.read()
    name = (file.filename or "").lower()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content))
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(io.BytesIO(content))
    else:
        raise HTTPException(400, "Only CSV/Excel")
    df.columns = [c.strip().lower() for c in df.columns]
    required = {"key","name","unit","scope","category"}
    if not required.issubset(set(df.columns)):
        raise HTTPException(400, f"Missing columns: need {sorted(required)}")

    def j(v):
        if v is None or (isinstance(v, float) and pd.isna(v)): return {}
        if isinstance(v, dict): return v
        s = str(v).strip()
        if not s or s.lower() == "nan": return {}
        try: return json.loads(s)
        except: return {}

    def tags(v):
        if v is None or (isinstance(v, float) and pd.isna(v)): return []
        if isinstance(v, list): return v
        s = str(v).strip()
        return [x.strip() for x in s.split(",") if x.strip()]

    count = 0
    for _, row in df.iterrows():
        payload = {k: row.get(k) for k in df.columns}
        payload["org_id"] = org_id
        payload["value"] = None if ("value" not in payload or pd.isna(payload.get("value"))) else float(payload["value"])
        payload["tags"] = tags(payload.get("tags"))
        payload["activity_id_fields"] = j(payload.get("activity_id_fields"))
        payload["gas_breakdown"] = j(payload.get("gas_breakdown"))
        payload["meta"] = j(payload.get("meta"))
        key = str(payload["key"]).strip()

        obj = db.query(EmissionFactor).filter(EmissionFactor.org_id==org_id, EmissionFactor.key == key).one_or_none()
        if obj:
            for k, v in payload.items():
                setattr(obj, k, v)
        else:
            db.add(EmissionFactor(**payload))
        count += 1
    db.commit()
    emit_event(db, org_id, user.username, "EF_IMPORT", {"count": count, "filename": file.filename})
    return {"ok": True, "imported": count}

# -------- Activities --------
@app.get("/api/activities")
def list_activities(request: Request, db: Session = Depends(get_db), user=Depends(require_org_roles("CALCULATOR","EXPERT"))):
    org_id = request.state.org.id
    rows = db.query(Activity).filter(Activity.org_id==org_id).order_by(Activity.id.desc()).all()
    return [{
        "id": a.id, "name": a.name, "ef_key": a.ef_key,
        "inputs": a.inputs, "scope": a.scope, "period": a.period
    } for a in rows]

@app.post("/api/activities")
def create_activity(request: Request, payload: dict, db: Session = Depends(get_db), user=Depends(require_org_roles("CALCULATOR","EXPERT"))):
    org_id = request.state.org.id
    if not payload.get("ef_key"):
        raise HTTPException(400, "ef_key required")
    a = Activity(
        org_id=org_id,
        name=payload.get("name",""),
        ef_key=payload["ef_key"],
        inputs=payload.get("inputs") or {},
        scope=payload.get("scope","Scope3"),
        period=payload.get("period"),
        note=payload.get("note"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    emit_event(db, org_id, user.username, "ACTIVITY_CREATED", {"activity_id": a.id, "ef_key": a.ef_key})
    return {"ok": True, "id": a.id}

@app.delete("/api/activities/{activity_id}")
def delete_activity(request: Request, activity_id: int, db: Session = Depends(get_db), user=Depends(require_org_roles("CALCULATOR","EXPERT"))):
    org_id = request.state.org.id
    a = db.query(Activity).filter(Activity.org_id==org_id, Activity.id == activity_id).one_or_none()
    if not a:
        return {"ok": False}
    db.delete(a)
    db.commit()
    emit_event(db, org_id, user.username, "ACTIVITY_DELETED", {"activity_id": activity_id})
    return {"ok": True}

@app.post("/api/activities/import")
async def import_activities(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(require_org_roles("CALCULATOR","EXPERT"))):
    org_id = request.state.org.id
    content = await file.read()
    name = (file.filename or "").lower()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content))
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(io.BytesIO(content))
    else:
        raise HTTPException(400, "Only CSV/Excel")
    df.columns = [c.strip().lower() for c in df.columns]
    required = {"name","ef_key"}
    if not required.issubset(set(df.columns)):
        raise HTTPException(400, f"Missing columns: need {sorted(required)}")

    def j(v):
        if v is None or (isinstance(v, float) and pd.isna(v)): return {}
        if isinstance(v, dict): return v
        s = str(v).strip()
        if not s or s.lower() == "nan": return {}
        try: return json.loads(s)
        except: return {}

    count = 0
    for _, row in df.iterrows():
        a = Activity(
            org_id=org_id,
            name=str(row.get("name","")).strip(),
            ef_key=str(row.get("ef_key","")).strip(),
            inputs=j(row.get("inputs")),
            scope=str(row.get("scope","Scope3")).strip(),
            period=(None if "period" not in df.columns else str(row.get("period")).strip()),
        )
        db.add(a)
        count += 1
    db.commit()
    emit_event(db, org_id, user.username, "ACTIVITY_IMPORT", {"count": count, "filename": file.filename})
    return {"ok": True, "imported": count}

# -------- Runs (CFO/CFP) --------
@app.post("/api/calc/run")
def run_calc(request: Request, payload: dict, db: Session = Depends(get_db), user=Depends(require_org_roles("CALCULATOR","EXPERT"))):
    org_id = request.state.org.id
    run_type = payload.get("run_type","CFO")
    activity_ids = payload.get("activity_ids") or []
    if not activity_ids:
        raise HTTPException(400, "activity_ids required")
    result = compute_run(db, activity_ids, run_type, org_id)

    r = CalculationRun(
        org_id=org_id,
        run_type=result["run_type"],
        total_kgco2e=result["total_kgco2e"],
        total_tco2e=result["total_tco2e"],
        details=result["details"],
        ef_snapshot=result.get("ef_snapshot") or {},
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    emit_event(db, org_id, user.username, "RUN_CREATED", {"run_id": r.id, "run_type": r.run_type, "total_tco2e": r.total_tco2e})
    return {"ok": True, "run_id": r.id, **result}

@app.get("/api/calc/runs")
def list_runs(request: Request, db: Session = Depends(get_db), user=Depends(require_org_roles("CALCULATOR","EXPERT","AUDITOR","VERIFIER"))):
    org_id = request.state.org.id
    rows = db.query(CalculationRun).filter(CalculationRun.org_id==org_id).order_by(CalculationRun.id.desc()).limit(50).all()
    return [{
        "id": r.id, "run_type": r.run_type,
        "total_tco2e": r.total_tco2e,
        "review_status": r.review_status,
        "created_at": r.created_at.isoformat()
    } for r in rows]

@app.post("/api/runs/{run_id}/review")
def review_run(request: Request, run_id: int, payload: dict, db: Session = Depends(get_db), user=Depends(require_org_roles("VERIFIER","AUDITOR"))):
    org_id = request.state.org.id
    run = db.query(CalculationRun).filter(CalculationRun.org_id==org_id, CalculationRun.id==run_id).one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    run.review_status = "REVIEWED"
    run.reviewed_by = user.username
    run.reviewed_at = datetime.datetime.utcnow()
    run.details = run.details or {}
    run.details["review_notes"] = payload.get("notes")
    db.add(run)
    db.commit()
    emit_event(db, org_id, user.username, "RUN_REVIEWED", {"run_id": run_id})
    return {"ok": True, "run_id": run_id, "review_status": run.review_status}

@app.post("/api/runs/{run_id}/approve")
def approve_run(request: Request, run_id: int, payload: dict, db: Session = Depends(get_db), user=Depends(require_org_roles("AUDITOR"))):
    org_id = request.state.org.id
    run = db.query(CalculationRun).filter(CalculationRun.org_id==org_id, CalculationRun.id==run_id).one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    run.review_status = "APPROVED"
    run.approved_by = user.username
    run.approved_at = datetime.datetime.utcnow()
    run.details = run.details or {}
    run.details["approval_notes"] = payload.get("notes")
    db.add(run)
    db.commit()
    emit_event(db, org_id, user.username, "RUN_APPROVED", {"run_id": run_id})
    return {"ok": True, "run_id": run_id, "review_status": run.review_status}

# -------- Carbon Credit Project Developer --------
@app.get("/api/credit/projects")
def list_credit_projects(request: Request, db: Session = Depends(get_db), user=Depends(require_org_roles("PROJECT_DEVELOPER","EXPERT"))):
    org_id = request.state.org.id
    rows = db.query(CarbonCreditProject).filter(CarbonCreditProject.org_id==org_id).order_by(CarbonCreditProject.id.desc()).all()
    return [{
        "project_code": p.project_code, "name": p.name, "methodology": p.methodology,
        "baseline_tco2e": p.baseline_tco2e, "project_tco2e": p.project_tco2e,
        "leakage_tco2e": p.leakage_tco2e, "buffer_pct": p.buffer_pct, "vintage": p.vintage
    } for p in rows]

@app.post("/api/credit/projects")
def upsert_credit_project(request: Request, payload: dict, db: Session = Depends(get_db), user=Depends(require_org_roles("PROJECT_DEVELOPER","EXPERT"))):
    org_id = request.state.org.id
    code = payload.get("project_code")
    if not code:
        raise HTTPException(400, "project_code required")
    p = db.query(CarbonCreditProject).filter(CarbonCreditProject.org_id==org_id, CarbonCreditProject.project_code == code).one_or_none()
    if p:
        for k, v in payload.items():
            setattr(p, k, v)
    else:
        payload["org_id"] = org_id
        p = CarbonCreditProject(**payload)
        db.add(p)
    db.commit()
    emit_event(db, org_id, user.username, "CREDIT_PROJECT_UPSERT", {"project_code": code})
    return {"ok": True, "project_code": code}

@app.post("/api/credit/calc")
def calc_credit(request: Request, payload: dict, db: Session = Depends(get_db), user=Depends(require_org_roles("PROJECT_DEVELOPER","EXPERT"))):
    org_id = request.state.org.id
    code = payload.get("project_code")
    if not code:
        raise HTTPException(400, "project_code required")
    trace = calc_carbon_credit(db, code)

    r = CalculationRun(
        org_id=org_id,
        run_type="CREDIT",
        total_kgco2e=trace["net_tco2e"] * 1000.0,
        total_tco2e=trace["net_tco2e"],
        details={"credit_trace": trace},
        ef_snapshot={},
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    emit_event(db, org_id, user.username, "CREDIT_RUN_CREATED", {"run_id": r.id, "project_code": code, "net_tco2e": trace["net_tco2e"]})
    return {"ok": True, "run_id": r.id, **trace}

# -------- Audit --------
@app.post("/api/audit/run/{run_id}")
def audit(request: Request, run_id: int, db: Session = Depends(get_db), user=Depends(require_org_roles("AUDITOR","VERIFIER"))):
    org_id = request.state.org.id
    out = audit_run(db, run_id)
    emit_event(db, org_id, user.username, "AUDIT_RUN", {"run_id": run_id, "score": out.get("score")})
    return out

@app.post("/api/audit/enqueue/{run_id}")
def enqueue_audit(request: Request, run_id: int, user=Depends(require_org_roles("AUDITOR","VERIFIER"))):
    redis_url = os.getenv("REDIS_URL","redis://localhost:6379/0")
    q = Queue(connection=redis.from_url(redis_url))
    job = q.enqueue(job_run_audit, run_id)
    return {"ok": True, "job_id": job.id}

# -------- Report export --------
@app.get("/api/reports/run/{run_id}.pdf")
def report_pdf(request: Request, run_id: int, db: Session = Depends(get_db), user=Depends(require_org_roles("AUDITOR","VERIFIER","EXPERT"))):
    org_id = request.state.org.id
    run = db.query(CalculationRun).filter(CalculationRun.org_id==org_id, CalculationRun.id==run_id).one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    data = export_run_pdf(db, run_id)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=run_{run_id}.pdf"})

@app.get("/api/reports/run/{run_id}.xlsx")
def report_xlsx(request: Request, run_id: int, db: Session = Depends(get_db), user=Depends(require_org_roles("AUDITOR","VERIFIER","EXPERT","CALCULATOR"))):
    org_id = request.state.org.id
    run = db.query(CalculationRun).filter(CalculationRun.org_id==org_id, CalculationRun.id==run_id).one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    data = export_run_excel(db, run_id)
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=run_{run_id}.xlsx"})

@app.post("/api/reports/run/{run_id}/sign")
def sign_run(request: Request, run_id: int, db: Session = Depends(get_db), user=Depends(require_org_roles("AUDITOR","VERIFIER","EXPERT"))):
    org_id = request.state.org.id
    run = db.query(CalculationRun).filter(CalculationRun.org_id==org_id, CalculationRun.id==run_id).one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    if run.review_status != "APPROVED":
        raise HTTPException(400, "Run must be APPROVED before signing (review_status=APPROVED)")

    payload = {"run_id": run.id, "run_type": run.run_type, "total_tco2e": run.total_tco2e, "details": run.details}
    h = calc_run_hash(payload)
    priv_pem, pub_pem = load_or_generate_keypair()
    sig_b64 = sign_hash(h, priv_pem)

    rec = RunSignature(org_id=org_id, run_id=run.id, algo="ed25519", run_hash=h, signature_b64=sig_b64,
                       public_key_pem=pub_pem.decode("utf-8"), signed_by=user.username)
    db.add(rec)
    db.commit()
    emit_event(db, org_id, user.username, "RUN_SIGNED", {"run_id": run.id, "hash": h})
    return {"ok": True, "run_id": run.id, "hash": h, "signature_b64": sig_b64}

@app.get("/api/reports/run/{run_id}/verify")
def verify_run_signature(request: Request, run_id: int, db: Session = Depends(get_db), user=Depends(require_org_roles("AUDITOR","VERIFIER","EXPERT","CALCULATOR"))):
    org_id = request.state.org.id
    sig = db.query(RunSignature).filter(RunSignature.org_id==org_id, RunSignature.run_id==run_id).order_by(RunSignature.id.desc()).first()
    if not sig:
        raise HTTPException(404, "No signature record")
    ok = verify_hash(sig.run_hash, sig.signature_b64, sig.public_key_pem.encode("utf-8"))
    return {"ok": ok, "algo": sig.algo, "hash": sig.run_hash, "signed_by": sig.signed_by, "signed_at": sig.signed_at.isoformat()}

# -------- Dashboard --------
@app.get("/api/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), user=Depends(require_org_roles("CALCULATOR","EXPERT","AUDITOR","VERIFIER","PROJECT_DEVELOPER"))):
    org_id = request.state.org.id
    return {
        "counts": {
            "efs": db.query(EmissionFactor).filter(EmissionFactor.org_id==org_id).count(),
            "activities": db.query(Activity).filter(Activity.org_id==org_id).count(),
            "runs": db.query(CalculationRun).filter(CalculationRun.org_id==org_id).count(),
            "credit_projects": db.query(CarbonCreditProject).filter(CarbonCreditProject.org_id==org_id).count(),
        }
    }
