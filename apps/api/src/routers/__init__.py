"""Routers package."""
from .auth import router as auth_router
from .incidents import router as incidents_router
from .agent_runs import router as agent_runs_router
from .root_cause_impact import router as root_cause_impact_router
from .actions import router as actions_router
from .verification import router as verification_router
from .knowledge import router as knowledge_router
from .policies import router as policies_router
from .integrations import router as integrations_router
from .reports import router as reports_router
from .webhooks import router as webhooks_router
from .audit import router as audit_router
from .health import router as health_router

ALL_ROUTERS = [
    auth_router,
    incidents_router,
    agent_runs_router,
    root_cause_impact_router,
    actions_router,
    verification_router,
    knowledge_router,
    policies_router,
    integrations_router,
    reports_router,
    webhooks_router,
    audit_router,
    health_router,
]
