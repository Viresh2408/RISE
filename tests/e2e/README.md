# E2E Tests

Playwright/Cypress end-to-end tests for dashboard and API workflows.

> **⚠️ Reference scaffolding — not implemented.** A real end-to-end run needs a full-stack
> harness (browser driver + live API + Postgres + Redis + Qdrant) that is not provisioned
> at this project stage. `test_e2e_placeholder.py` is collected-but-skipped so the gap
> shows up in the pytest report rather than being silently empty. To implement, stand up
> the full stack (e.g. docker-compose) and drive the flow:
> alert ingest → RCA → impact → plan → human approval → gated execution → verification → report.
