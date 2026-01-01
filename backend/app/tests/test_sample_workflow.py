import pytest
from starlette.requests import Request

from .utils import reload_app_modules


def build_request(org):
    scope = {"type": "http", "headers": [(b"x-org-slug", org.slug.encode("utf-8"))]}
    request = Request(scope)
    request.state.org = org
    return request


def test_sample_run_workflow(tmp_path, monkeypatch):
    db_path = tmp_path / "workflow.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    main, db, tenancy_models = reload_app_modules()
    main.startup()

    with db.SessionLocal() as session:
        org = session.query(tenancy_models.Org).filter_by(slug="kmutt").one()
        admin = session.query(main.User).filter_by(username="admin").one()
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
        ef_res = main.upsert_ef(request, ef_payload, db=session, user=admin)
        assert ef_res["ok"] is True

        act_payload = {
            "name": "Diesel generator",
            "ef_key": ef_payload["key"],
            "inputs": {"amount": 4},
            "period": "2024-Q1",
        }
        act_res = main.create_activity(request, act_payload, db=session, user=admin)
        assert act_res["ok"] is True
        activity_id = act_res["id"]

        run_payload = {"run_type": "CFP", "activity_ids": [activity_id]}
        run_res = main.run_calc(request, run_payload, db=session, user=admin)

        assert run_res["ok"] is True
        assert run_res["total_kgco2e"] == pytest.approx(10.0)
        assert run_res["total_tco2e"] == pytest.approx(0.01)
        assert run_res["details"]["rows"][0]["activity_id"] == activity_id
        assert run_res["run_type"] == "CFP"

        dashboard = main.dashboard(request, db=session, user=admin)
        assert dashboard["counts"]["activities"] == 1
        assert dashboard["counts"]["runs"] == 1
