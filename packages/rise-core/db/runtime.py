"""Deployment boundaries shared by the API and execution services."""

import os

LOCAL_ENVIRONMENTS = frozenset({"local", "development", "dev", "test", "ci"})


def deployment_environment() -> str:
    return os.getenv("ENVIRONMENT", "local").strip().lower()


def allows_local_fallbacks() -> bool:
    """Unknown deployment names fail closed, just like staging and production."""
    return deployment_environment() in LOCAL_ENVIRONMENTS
