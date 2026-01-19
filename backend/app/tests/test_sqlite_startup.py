from .utils import reload_app_modules


def test_startup_seeds_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "seed.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    main, db, tenancy_models = reload_app_modules()

    main.startup()

    with db.SessionLocal() as session:
        assert session.query(main.EmissionFactor).count() > 0
        org = session.query(tenancy_models.Org).filter_by(slug="kmutt").one()
        admin = session.query(main.User).filter_by(username="admin").one()
        membership = session.query(tenancy_models.OrgMember).filter_by(
            org_id=org.id, user_id=admin.id
        ).one()
        assert "AUDITOR" in membership.roles
