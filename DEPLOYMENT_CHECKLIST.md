# Deployment checklist

## Before first deployment
- [ ] Copy `.env.example` to `.env`.
- [ ] Set unique URL-safe PostgreSQL password, API key, and UI login password.
- [ ] Add Google API key only if enabling the AI assistant.
- [ ] Review `CORS_ORIGINS` and published ports.
- [ ] Confirm no real employee information is in the sample seed.

## Start and verify
- [ ] `docker compose config` completes without errors.
- [ ] `docker compose up --build -d` completes.
- [ ] PostgreSQL health check passes.
- [ ] API `/health` reports database connected.
- [ ] Streamlit UI loads and requires the shared password.
- [ ] API `/api/dashboard` rejects requests without `X-API-Key`.
- [ ] API `/api/dashboard` succeeds with the configured key.
- [ ] Sample seed reports 32 employees, 20 brands, 4 pods, and 41 processes.
- [ ] Generate a month and verify all coverage rows.
- [ ] Submit a leave request and confirm it stays pending.
- [ ] Approve the request and verify affected months revalidate.
- [ ] Confirm coverage gap and backup recommendations appear after an absence.
- [ ] Confirm the agent uses actual tools with a valid Google API key.
- [ ] Confirm the UI's real-time agent insight appears after a leave/shortage event.
- [ ] Verify database volume survives container restart.
- [ ] Configure TLS, database backups, monitoring, and access controls before real use.

## Current verification from the development environment
- [x] Python compilation.
- [x] Six deterministic scheduler tests.
- [x] FastAPI TestClient smoke test: health, dashboard, seeded data, roster generation, impact simulation, pending leave, approval, revalidation.
- [x] API key enforcement for read and write routes.
- [x] Seed data profile: 32 employees, 20 brands, 4 pods, 16 single-resource brands, 4 multi-resource brands, two cross-brand employees.
- [x] November 2026 sample roster: 1,140 allocations, 100% required coverage before leave.
- [x] Approved absence simulation: three service coverage gaps surfaced with same-pod backup recommendations in the smoke test.
- [x] Docker Compose YAML parse.
- [ ] Docker image build / Compose startup (Docker CLI unavailable in this environment).
- [ ] Streamlit browser runtime test (Streamlit package unavailable in this environment).
- [ ] LangGraph/Gemini runtime test (agent packages unavailable offline; requires dependency installation and a real API key).
- [ ] Public deployment and externally accessible URL.
