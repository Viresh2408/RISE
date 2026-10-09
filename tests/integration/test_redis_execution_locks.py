"""Distributed lock ownership against an explicitly configured test Redis."""

import os
import uuid

import pytest
from redis import Redis

from mcp_client.lock import ResourceLockManager, ResourceLockedException

pytestmark = pytest.mark.integration


def test_real_redis_lock_is_single_owner_and_wrong_token_cannot_release(monkeypatch):
    url = os.getenv("RISE_INTEGRATION_REDIS_URL")
    if not url:
        pytest.skip("Set RISE_INTEGRATION_REDIS_URL to an isolated test Redis")
    client = Redis.from_url(url)
    client.ping()
    monkeypatch.setenv("ENVIRONMENT", "staging")
    resource = f"phase1-integration:{uuid.uuid4()}"
    owner = f"incident:{uuid.uuid4()}"
    token = ResourceLockManager.acquire_lock(resource, redis_client=client, owner_id=owner)
    try:
        with pytest.raises(ResourceLockedException):
            ResourceLockManager.acquire_lock(resource, redis_client=client)
        ResourceLockManager.release_lock(resource, "foreign-token", client)
        assert ResourceLockManager.get_lock_owner(resource, client) == owner
        ResourceLockManager.release_lock(resource, token, client)
        assert ResourceLockManager.get_lock_owner(resource, client) is None
        replacement = ResourceLockManager.acquire_lock(resource, redis_client=client, owner_id=owner)
        assert replacement != token
        ResourceLockManager.release_lock(resource, token, client)
        assert ResourceLockManager.get_lock_owner(resource, client) == owner
        ResourceLockManager.release_lock(resource, replacement, client)
    finally:
        client.delete(f"lock:resource:{resource}")
        client.close()
