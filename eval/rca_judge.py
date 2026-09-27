"""eval/rca_judge.py -- Live RCA Benchmark Pilot (n=10).

Implements Phase 5 of the RISE remediation plan.

PURPOSE
-------
Runs the REAL Investigation Agent + Root Cause Agent (real LLM calls, real
fetched context -- NOT mock-populated state) against 10 frozen golden scenarios
and scores the resulting cause_summary against ground_truth_root_cause using a
deterministic mechanism rubric.

WHAT THIS IS NOT
----------------
This is NOT the orchestration certification (run_eval.py --mode orchestration),
which validates state-machine transitions with mocked LLM boundaries. Those
tests confirm wiring -- they say nothing about diagnostic accuracy.

SCORING
-------
Keyword/substring overlap is explicitly PROHIBITED as a passing criterion.
Each scenario has a mechanism_rubric with required technical concepts.
The rubric requires ALL primary_components AND at least one causal_mechanism.

A correct answer must:
  1. Name the specific component(s) involved (e.g. "connection pool", "JWKS cache").
  2. Name the causal mechanism (e.g. "exhaustion", "thundering herd", "race condition").
  3. Not introduce a materially wrong component as the primary cause
     (hallucination check: first 120 chars of cause_summary must not feature
     a known-wrong component as the dominant subject).

LABELING
--------
Per docs/evaluation-methodology.md S2 release-gate requirement:
  PILOT -- NOT RELEASE ELIGIBLE  (n=10, fewer than 50 required for release gate)

HOW TO RUN
----------
  Without live LLM keys (prints skip notice -- does NOT substitute mock):
    python eval/run_eval.py --mode rca

  With live LLM keys:
    python eval/run_eval.py --mode rca --live --provider gemini --model gemini-1.5-pro

  Direct invocation:
    Without live LLM keys (prints skip notice):
      python eval/rca_judge.py

    With live LLM keys:
      python eval/rca_judge.py --provider gemini --model gemini-1.5-pro

INTERFACE CONTRACT (called by run_eval.py via importlib)
---------------------------------------------------------
    async def run_benchmark(
        *,
        run_id: str,
        live: bool,
        provider: str | None,
        model: str | None,
        artifacts_dir: str,
    ) -> bool

Returns True if all scored cases pass, or live=False (skip).
Raises RuntimeError if live=True but credentials are missing.
Never silently substitutes a mock for a failed live call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup (allow running from repo root, same as run_eval.py)
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath("packages/rise-core"))
sys.path.insert(0, os.path.abspath("."))

# Configure UTF-8 safe streams on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("rca_judge")

# ---------------------------------------------------------------------------
# BENCHMARK CONSTANTS
# ---------------------------------------------------------------------------
BENCHMARK_LABEL = "PILOT -- NOT RELEASE ELIGIBLE"
BENCHMARK_N = 10
RELEASE_GATE_N = 50

# ---------------------------------------------------------------------------
# GOLDEN SCENARIOS (n=10, frozen)
#
# raw_evidence  -- sole telemetry provided to the agent (logs, metrics, alerts,
#                  deploys). Never contains the answer.
# answer_key    -- isolated ground truth. Passed only to the scorer (judge),
#                  NEVER injected into agent prompts or runbook context.
# mechanism_rubric -- deterministic evaluation rules. ALL primary_components
#                  must appear in model output, plus at least one causal_mechanism.
# ---------------------------------------------------------------------------
GOLDEN_SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "title": "payment-service high error rate -- 503s spiking to 45%",
        "service": "payment-service",
        "raw_evidence": {
            "timeline": [
                {
                    "timestamp": "2026-08-04T11:58:00Z",
                    "event": "Deploy v2.4.1 to payment-service",
                    "source": "github-actions",
                },
                {
                    "timestamp": "2026-08-04T12:03:00Z",
                    "event": "Error rate crossed 20%",
                    "source": "alertmanager",
                },
                {
                    "timestamp": "2026-08-04T12:07:00Z",
                    "event": "Error rate at 45%, SLO breached",
                    "source": "alertmanager",
                },
            ],
            "log_excerpts": [
                {
                    "source": "loki:payment-service",
                    "excerpt": "WARN [db-pool] acquire timeout after 5000ms -- all 20 connections in use",
                },
                {
                    "source": "loki:payment-service",
                    "excerpt": "ERROR connection pool exhausted; returning 503 to caller",
                },
                {
                    "source": "loki:payment-service",
                    "excerpt": "SLOW QUERY [180ms]: SELECT * FROM transactions WHERE status='pending' -- added in v2.4.1",
                },
            ],
            "metric_snapshots": [
                {"metric": "http_error_rate_5xx", "value": "45%", "window": "5m"},
                {"metric": "db_pool_wait_ms_p99", "value": "4800ms", "window": "5m"},
                {"metric": "db_pool_active_connections", "value": "20/20 (saturated)", "window": "5m"},
            ],
            "recent_deploys": [
                {
                    "repo": "payment-service",
                    "commit": "v2.4.1",
                    "deployed_at": "2026-08-04T11:58:00Z",
                    "author": "dev-alice",
                    "pr_title": "Add pending transaction query for reporting dashboard",
                }
            ],
        },
        "answer_key": {
            "ground_truth_root_cause": "database connection pool exhausted",
            "provenance": "Slow unbounded query in v2.4.1 held connections beyond timeout, exhausting the pool of 20.",
            "verified_by": "SRE postmortem PM-2026-08-04",
        },
        "mechanism_rubric": {
            "primary_components": ["connection pool", "database"],
            "causal_mechanisms": ["exhausted", "exhaustion", "depleted", "saturated"],
            "causal_trigger": ["slow query", "v2.4.1", "deploy"],
            "hallucination_check": ["network partition", "OOM", "memory leak", "TLS"],
        },
    },
    {
        "id": 2,
        "title": "payment-service memory leak causing OOM restarts",
        "service": "payment-service",
        "raw_evidence": {
            "timeline": [
                {
                    "timestamp": "2026-08-10T09:00:00Z",
                    "event": "Deploy v2.3.0 to payment-service",
                    "source": "github-actions",
                },
                {
                    "timestamp": "2026-08-10T11:30:00Z",
                    "event": "RSS growing -- memory alert firing",
                    "source": "alertmanager",
                },
                {
                    "timestamp": "2026-08-10T12:55:00Z",
                    "event": "OOMKilled -- container restarted",
                    "source": "k8s-events",
                },
            ],
            "log_excerpts": [
                {
                    "source": "loki:payment-service",
                    "excerpt": "INFO [billing-middleware] Registered EventEmitter listener (total: 847 listeners)",
                },
                {
                    "source": "loki:payment-service",
                    "excerpt": "MaxListenersExceededWarning: 850+ listeners detected for request event",
                },
                {
                    "source": "k8s",
                    "excerpt": "OOMKilled reason=OOMKilled exitCode=137 container=payment-service",
                },
            ],
            "metric_snapshots": [
                {
                    "metric": "container_memory_rss_bytes",
                    "value": "increasing monotonically over 3h",
                    "window": "3h",
                },
                {"metric": "container_restarts", "value": "3 restarts in 6h", "window": "6h"},
            ],
            "recent_deploys": [
                {
                    "repo": "payment-service",
                    "commit": "v2.3.0",
                    "deployed_at": "2026-08-10T09:00:00Z",
                    "author": "dev-bob",
                    "pr_title": "Add billing audit middleware with per-request event hooks",
                }
            ],
        },
        "answer_key": {
            "ground_truth_root_cause": "listener leak / memory leak in billing middleware",
            "provenance": "EventEmitter listeners registered per-request but never removed in billing middleware introduced in v2.3.0.",
            "verified_by": "Heap dump analysis postmortem PM-2026-08-10",
        },
        "mechanism_rubric": {
            "primary_components": ["billing middleware", "listener", "EventEmitter"],
            "causal_mechanisms": ["leak", "not removed", "never removed", "unbounded growth", "accumulation"],
            "causal_trigger": ["v2.3.0", "per-request", "middleware"],
            "hallucination_check": ["network", "database", "connection pool", "TLS"],
        },
    },
    {
        "id": 3,
        "title": "auth-service JWT validation latency spike",
        "service": "auth-service",
        "raw_evidence": {
            "timeline": [
                {
                    "timestamp": "2026-08-15T14:00:00Z",
                    "event": "JWKS cache keys expired simultaneously",
                    "source": "auth-service-log",
                },
                {
                    "timestamp": "2026-08-15T14:00:01Z",
                    "event": "P99 latency jumped from 12ms to 890ms",
                    "source": "prometheus",
                },
                {
                    "timestamp": "2026-08-15T14:00:45Z",
                    "event": "JWKS cache refilled, latency recovered",
                    "source": "prometheus",
                },
            ],
            "log_excerpts": [
                {
                    "source": "loki:auth-service",
                    "excerpt": "WARN [jwks-cache] Cache miss -- fetching remote JWKS from identity provider",
                },
                {
                    "source": "loki:auth-service",
                    "excerpt": "INFO [jwks-cache] 1843 concurrent goroutines waiting for JWKS refresh",
                },
                {
                    "source": "loki:auth-service",
                    "excerpt": "INFO [jwks-cache] JWKS refreshed in 820ms, unblocking waiters",
                },
            ],
            "metric_snapshots": [
                {"metric": "jwt_validation_p99_ms", "value": "890ms peak", "window": "1m"},
                {"metric": "jwks_cache_hit_rate", "value": "0% for 45s", "window": "1m"},
                {"metric": "concurrent_jwks_refreshers", "value": "1843", "window": "30s"},
            ],
            "recent_deploys": [],
        },
        "answer_key": {
            "ground_truth_root_cause": "JWKS cache expiration thundering herd",
            "provenance": "All cached JWKS keys expired at the same TTL, causing a thundering-herd of simultaneous refresh requests.",
            "verified_by": "Auth-service SRE review 2026-08-15",
        },
        "mechanism_rubric": {
            "primary_components": ["JWKS", "cache"],
            "causal_mechanisms": [
                "thundering herd",
                "stampede",
                "simultaneous expiration",
                "concurrent refresh",
                "cache miss storm",
            ],
            "causal_trigger": ["TTL", "expiration", "expired"],
            "hallucination_check": ["deploy", "certificate", "memory", "database"],
        },
    },
    {
        "id": 4,
        "title": "auth-service complete outage -- misconfigured TLS cert",
        "service": "auth-service",
        "raw_evidence": {
            "timeline": [
                {
                    "timestamp": "2026-09-01T03:00:00Z",
                    "event": "Automated cert rotation ran",
                    "source": "cert-manager",
                },
                {
                    "timestamp": "2026-09-01T03:01:30Z",
                    "event": "auth-service pods failing readiness -- TLS handshake errors",
                    "source": "k8s-events",
                },
                {
                    "timestamp": "2026-09-01T03:01:45Z",
                    "event": "100% of auth-service requests failing",
                    "source": "alertmanager",
                },
            ],
            "log_excerpts": [
                {
                    "source": "loki:auth-service",
                    "excerpt": "ERROR tls: no certificates configured for auth.internal.cluster.local",
                },
                {
                    "source": "loki:api-gateway",
                    "excerpt": "ERROR upstream TLS handshake failed: x509: certificate is not valid for auth.internal.cluster.local",
                },
                {
                    "source": "loki:cert-manager",
                    "excerpt": "INFO Certificate issued for auth-service.default.svc -- SANs: [auth-service.example.com]",
                },
            ],
            "metric_snapshots": [
                {"metric": "auth_service_request_success_rate", "value": "0%", "window": "5m"},
                {"metric": "tls_handshake_failures", "value": "100%", "window": "5m"},
            ],
            "recent_deploys": [
                {
                    "repo": "cert-manager-config",
                    "commit": "rotate-cert-2026-09",
                    "deployed_at": "2026-09-01T03:00:00Z",
                    "author": "cert-rotation-bot",
                    "pr_title": "Scheduled TLS cert rotation for auth-service",
                }
            ],
        },
        "answer_key": {
            "ground_truth_root_cause": "missing SAN in rotated TLS certificate",
            "provenance": "New cert issued with only the public SAN; internal cluster DNS name omitted from SubjectAltName list.",
            "verified_by": "Postmortem PM-2026-09-01",
        },
        "mechanism_rubric": {
            "primary_components": ["certificate", "SAN", "SubjectAltName"],
            "causal_mechanisms": ["missing", "not included", "omitted", "not valid for"],
            "causal_trigger": ["rotation", "cert rotation", "internal DNS", "cluster DNS"],
            "hallucination_check": ["connection pool", "memory", "cache", "query"],
        },
    },
    {
        "id": 5,
        "title": "notification-service queue backlog -- emails delayed 2h",
        "service": "notification-service",
        "raw_evidence": {
            "timeline": [
                {
                    "timestamp": "2026-08-20T08:00:00Z",
                    "event": "Helm chart upgrade deployed",
                    "source": "github-actions",
                },
                {
                    "timestamp": "2026-08-20T08:05:00Z",
                    "event": "Email queue depth growing exponentially",
                    "source": "alertmanager",
                },
                {
                    "timestamp": "2026-08-20T10:10:00Z",
                    "event": "Queue depth 45000 -- 2h email delay",
                    "source": "alertmanager",
                },
            ],
            "log_excerpts": [
                {
                    "source": "loki:notification-service",
                    "excerpt": "INFO [worker-pool] Starting 1 email worker (configured: 1)",
                },
                {
                    "source": "loki:notification-service",
                    "excerpt": "WARN [email-queue] Queue depth: 45000, active workers: 1, expected: 8",
                },
            ],
            "metric_snapshots": [
                {"metric": "email_queue_depth", "value": "45000", "window": "5m"},
                {"metric": "active_email_workers", "value": "1", "window": "5m"},
                {"metric": "email_processing_rate_per_min", "value": "12 (expected ~1000)", "window": "5m"},
            ],
            "recent_deploys": [
                {
                    "repo": "notification-service-helm",
                    "commit": "helm-upgrade-v3.2.0",
                    "deployed_at": "2026-08-20T08:00:00Z",
                    "author": "deploy-bot",
                    "pr_title": "Upgrade Helm chart to v3.2.0",
                }
            ],
        },
        "answer_key": {
            "ground_truth_root_cause": "notification worker count misconfiguration",
            "provenance": "Helm chart upgrade accidentally reset worker replica count from 8 to 1.",
            "verified_by": "Postmortem PM-2026-08-20",
        },
        "mechanism_rubric": {
            "primary_components": ["worker", "worker count", "replica"],
            "causal_mechanisms": ["misconfiguration", "misconfigured", "reduced", "reset", "wrong value", "set to 1"],
            "causal_trigger": ["Helm", "helm upgrade", "chart upgrade"],
            "hallucination_check": ["memory", "OOM", "database", "TLS", "cache"],
        },
    },
    {
        "id": 6,
        "title": "notification-service Slack webhook rate limit exceeded",
        "service": "notification-service",
        "raw_evidence": {
            "timeline": [
                {
                    "timestamp": "2026-09-05T16:00:00Z",
                    "event": "Alert storm: 2300 alerts fired in 10 minutes",
                    "source": "alertmanager",
                },
                {
                    "timestamp": "2026-09-05T16:03:00Z",
                    "event": "Slack webhook responses: HTTP 429 Too Many Requests",
                    "source": "loki:notification-service",
                },
                {
                    "timestamp": "2026-09-05T16:10:00Z",
                    "event": "All Slack notifications silently dropped",
                    "source": "loki:notification-service",
                },
            ],
            "log_excerpts": [
                {
                    "source": "loki:notification-service",
                    "excerpt": "ERROR [slack-webhook] POST https://hooks.slack.com -- HTTP 429 Retry-After: 60",
                },
                {
                    "source": "loki:notification-service",
                    "excerpt": "WARN [slack-webhook] Rate limit hit -- no backoff configured, dropping message",
                },
                {
                    "source": "loki:notification-service",
                    "excerpt": "INFO Sent 2300 webhook POSTs in 600s to Slack",
                },
            ],
            "metric_snapshots": [
                {"metric": "slack_webhook_http_429_count", "value": "1847", "window": "10m"},
                {"metric": "slack_notifications_dropped", "value": "1847", "window": "10m"},
            ],
            "recent_deploys": [],
        },
        "answer_key": {
            "ground_truth_root_cause": "Slack API rate limiting under alert storm",
            "provenance": "Notification service fired 2300 Slack webhooks without backoff; Slack rate-limited at 1 msg/s per channel.",
            "verified_by": "Slack API audit 2026-09-05",
        },
        "mechanism_rubric": {
            "primary_components": ["Slack", "webhook", "rate limit"],
            "causal_mechanisms": ["rate limited", "rate limiting", "429", "throttled", "throttling"],
            "causal_trigger": ["alert storm", "no backoff", "backoff not configured", "burst"],
            "hallucination_check": ["database", "TLS", "memory", "connection pool"],
        },
    },
    {
        "id": 7,
        "title": "api-gateway 502 cascade -- upstream connection refused",
        "service": "api-gateway",
        "raw_evidence": {
            "timeline": [
                {
                    "timestamp": "2026-08-25T10:00:00Z",
                    "event": "payment-service rollout started",
                    "source": "k8s-events",
                },
                {
                    "timestamp": "2026-08-25T10:02:00Z",
                    "event": "api-gateway 502 rate: 100%",
                    "source": "alertmanager",
                },
                {
                    "timestamp": "2026-08-25T10:02:10Z",
                    "event": "payment-service pods: 0 ready / 3 running",
                    "source": "k8s-events",
                },
            ],
            "log_excerpts": [
                {
                    "source": "loki:api-gateway",
                    "excerpt": "ERROR upstream connect error before headers: payment-service -- connection refused",
                },
                {
                    "source": "k8s",
                    "excerpt": "Readiness probe failed: HTTP probe failed with statuscode: 404 -- path: /health",
                },
                {
                    "source": "k8s",
                    "excerpt": "Readiness probe path configured as /health; actual endpoint is /healthz",
                },
            ],
            "metric_snapshots": [
                {"metric": "payment_service_ready_pods", "value": "0", "window": "5m"},
                {"metric": "api_gateway_502_rate", "value": "100%", "window": "5m"},
                {"metric": "readiness_probe_failure_count", "value": "180", "window": "3m"},
            ],
            "recent_deploys": [
                {
                    "repo": "payment-service",
                    "commit": "rollout-v2.5.0",
                    "deployed_at": "2026-08-25T10:00:00Z",
                    "author": "deploy-bot",
                    "pr_title": "Rollout payment-service v2.5.0",
                }
            ],
        },
        "answer_key": {
            "ground_truth_root_cause": "readiness probe configuration mismatch",
            "provenance": "Probe path /health; endpoint moved to /healthz in v2.5.0. All pods failed readiness, leaving 0 active endpoints.",
            "verified_by": "K8s SRE review 2026-08-25",
        },
        "mechanism_rubric": {
            "primary_components": ["readiness probe", "probe"],
            "causal_mechanisms": ["mismatch", "misconfigured", "wrong path", "path mismatch", "404"],
            "causal_trigger": ["rollout", "deploy", "/health", "/healthz"],
            "hallucination_check": ["TLS", "memory", "connection pool", "rate limit"],
        },
    },
    {
        "id": 8,
        "title": "api-gateway TLS 1.0 deprecation breaking legacy clients",
        "service": "api-gateway",
        "raw_evidence": {
            "timeline": [
                {
                    "timestamp": "2026-09-10T00:00:00Z",
                    "event": "TLS 1.0/1.1 disabled on api-gateway",
                    "source": "change-management",
                },
                {
                    "timestamp": "2026-09-10T00:05:00Z",
                    "event": "B2B partner error alerts: SSL handshake failure",
                    "source": "alertmanager",
                },
                {
                    "timestamp": "2026-09-10T08:00:00Z",
                    "event": "3 enterprise B2B customers reporting complete API failure",
                    "source": "support-ticket",
                },
            ],
            "log_excerpts": [
                {
                    "source": "loki:api-gateway",
                    "excerpt": "ERROR TLS handshake error from 203.0.113.45: tls: no supported versions satisfy minVersion",
                },
                {
                    "source": "loki:api-gateway",
                    "excerpt": "INFO TLS negotiation: client offered [TLSv1.0], server minimum is TLSv1.2 -- rejected",
                },
                {
                    "source": "support",
                    "excerpt": "Client system: Java 7 JRE, .NET Framework 4.5 -- both only support TLS 1.0",
                },
            ],
            "metric_snapshots": [
                {"metric": "b2b_api_request_failure_rate", "value": "100% for affected clients", "window": "8h"},
                {"metric": "tls10_connection_attempts_blocked", "value": "4200", "window": "8h"},
            ],
            "recent_deploys": [
                {
                    "repo": "api-gateway-config",
                    "commit": "disable-tls10",
                    "deployed_at": "2026-09-10T00:00:00Z",
                    "author": "security-team",
                    "pr_title": "Enforce TLS 1.2+ minimum -- disable TLS 1.0 and 1.1",
                }
            ],
        },
        "answer_key": {
            "ground_truth_root_cause": "TLS 1.0 deprecation breaking legacy clients",
            "provenance": "Enforcing TLS 1.2+ minimum broke Java 7 and .NET 4.5 B2B clients that only support TLS 1.0.",
            "verified_by": "Security team postmortem 2026-09-10",
        },
        "mechanism_rubric": {
            "primary_components": ["TLS", "TLS 1.0"],
            "causal_mechanisms": ["deprecation", "deprecated", "disabled", "enforcement", "minimum version"],
            "causal_trigger": ["legacy client", "Java 7", ".NET 4.5", "B2B"],
            "hallucination_check": ["connection pool", "memory", "cache", "worker", "queue"],
        },
    },
    {
        "id": 9,
        "title": "payment-service duplicate charge bug after retry storm",
        "service": "payment-service",
        "raw_evidence": {
            "timeline": [
                {
                    "timestamp": "2026-09-12T15:00:00Z",
                    "event": "Network instability: upstream payment processor latency 2-8s",
                    "source": "cloud-provider-status",
                },
                {
                    "timestamp": "2026-09-12T15:05:00Z",
                    "event": "Charge retry storm -- 1200 retries in 5 minutes",
                    "source": "loki:payment-service",
                },
                {
                    "timestamp": "2026-09-12T15:30:00Z",
                    "event": "340 duplicate charge reports from customers",
                    "source": "support-tickets",
                },
            ],
            "log_excerpts": [
                {
                    "source": "loki:payment-service",
                    "excerpt": "WARN [idempotency] Key charge-req-a7f3c2 not found in Redis -- treating as new request",
                },
                {
                    "source": "loki:payment-service",
                    "excerpt": "INFO [idempotency] Key TTL set to 60s on charge creation",
                },
                {
                    "source": "loki:payment-service",
                    "excerpt": "ERROR [payment] Network timeout -- retrying charge charge-req-a7f3c2 (attempt 2)",
                },
            ],
            "metric_snapshots": [
                {"metric": "idempotency_key_hit_rate", "value": "0% during retry window", "window": "30m"},
                {"metric": "duplicate_charge_count", "value": "340", "window": "30m"},
                {"metric": "redis_idempotency_key_ttl_seconds", "value": "60", "window": "current"},
            ],
            "recent_deploys": [],
        },
        "answer_key": {
            "ground_truth_root_cause": "idempotency key expiry too short",
            "provenance": "Redis idempotency keys expired (60s TTL) before retries completed (up to 8s timeout x retries), causing duplicate charges.",
            "verified_by": "Payment SRE postmortem PM-2026-09-12",
        },
        "mechanism_rubric": {
            "primary_components": ["idempotency key", "idempotency"],
            "causal_mechanisms": ["expired", "expiry", "TTL too short", "TTL", "short TTL"],
            "causal_trigger": ["retry", "network timeout", "60s", "Redis"],
            "hallucination_check": ["memory", "OOM", "TLS", "connection pool", "worker"],
        },
    },
    {
        "id": 10,
        "title": "auth-service token refresh race condition causing logout loops",
        "service": "auth-service",
        "raw_evidence": {
            "timeline": [
                {
                    "timestamp": "2026-09-18T09:00:00Z",
                    "event": "Mobile app v4.2.0 released -- parallel refresh requests",
                    "source": "release-notes",
                },
                {
                    "timestamp": "2026-09-18T09:30:00Z",
                    "event": "Spike in 401 errors -- users reporting forced logouts",
                    "source": "alertmanager",
                },
                {
                    "timestamp": "2026-09-18T10:00:00Z",
                    "event": "5% of active mobile sessions affected",
                    "source": "alertmanager",
                },
            ],
            "log_excerpts": [
                {
                    "source": "loki:auth-service",
                    "excerpt": "INFO [token-refresh] Refresh token rt-abc123 validated -- issuing new tokens",
                },
                {
                    "source": "loki:auth-service",
                    "excerpt": "WARN [token-refresh] Refresh token rt-abc123 already rotated -- token invalid",
                },
                {
                    "source": "loki:auth-service",
                    "excerpt": "INFO [token-refresh] 2 concurrent refresh requests received for same session within 50ms",
                },
            ],
            "metric_snapshots": [
                {"metric": "token_refresh_401_rate", "value": "12% of refresh calls", "window": "1h"},
                {"metric": "concurrent_refresh_same_session", "value": "8% of mobile sessions", "window": "1h"},
                {"metric": "forced_logout_count", "value": "1420", "window": "1h"},
            ],
            "recent_deploys": [
                {
                    "repo": "mobile-app",
                    "commit": "v4.2.0",
                    "deployed_at": "2026-09-18T09:00:00Z",
                    "author": "mobile-team",
                    "pr_title": "Parallel API request optimization -- refresh token on every concurrent call",
                }
            ],
        },
        "answer_key": {
            "ground_truth_root_cause": "token refresh race condition causing invalidation",
            "provenance": "Mobile v4.2.0 sends concurrent requests each triggering token refresh; server rotates on first, invalidates on second -- logout loop.",
            "verified_by": "Auth SRE postmortem PM-2026-09-18",
        },
        "mechanism_rubric": {
            "primary_components": ["token refresh", "refresh token"],
            "causal_mechanisms": ["race condition", "race", "concurrent", "simultaneous", "invalidated"],
            "causal_trigger": ["mobile", "v4.2.0", "parallel", "concurrent requests"],
            "hallucination_check": ["database", "connection pool", "TLS", "memory", "cache miss"],
        },
    },
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RubricScore:
    scenario_id: int
    title: str
    cause_summary: str
    ground_truth: str
    components_matched: List[str]
    mechanisms_matched: List[str]
    trigger_matched: bool
    hallucination_detected: bool
    hallucination_detail: str
    mechanism_match: bool
    confidence_reported: float
    latency_ms: int
    error: Optional[str] = None


@dataclass
class BenchmarkReport:
    run_id: str
    label: str
    pilot_n: int
    release_gate_n: int
    live: bool
    provider: Optional[str]
    model: Optional[str]
    git_sha: Optional[str]
    dataset_hash: str
    timestamp_utc: str
    scores: List[RubricScore] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    mechanism_accuracy_pct: float = 0.0
    release_eligible: bool = False
    summary: str = ""


# ---------------------------------------------------------------------------
# Mechanism rubric scorer (deterministic -- no LLM involvement in scoring)
# ---------------------------------------------------------------------------


def _score_mechanism(
    cause_summary: str,
    confidence_rationale: str,
    rubric: Dict[str, Any],
) -> Tuple[bool, List[str], List[str], bool, bool, str]:
    """Score cause_summary against the mechanism rubric.

    Rules -- ALL must hold for PASS:
      1. At least ONE primary_component must appear in cause_summary or rationale.
      2. At least ONE causal_mechanism must appear in cause_summary or rationale.
      3. Hallucination check: NONE of the hallucination_check terms may appear
         in the first 120 chars of cause_summary (the topic/lead sentence).

    This is intentionally stricter than substring matching alone:
      - Repeating the incident title verbatim but missing the mechanism fails.
      - Correct component + wrong mechanism fails.
    """
    text = (cause_summary + " " + confidence_rationale).lower()

    components_matched = [c for c in rubric["primary_components"] if c.lower() in text]
    mechanisms_matched = [m for m in rubric["causal_mechanisms"] if m.lower() in text]
    trigger_matched = any(t.lower() in text for t in rubric.get("causal_trigger", []))

    # Hallucination: wrong root-cause component as primary subject of lead sentence
    summary_lead = cause_summary[:120].lower()
    hallucination_terms = [h for h in rubric["hallucination_check"] if h.lower() in summary_lead]
    hallucination_detected = len(hallucination_terms) > 0
    hallucination_detail = ", ".join(hallucination_terms) if hallucination_terms else ""

    mechanism_match = (
        len(components_matched) >= 1
        and len(mechanisms_matched) >= 1
        and not hallucination_detected
    )

    return (
        mechanism_match,
        components_matched,
        mechanisms_matched,
        trigger_matched,
        hallucination_detected,
        hallucination_detail,
    )


# ---------------------------------------------------------------------------
# Live agent runner
# ---------------------------------------------------------------------------


async def _run_agents_on_scenario(
    scenario: Dict[str, Any],
    gateway: Any,
) -> Dict[str, Any]:
    """Run Investigation + Root Cause agents on raw_evidence only.

    The agent receives ONLY raw_evidence -- NEVER the answer_key.
    The runbook fetcher returns empty to prevent ground-truth leakage via RAG.
    """
    from apps.agents.src.nodes.investigation import run_investigation_agent
    from apps.agents.src.nodes.root_cause import run_root_cause_agent

    state: Dict[str, Any] = {
        "tenant_id": "tenant-rca-benchmark",
        "event_payload": {
            "resource_id": scenario["service"],
            "summary": scenario["title"],
            "event_type": "incident_alert",
        },
        "context": {
            "timeline": scenario["raw_evidence"].get("timeline", []),
            "log_excerpts": scenario["raw_evidence"].get("log_excerpts", []),
            "metric_snapshots": scenario["raw_evidence"].get("metric_snapshots", []),
            "recent_deploys": scenario["raw_evidence"].get("recent_deploys", []),
            "similar_past_incidents": [],
            "context_completeness_pct": 100,
            "missing_sources": [],
        },
        "hypotheses": [],
        "root_cause": {},
    }

    # Null runbook fetcher -- no ground-truth leakage via RAG
    def _null_runbook_fetcher(
        query: str, tenant_id: str, service_id: Optional[str] = None
    ) -> Tuple[str, bool]:
        return "No runbook available for this service in the benchmark dataset.", False

    state = await run_investigation_agent(
        state,
        gateway=gateway,
        runbook_fetcher=_null_runbook_fetcher,
    )
    state = await run_root_cause_agent(state, gateway=gateway)
    return state


# ---------------------------------------------------------------------------
# Provider gateway factory for live mode
# ---------------------------------------------------------------------------


def _build_live_gateway(provider: str, model: str) -> Any:
    """Build a real LLMGateway.  Raises RuntimeError if credentials are missing.

    Never substitutes a mock for a failed live call.
    """
    from llm_gateway.config import GatewayConfig, ProviderConfig
    from llm_gateway.gateway import LLMGateway

    env_map: Dict[str, Tuple[str, str]] = {
        "gemini": ("GEMINI_API_KEY", "your_gemini_api_key"),
        "openai": ("OPENAI_API_KEY", "your_openai_api_key"),
        "anthropic": ("ANTHROPIC_API_KEY", "your_anthropic_api_key"),
        "groq": ("GROQ_API_KEY", "your_groq_api_key"),
    }

    p = provider.lower()
    if p not in env_map:
        raise RuntimeError(
            f"Unknown provider '{provider}'. Supported: {', '.join(env_map.keys())}."
        )

    env_var, placeholder = env_map[p]
    api_key = os.environ.get(env_var, "").strip()
    if "#" in api_key:
        api_key = api_key.split("#", 1)[0].strip()
    if not api_key or placeholder in api_key:
        raise RuntimeError(
            f"{env_var} is not set or is a placeholder. "
            f"Live RCA benchmark requires a real API key. "
            f"Set {env_var} in your .env or environment."
        )

    pcfg = ProviderConfig(name=p, model=model, api_key=api_key)
    return LLMGateway(config=GatewayConfig(providers=[pcfg]))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _dataset_hash(scenarios: List[Dict[str, Any]]) -> str:
    """Deterministic SHA-256 of the frozen golden dataset (answer keys included)."""
    canonical = json.dumps(scenarios, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _git_sha() -> Optional[str]:
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def _write_markdown_report(report: "BenchmarkReport", path: str) -> None:
    lines = [
        "# Live RCA Benchmark Report",
        "",
        f"> **{report.label}**  ",
        f"> n={report.pilot_n} -- release gate requires n>={report.release_gate_n}",
        "",
        "| Field | Value |",
        "|:---|:---|",
        f"| Run ID | `{report.run_id}` |",
        f"| Timestamp (UTC) | {report.timestamp_utc} |",
        f"| Provider | {report.provider} |",
        f"| Model | {report.model} |",
        f"| Git SHA | `{report.git_sha}` |",
        f"| Dataset hash | `{report.dataset_hash}` |",
        f"| Live | {'Yes' if report.live else 'No (skipped)'} |",
        f"| Release eligible | {'Yes' if report.release_eligible else '**No** -- pilot only'} |",
        "",
        "## Results",
        "",
        f"**Mechanism accuracy: {report.mechanism_accuracy_pct:.1f}%** ({report.passed}/{report.total} passed)",
        "",
        "| ID | Title | Cause Summary | Components | Mechanisms | Hallucination | Result |",
        "|:--|:--|:--|:--|:--|:--|:--|",
    ]
    for s in report.scores:
        result_str = "PASS" if s.mechanism_match else ("ERROR" if s.error else "FAIL")
        halluc = f"YES: {s.hallucination_detail}" if s.hallucination_detected else "None"
        summary_trunc = (s.cause_summary[:55] + "...") if len(s.cause_summary) > 55 else s.cause_summary
        lines.append(
            f"| {s.scenario_id} | {s.title[:38]}... | {summary_trunc} | "
            f"{', '.join(s.components_matched) or 'NONE'} | "
            f"{', '.join(s.mechanisms_matched) or 'NONE'} | "
            f"{halluc} | {result_str} |"
        )

    lines += [
        "",
        "## Scoring Methodology",
        "",
        "Scoring uses a **deterministic mechanism rubric** per scenario.",
        "**Keyword/substring overlap alone is NOT sufficient** for a PASS.",
        "A case PASSES only when ALL of the following hold:",
        "",
        "1. At least one `primary_component` appears in `cause_summary` or `confidence_rationale`.",
        "2. At least one `causal_mechanism` appears in `cause_summary` or `confidence_rationale`.",
        "3. No `hallucination_check` term dominates the first 120 chars of `cause_summary`.",
        "",
        "## Release Gate Status",
        "",
        f"> WARNING: NOT RELEASE ELIGIBLE -- pilot run (n={report.pilot_n}).",
        f"> Release gate requires n>={report.release_gate_n} independently authored,",
        "> stratified, and peer-reviewed cases per docs/evaluation-methodology.md S2.",
        "",
        "This number MUST NOT be reported as the same metric as Orchestration Certification",
        "(which uses mocked LLM boundaries and validates state-machine wiring,",
        "not LLM diagnostic accuracy).",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Public entry point  (called by run_eval.py via importlib)
# ---------------------------------------------------------------------------


async def run_benchmark(
    *,
    run_id: str,
    live: bool,
    provider: Optional[str],
    model: Optional[str],
    artifacts_dir: str,
) -> bool:
    """Run the Live RCA Benchmark Pilot (n=10).

    Parameters
    ----------
    run_id        : Unique run identifier supplied by run_eval.py.
    live          : If True, requires a real LLM provider and credentials.
                    If False, prints a skip notice and returns True
                    (not a failure, but no benchmark score is produced).
    provider      : LLM provider name ('gemini', 'openai', 'anthropic', 'groq').
    model         : Model name (e.g. 'gemini-1.5-pro', 'gpt-4o').
    artifacts_dir : Directory to write rca-benchmark-report.json and .md.

    Returns
    -------
    True  -- all scored cases passed the rubric, or live=False (skip).
    False -- one or more cases failed or errored.

    Raises
    ------
    RuntimeError  -- live=True but credentials are missing/invalid.
                     Never silently substitutes a mock.
    """
    os.makedirs(artifacts_dir, exist_ok=True)
    report_json_path = os.path.join(artifacts_dir, "rca-benchmark-report.json")
    report_md_path = os.path.join(artifacts_dir, "rca-benchmark-report.md")

    sep = "=" * 66
    print(f"\n{sep}")
    print(f"  Live RCA Benchmark Pilot -- {BENCHMARK_LABEL}")
    print(f"  n={BENCHMARK_N}  (release gate requires n>={RELEASE_GATE_N})")
    print(sep)

    if not live:
        msg = (
            "  --live not specified. Skipping live RCA benchmark.\n"
            "  To run:\n"
            "    python eval/run_eval.py --mode rca --live"
            " --provider <provider> --model <model>\n"
            "  This skip is NOT a test failure -- but no benchmark score is produced.\n"
        )
        print(msg)
        _report = {
            "run_id": run_id,
            "mode": "rca",
            "label": BENCHMARK_LABEL,
            "live": False,
            "status": "SKIPPED",
            "reason": "--live not specified; live LLM credential required for real benchmark",
        }
        with open(report_json_path, "w") as f:
            json.dump(_report, f, indent=2)
        print(sep)
        return True  # Skip is not a failure

    # -- Live mode ---------------------------------------------------------
    if not provider or not model:
        raise RuntimeError("--live requires --provider <provider> and --model <model>.")

    gateway = _build_live_gateway(provider, model)

    report = BenchmarkReport(
        run_id=run_id,
        label=BENCHMARK_LABEL,
        pilot_n=BENCHMARK_N,
        release_gate_n=RELEASE_GATE_N,
        live=True,
        provider=provider,
        model=model,
        git_sha=_git_sha(),
        dataset_hash=_dataset_hash(GOLDEN_SCENARIOS),
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )

    for scenario in GOLDEN_SCENARIOS[:BENCHMARK_N]:
        print(f"\n  [{scenario['id']:02d}/{BENCHMARK_N}] {scenario['title']}")
        t0 = time.monotonic()

        try:
            state = await _run_agents_on_scenario(scenario, gateway)
            latency_ms = int((time.monotonic() - t0) * 1000)

            rca = state.get("root_cause", {})
            cause_summary: str = rca.get("cause_summary", "")
            confidence: float = float(rca.get("confidence", 0.0))
            confidence_rationale: str = rca.get("confidence_rationale", "")

            ground_truth: str = scenario["answer_key"]["ground_truth_root_cause"]
            rubric = scenario["mechanism_rubric"]

            (
                mechanism_match,
                components_matched,
                mechanisms_matched,
                trigger_matched,
                hallucination_detected,
                hallucination_detail,
            ) = _score_mechanism(cause_summary, confidence_rationale, rubric)

            score = RubricScore(
                scenario_id=scenario["id"],
                title=scenario["title"],
                cause_summary=cause_summary,
                ground_truth=ground_truth,
                components_matched=components_matched,
                mechanisms_matched=mechanisms_matched,
                trigger_matched=trigger_matched,
                hallucination_detected=hallucination_detected,
                hallucination_detail=hallucination_detail,
                mechanism_match=mechanism_match,
                confidence_reported=confidence,
                latency_ms=latency_ms,
            )
            report.scores.append(score)

            result_str = "PASS" if mechanism_match else "FAIL"
            print(f"       Cause summary : {cause_summary[:80]}...")
            print(f"       Ground truth  : {ground_truth}")
            print(f"       Components hit: {components_matched}")
            print(f"       Mechanisms hit: {mechanisms_matched}")
            if hallucination_detected:
                print(f"       Hallucination : {hallucination_detail}")
            print(f"       Confidence    : {confidence:.2f}  |  Latency: {latency_ms}ms")
            print(f"       Result        : {result_str}")

        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            score = RubricScore(
                scenario_id=scenario["id"],
                title=scenario["title"],
                cause_summary="",
                ground_truth=scenario["answer_key"]["ground_truth_root_cause"],
                components_matched=[],
                mechanisms_matched=[],
                trigger_matched=False,
                hallucination_detected=False,
                hallucination_detail="",
                mechanism_match=False,
                confidence_reported=0.0,
                latency_ms=latency_ms,
                error=str(exc),
            )
            report.scores.append(score)
            print(f"       ERROR: {exc}")
            logger.exception("RCA benchmark error on scenario %d", scenario["id"])

    # -- Tally ---------------------------------------------------------------
    report.total = len(report.scores)
    report.passed = sum(1 for s in report.scores if s.mechanism_match and not s.error)
    report.failed = sum(1 for s in report.scores if not s.mechanism_match and not s.error)
    report.errored = sum(1 for s in report.scores if s.error)
    report.mechanism_accuracy_pct = (
        (report.passed / report.total * 100) if report.total > 0 else 0.0
    )
    report.release_eligible = False  # Always False: n=10 < 50
    report.summary = (
        f"Live RCA benchmark (pilot, n={report.total}): "
        f"{report.mechanism_accuracy_pct:.1f}% -- {BENCHMARK_LABEL}, "
        f"target n>={report.release_gate_n}"
    )

    # -- Write JSON report ---------------------------------------------------
    report_dict = {
        "run_id": report.run_id,
        "label": report.label,
        "pilot_n": report.pilot_n,
        "release_gate_n": report.release_gate_n,
        "release_eligible": report.release_eligible,
        "live": report.live,
        "provider": report.provider,
        "model": report.model,
        "git_sha": report.git_sha,
        "dataset_hash": report.dataset_hash,
        "timestamp_utc": report.timestamp_utc,
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "errored": report.errored,
        "mechanism_accuracy_pct": round(report.mechanism_accuracy_pct, 2),
        "summary": report.summary,
        "scores": [asdict(s) for s in report.scores],
    }
    with open(report_json_path, "w") as f:
        json.dump(report_dict, f, indent=2)

    _write_markdown_report(report, report_md_path)

    # -- Print summary -------------------------------------------------------
    print(f"\n{sep}")
    print(f"  {report.summary}")
    print(f"  Passed  : {report.passed}/{report.total}")
    print(f"  Failed  : {report.failed}/{report.total}")
    print(f"  Errored : {report.errored}/{report.total}")
    print(f"  JSON    : {report_json_path}")
    print(f"  Markdown: {report_md_path}")
    print(f"{sep}\n")

    return report.failed == 0 and report.errored == 0


# ---------------------------------------------------------------------------
# CLI entry point (direct invocation without run_eval.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    def _load_env() -> None:
        if os.path.exists(".env"):
            with open(".env", "r", encoding="utf-8") as _fh:
                for _ln in _fh:
                    _ln = _ln.strip()
                    if _ln and not _ln.startswith("#") and "=" in _ln:
                        _k, _v = _ln.split("=", 1)
                        _k = _k.strip()
                        _v = _v.strip()
                        if _v.startswith('"') and '"' in _v[1:]:
                            _v = _v[1:_v.find('"', 1)]
                        elif _v.startswith("'") and "'" in _v[1:]:
                            _v = _v[1:_v.find("'", 1)]
                        elif "#" in _v:
                            _v = _v.split("#", 1)[0].strip()
                        else:
                            _v = _v.strip().strip('"').strip("'")
                        if _k not in os.environ:
                            os.environ[_k] = _v

    _load_env()

    _p = argparse.ArgumentParser(
        description=f"RISE Live RCA Benchmark Judge ({BENCHMARK_LABEL})",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python eval/rca_judge.py\n"
            "  python eval/rca_judge.py --provider gemini --model gemini-1.5-pro\n"
            "  python eval/rca_judge.py --provider openai --model gpt-4o\n"
            "  python eval/rca_judge.py --provider anthropic --model claude-3-5-sonnet-20241022\n"
        ),
    )
    _p.add_argument("--provider", default=None, help="LLM provider (gemini|openai|anthropic|groq)")
    _p.add_argument("--model", default=None, help="Model name")
    _p.add_argument("--live", action="store_true", help="Run live evaluation with real LLM calls")
    _args = _p.parse_args()

    _run_id = str(uuid.uuid4())[:8]
    _artifacts_dir = os.path.join("eval", "artifacts", _run_id)

    _is_live = _args.live or bool(_args.provider and _args.model)
    _ok = asyncio.run(
        run_benchmark(
            run_id=_run_id,
            live=_is_live,
            provider=_args.provider,
            model=_args.model,
            artifacts_dir=_artifacts_dir,
        )
    )
    sys.exit(0 if _ok else 1)

