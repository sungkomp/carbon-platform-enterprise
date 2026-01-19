"""Seed the demo workflow database and run the API server."""
from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from scripts.run_sample_workflow import run_workflow


def main():
    db_path = Path(os.environ.get("DEMO_DB_PATH", "./demo_workflow.db"))
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    recreate = os.environ.get("DEMO_RECREATE_DB", "1") != "0"

    result = run_workflow(db_path=db_path, recreate=recreate)

    host = os.environ.get("DEMO_API_HOST", "0.0.0.0")
    port = int(os.environ.get("DEMO_API_PORT", "8000"))

    print("\nDemo API ready:")
    print("  Database:", result["db_path"].resolve())
    print("  Emission factor:", result["ef_response"]["key"])
    print("  Activity:", result["activity_payload"]["name"])
    print("  Run total kgCO2e:", result["run_response"]["total_kgco2e"])
    print("  Dashboard counts:", result["dashboard"]["counts"])
    print("  Login with admin/admin1234 and X-Org-Slug header set to 'kmutt'.")
    print(f"  Serving on http://{host}:{port}")

    uvicorn.run("app.main:app", host=host, port=port, timeout_keep_alive=5)


if __name__ == "__main__":
    main()
