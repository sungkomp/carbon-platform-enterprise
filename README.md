# Carbon Platform — Enterprise Edition

Added on top of the base platform:
- Multi-tenant org (`orgs`, `org_members`) with required header: `X-Org-Slug`
- Org-scoped RBAC with roles: EXPERT / CALCULATOR / POLICY_ADVISOR / VERIFIER / AUDITOR / PROJECT_DEVELOPER
- EF SCD2 versioning (`emission_factor_versions`) with SHA256 payload hash
- Run workflow: REVIEWED/APPROVED + signing (Ed25519) + verify endpoint
- Background jobs: Redis + RQ worker (audit enqueue)
- Rate limiting via slowapi
- Prometheus metrics endpoint: `/metrics`

## Quick start
```bash
docker compose up -d --build
```

Frontend: http://localhost:5173  
Backend: http://localhost:8000  

Dev defaults:
- Org header: `X-Org-Slug: kmutt`
- Admin: `admin / admin1234` (seeded)

## Deploy to GitHub
Same steps as before (git init/add/commit/push).

## Production note
For true production: replace `create_all()` with Alembic migrations and manage secrets (JWT key, signing keys, DB creds).
- For a quick ChatGPT-ready demo of the workflow without the web UI, run
  `PYTHONPATH=backend python backend/scripts/chatgpt_demo.py` (see
  `docs/chatgpt-demo.md`).
