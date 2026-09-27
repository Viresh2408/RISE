"""End-to-end test suite — placeholder.

This suite is REFERENCE SCAFFOLDING. A real end-to-end run needs a full-stack harness
(dashboard browser driver + live API + Postgres + Redis + Qdrant) that is not wired up
at this project stage. Rather than leave `tests/e2e/` silently empty, this placeholder
documents the intended flow and is collected-but-skipped so the gap is visible in the
test report. See tests/e2e/README.md.
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="E2E harness (browser + live API/DB/Redis/Qdrant) not provisioned; "
    "reference scaffolding — see tests/e2e/README.md."
)


def test_full_incident_to_verified_remediation_flow():
    """Intended flow: alert ingest -> RCA -> impact -> plan -> human approval
    -> gated execution -> verification -> report. Requires a live full stack."""
    raise AssertionError("Not implemented — see module docstring.")
