from __future__ import annotations
from sqlalchemy.orm import Session
from app.models import EmissionFactor, Activity
from app.services.gwp import resolve_gwp
from app.services.formula_engine import eval_expression
from app.services.ef_versioning import snapshot_ef_payload, canonical_hash

def _per_unit_co2e_from_gas_breakdown(ef: EmissionFactor) -> float:
    gb = ef.gas_breakdown or {}
    gases = gb.get("gases") or {}
    gwp = resolve_gwp(ef.gwp_version)
    per_unit = 0.0
    for gas, val in gases.items():
        g = gas.strip().upper()
        if g in gwp:
            per_unit += float(val) * float(gwp[g])
    return per_unit

def compute_activity_quantity(ef: EmissionFactor, inputs: dict) -> tuple[float, dict]:
    spec = ef.activity_id_fields or {}
    required = spec.get("required") or []
    formula = spec.get("formula")
    quantity_field = spec.get("quantity_field")

    for r in required:
        if r not in inputs:
            raise ValueError(f"Missing required input '{r}' for EF={ef.key}")

    if formula:
        expr = formula.get("expression")
        out = formula.get("output") or quantity_field or "quantity"
        q = eval_expression(expr, inputs)
        return q, {"method":"formula","expression":expr,"output":out,"quantity":q,"unit":formula.get("unit")}

    if quantity_field and quantity_field in inputs:
        q = float(inputs[quantity_field])
        return q, {"method":"quantity_field","field":quantity_field,"quantity":q}

    if required:
        q = float(inputs[required[0]])
        return q, {"method":"first_required","field":required[0],"quantity":q}

    if "amount" in inputs:
        q = float(inputs["amount"])
        return q, {"method":"fallback_amount","field":"amount","quantity":q}

    raise ValueError("No quantity derivation possible")

def compute_activity_kgco2e(db: Session, activity: Activity, org_id: int) -> tuple[float, dict, str]:
    ef = db.query(EmissionFactor).filter(EmissionFactor.org_id==org_id, EmissionFactor.key == activity.ef_key).one_or_none()
    if not ef:
        raise ValueError(f"EF not found: {activity.ef_key}")

    inputs = activity.inputs or {}
    qty, qtrace = compute_activity_quantity(ef, inputs)

    payload = snapshot_ef_payload(ef)
    h = canonical_hash(payload)

    if ef.value is not None:
        kg = qty * float(ef.value)
        return kg, {"method":"direct_value","qty":qty,"ef_value":ef.value,"qtrace":qtrace,"ef_key":ef.key,"meta":ef.meta, "ef_payload_hash": h}, h

    per_unit = _per_unit_co2e_from_gas_breakdown(ef)
    kg = qty * per_unit
    return kg, {"method":"gas_breakdown","qty":qty,"per_unit_co2e":per_unit,"qtrace":qtrace,"ef_key":ef.key,"meta":ef.meta, "ef_payload_hash": h}, h

def compute_run(db: Session, activity_ids: list[int], run_type: str, org_id: int) -> dict:
    total = 0.0
    rows = []
    ef_snapshot = {}
    for aid in activity_ids:
        a = db.query(Activity).filter(Activity.org_id==org_id, Activity.id == aid).one_or_none()
        if not a:
            raise ValueError(f"Activity not found: {aid}")
        kg, trace, ef_hash = compute_activity_kgco2e(db, a, org_id)
        ef_snapshot[a.ef_key] = ef_hash
        total += kg
        rows.append({"activity_id":a.id,"activity_name":a.name,"ef_key":a.ef_key,"inputs":a.inputs,"kgco2e":kg,"trace":trace})
    return {"run_type":run_type,"total_kgco2e":total,"total_tco2e":total/1000.0,"details":{"rows":rows},"ef_snapshot":ef_snapshot}
