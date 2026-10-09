# CI/CD Workflows

GitHub Actions workflows for linting, testing, security scanning, and deployment

`ci.yml` gates changes with isolated Python unit tests, pinned OPA/Rego tests,
dashboard lint/tests/build, and disposable PostgreSQL 16 + Redis 7 services.
The service job applies and rolls back the new migrations, tests RLS with the
restricted `rise_app` role (not a PostgreSQL superuser), and tests audit-chain
concurrency and Redis compare-and-delete ownership.

The unit job uses `scripts/run_unit_tests.py` to clear live credentials and use
ephemeral SQLite. Its results certify offline behavior, not live remediation or
RCA accuracy. The integration job selects only the explicit infrastructure tests;
tests needing deployment or provider credentials are separate release gates.
