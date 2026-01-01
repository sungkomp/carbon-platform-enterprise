"""Run a demo workflow against a temporary SQLite database and print results."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from starlette.requests import Request


def build_request(org):
    scope = {"type": "http", "headers": [(b"x-org-slug", org.slug.encode("utf-8"))]}
    request = Request(scope)
    request.state.org = org
    return request


def run_workflow(db_path: Path | None = None, recreate: bool = True):
    """Seed the database and execute the demo workflow.

    Returns a dictionary containing the database path and responses so callers
    (scripts/tests) can display or assert on the results.
    """
    db_path = Path(db_path or os.environ.get("DEMO_DB_PATH", "./demo_workflow.db"))
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{db_path}")

    if recreate and db_path.exists():
        db_path.unlink()

    from app import db
    from app import main as app_main
    from app.tenancy import models as tenancy_models

    app_main.startup()

    with db.SessionLocal() as session:
        org = session.query(tenancy_models.Org).filter_by(slug="kmutt").one()
        admin = session.query(app_main.User).filter_by(username="admin").one()
        request = build_request(org)

        ef_payload = {
            "key": "demo:stationary_combustion",
            "name": "Demo stationary combustion",
            "unit": "kg",
            "value": 2.5,
            "scope": "Scope1",
            "category": "Combustion",
            "tags": ["demo"],
        }
        ef_res = app_main.upsert_ef(request, ef_payload, db=session, user=admin)

        activity_payload = {
            "name": "Diesel generator",
            "ef_key": ef_payload["key"],
            "inputs": {"amount": 4},
            "period": "2024-Q1",
        }
        act_res = app_main.create_activity(request, activity_payload, db=session, user=admin)
        activity_id = act_res["id"]

        run_payload = {"run_type": "CFP", "activity_ids": [activity_id]}
        run_res = app_main.run_calc(request, run_payload, db=session, user=admin)
        dashboard = app_main.dashboard(request, db=session, user=admin)

    assert run_res["ok"] is True
    assert run_res["total_kgco2e"] == pytest.approx(10.0)
    assert run_res["total_tco2e"] == pytest.approx(0.01)
    assert dashboard["counts"]["activities"] == 1
    assert dashboard["counts"]["runs"] == 1

    return {
        "db_path": db_path,
        "ef_payload": ef_payload,
        "ef_response": ef_res,
        "activity_payload": activity_payload,
        "activity_response": act_res,
        "run_response": run_res,
        "dashboard": dashboard,
    }


def main():
    result = run_workflow()

    print("Database path:", result["db_path"])
    print("Emission factor response:", result["ef_response"])
    print("Activity response:", result["activity_response"])
    print("Run response:", result["run_response"])
    print("Dashboard counts:", result["dashboard"]["counts"])


if __name__ == "__main__":
    main()
