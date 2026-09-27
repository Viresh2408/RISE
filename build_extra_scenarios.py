"""One-shot builder: append 10 stratified, concept-isolated pilot scenarios
(ids 11-20, seeded from incidents.json) to eval/golden_dataset/rca_scenarios.json.

INTEGRITY: every appended case is machine-authored -> peer_reviewed=False.  It
grows the PILOT corpus only; it can never confer release eligibility (the honest
gate in rca_judge.py requires human peer review + n>=50 + >=80%).  A verbatim
ground-truth-isolation + solvability check runs before anything is written.
"""
from __future__ import annotations

import json
import re

PATH = "eval/golden_dataset/rca_scenarios.json"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


NEW: list[dict] = []
NEW.append({
    "id": 11,
    "title": "search-service latency spike -- single pod CPU pegged",
    "service": "search-service",
    "raw_evidence": {
        "timeline": [
            {"timestamp": "2026-03-04T09:12:00Z", "event": "New 'advanced filter' search feature enabled via flag for 100% of traffic", "source": "feature-flag-audit"},
            {"timestamp": "2026-03-04T09:19:40Z", "event": "search-service-7b9 CPU crosses 95% and stays pegged; other 4 pods normal", "source": "prometheus-alert"},
            {"timestamp": "2026-03-04T09:21:10Z", "event": "p99 query latency 180ms -> 14s on affected pod; heap flat at 41%", "source": "grafana"}
        ],
        "log_excerpts": [
            {"source": "search-service-7b9", "excerpt": "WARN parser: matching input against pattern took 11284ms (thread search-worker-3 stuck in java.util.regex.Pattern$Curly.match)"},
            {"source": "search-service-7b9", "excerpt": "DEBUG incoming query='(a+)+$' user_filter='name~=((x*)*)y' -- compiled to backtracking automaton, steps>2^31"},
            {"source": "search-service-7b9", "excerpt": "INFO GC minor 12ms, old-gen stable; no allocation pressure detected"}
        ],
        "metric_snapshots": [
            {"metric": "cpu_usage_pct{pod=search-service-7b9}", "value": "100", "window": "9m"},
            {"metric": "jvm_heap_used_pct{pod=search-service-7b9}", "value": "41", "window": "9m"},
            {"metric": "threads_runnable_in_regex", "value": "6", "window": "1m"}
        ],
        "recent_deploys": []
    },
    "answer_key": {
        "ground_truth_root_cause": "regex denial of service in the user query parser",
        "provenance": "root-caused by on-call from thread dump showing catastrophic backtracking on a crafted filter expression",
        "verified_by": "search platform team, incident SR-1181 postmortem"
    },
    "mechanism_rubric": {
        "primary_components": ["regex", "query parser", "pattern matcher"],
        "causal_mechanisms": ["backtracking", "cpu pegged", "cpu exhaustion", "runaway matching"],
        "causal_trigger": ["crafted user filter", "nested quantifier input", "advanced filter feature"],
        "hallucination_check": ["memory leak", "out of memory", "deadlock", "network saturation", "gc pause"]
    }
})
NEW.append({
    "id": 12,
    "title": "inventory-service order failures during flash sale",
    "service": "inventory-service",
    "raw_evidence": {
        "timeline": [
            {"timestamp": "2026-03-11T18:00:00Z", "event": "Flash sale opens; write QPS to inventory 4x baseline", "source": "traffic-manager"},
            {"timestamp": "2026-03-11T18:03:22Z", "event": "Spike in 500s on POST /reserve; 0.9% of reservations rolled back", "source": "api-gateway"},
            {"timestamp": "2026-03-11T18:04:05Z", "event": "PagerDuty critical: inventory reservation error rate > 0.5%", "source": "pagerduty"}
        ],
        "log_excerpts": [
            {"source": "inventory-service", "excerpt": "ERROR org.postgresql.util.PSQLException: ERROR: deadlock detected; Detail: Process 8841 waits for ShareLock on transaction 55210; Process 8839 waits for ShareLock on transaction 55214."},
            {"source": "postgres-primary", "excerpt": "DETAIL: Process 8841 holds lock on relation inventory_items row (sku=A), waiting for row (sku=B); Process 8839 holds row (sku=B), waiting for row (sku=A)."},
            {"source": "inventory-service", "excerpt": "INFO bulk reserve tx updates rows in the order they arrive in the cart payload"}
        ],
        "metric_snapshots": [
            {"metric": "pg_deadlocks_total", "value": "37", "window": "5m"},
            {"metric": "reserve_rollback_ratio", "value": "0.009", "window": "5m"},
            {"metric": "db_connections_in_use", "value": "22/100", "window": "5m"}
        ],
        "recent_deploys": [
            {"repo": "inventory-service", "commit": "c41a7de", "deployed_at": "2026-03-10T22:14:00Z", "author": "dev-team", "pr_title": "batch multi-SKU reservations into one transaction"}
        ]
    },
    "answer_key": {
        "ground_truth_root_cause": "inconsistent row lock acquisition order in the multi-SKU reservation transaction",
        "provenance": "confirmed from postgres deadlock detail showing two transactions locking the same rows in opposite order under concurrency",
        "verified_by": "inventory team, incident INV-903 review"
    },
    "mechanism_rubric": {
        "primary_components": ["row lock", "reservation transaction", "postgres", "inventory_items"],
        "causal_mechanisms": ["deadlock", "lock ordering", "circular wait", "lock contention"],
        "causal_trigger": ["concurrent multi-sku reservations", "flash sale write spike", "batch reservation deploy"],
        "hallucination_check": ["connection pool exhausted", "out of memory", "network partition", "disk full", "cpu"]
    }
})
NEW.append({
    "id": 13,
    "title": "billing-service checkout latency and thread starvation",
    "service": "billing-service",
    "raw_evidence": {
        "timeline": [
            {"timestamp": "2026-02-19T13:40:00Z", "event": "External status page reports elevated latency at payment provider", "source": "vendor-status-webhook"},
            {"timestamp": "2026-02-19T13:47:30Z", "event": "billing-service worker pool saturated; queued requests climbing", "source": "grafana"},
            {"timestamp": "2026-02-19T13:49:00Z", "event": "Checkout p95 320ms -> 9.8s; no billing-service deploy in last 14 days", "source": "deploy-tracker"}
        ],
        "log_excerpts": [
            {"source": "billing-service", "excerpt": "WARN http-client: call to https://api.stripe.com/v1/charges exceeded 8000ms socket read; 47 worker threads BLOCKED on this call"},
            {"source": "billing-service", "excerpt": "ERROR java.net.SocketTimeoutException: Read timed out (no breaker in chain, request forwarded to caller after full wait)"},
            {"source": "billing-service", "excerpt": "INFO outbound charge attempts have no bounded retry budget or fast-fail path configured"}
        ],
        "metric_snapshots": [
            {"metric": "upstream_latency_ms{host=api.stripe.com}", "value": "8600", "window": "6m"},
            {"metric": "worker_threads_blocked", "value": "47/50", "window": "1m"},
            {"metric": "billing_db_query_ms_p95", "value": "12", "window": "6m"}
        ],
        "recent_deploys": []
    },
    "answer_key": {
        "ground_truth_root_cause": "unbounded blocking on a slow payment-provider dependency with no circuit breaker or fallback",
        "provenance": "traced to worker threads pinned on synchronous provider calls during vendor-side latency; database was healthy throughout",
        "verified_by": "payments reliability team, incident BILL-455"
    },
    "mechanism_rubric": {
        "primary_components": ["payment provider", "http client", "worker pool", "upstream dependency"],
        "causal_mechanisms": ["threads blocked", "thread starvation", "blocking", "no circuit breaker", "no fallback"],
        "causal_trigger": ["provider latency spike", "upstream degradation"],
        "hallucination_check": ["database slow", "out of memory", "deadlock", "dns failure", "code regression from deploy"]
    }
})
NEW.append({
    "id": 14,
    "title": "order-service event processing stalled",
    "service": "order-service",
    "raw_evidence": {
        "timeline": [
            {"timestamp": "2026-01-27T07:05:00Z", "event": "Downstream fulfillment stops receiving order events; consumer lag begins climbing linearly", "source": "kafka-lag-exporter"},
            {"timestamp": "2026-01-27T07:11:00Z", "event": "Consumer group order-svc re-reads same offset repeatedly; no commit advance for 6 min", "source": "grafana"},
            {"timestamp": "2026-01-27T07:12:30Z", "event": "Broker cluster healthy; all partitions have live leaders; no rebalance events", "source": "kafka-admin"}
        ],
        "log_excerpts": [
            {"source": "order-service", "excerpt": "ERROR failed to deserialize record at partition orders-3 offset 88123: unexpected schema id 0x91, expected orders.v2; will retry"},
            {"source": "order-service", "excerpt": "WARN consumer stuck: offset 88123 attempted 214 times, exception rethrown, offset NOT committed, loop re-polls same record"},
            {"source": "order-service", "excerpt": "INFO all other partitions idle because single-threaded handler blocks on the failing record"}
        ],
        "metric_snapshots": [
            {"metric": "kafka_consumer_lag{group=order-svc}", "value": "41200", "window": "7m"},
            {"metric": "committed_offset_delta{partition=orders-3}", "value": "0", "window": "6m"},
            {"metric": "broker_under_replicated_partitions", "value": "0", "window": "7m"}
        ],
        "recent_deploys": [
            {"repo": "checkout-service", "commit": "9de11a2", "deployed_at": "2026-01-27T07:02:00Z", "author": "checkout-team", "pr_title": "start emitting orders.v3 envelope (new schema id)"}
        ]
    },
    "answer_key": {
        "ground_truth_root_cause": "a poison-pill message the consumer cannot deserialize, trapping it in an infinite non-committing retry loop",
        "provenance": "root-caused to an upstream schema change producing records the order consumer rejects, blocking the whole partition at one offset",
        "verified_by": "order platform team, incident ORD-2210"
    },
    "mechanism_rubric": {
        "primary_components": ["kafka consumer", "consumer group", "orders partition", "offset"],
        "causal_mechanisms": ["deserialization failure", "retry loop", "consumer stuck", "offset not committed"],
        "causal_trigger": ["upstream schema change", "malformed record", "unexpected schema id"],
        "hallucination_check": ["broker down", "disk full", "network partition", "rebalance storm", "consumer scaled down"]
    }
})
NEW.append({
    "id": 15,
    "title": "recommendation-service cache writes failing at peak",
    "service": "recommendation-service",
    "raw_evidence": {
        "timeline": [
            {"timestamp": "2026-02-02T20:00:00Z", "event": "Evening peak; recommendation cache working set grows past provisioned memory", "source": "grafana"},
            {"timestamp": "2026-02-02T20:06:10Z", "event": "Cache SET operations start erroring; read hit ratio collapses as new entries cannot be stored", "source": "redis-exporter"},
            {"timestamp": "2026-02-02T20:07:00Z", "event": "recommendation latency 45ms -> 900ms as service falls back to recomputing everything", "source": "grafana"}
        ],
        "log_excerpts": [
            {"source": "recommendation-service", "excerpt": "ERROR redis: OOM command not allowed when used memory > 'maxmemory' (SET rec:user:8813)"},
            {"source": "redis-config-snapshot", "excerpt": "used_memory=4.00G maxmemory=4.00G maxmemory-policy=noeviction keyspace_misses spiking"},
            {"source": "recommendation-service", "excerpt": "WARN cache write rejected; falling back to synchronous recompute for every request"}
        ],
        "metric_snapshots": [
            {"metric": "redis_used_memory_bytes / redis_maxmemory_bytes", "value": "1.00", "window": "8m"},
            {"metric": "redis_rejected_writes_total", "value": "9021", "window": "8m"},
            {"metric": "redis_evicted_keys_total", "value": "0", "window": "8m"}
        ],
        "recent_deploys": []
    },
    "answer_key": {
        "ground_truth_root_cause": "the Redis instance is configured to reject writes instead of evicting keys once memory is full",
        "provenance": "confirmed from the OOM-on-write errors combined with a memory policy that never evicts, so a full cache stops accepting new entries",
        "verified_by": "recommendations team, incident REC-771"
    },
    "mechanism_rubric": {
        "primary_components": ["redis", "cache", "maxmemory-policy"],
        "causal_mechanisms": ["noeviction", "rejects writes", "oom on write", "no keys evicted"],
        "causal_trigger": ["peak working set exceeds maxmemory", "memory limit reached"],
        "hallucination_check": ["application memory leak", "network", "disk full", "cpu saturation", "redis crashed"]
    }
})
NEW.append({
    "id": 16,
    "title": "user-service intermittent internal lookup failures",
    "service": "user-service",
    "raw_evidence": {
        "timeline": [
            {"timestamp": "2026-03-18T15:22:00Z", "event": "Node ip-10-2-3-44 reports MemoryPressure; kubelet begins evicting low-priority pods", "source": "k8s-events"},
            {"timestamp": "2026-03-18T15:23:10Z", "event": "user-service starts logging sporadic failures resolving internal service hostnames", "source": "grafana"},
            {"timestamp": "2026-03-18T15:24:00Z", "event": "Error rate to user-db and auth-service intermittent (~8%); healthy pods co-scheduled on the affected node", "source": "prometheus"}
        ],
        "log_excerpts": [
            {"source": "kube-system events", "excerpt": "Evicted: coredns-5d8f-abc pod evicted due to node MemoryPressure; only 1 DNS replica remained schedulable"},
            {"source": "user-service", "excerpt": "ERROR dial tcp: lookup user-db.prod.svc.cluster.local on 10.96.0.10:53: read udp i/o timeout"},
            {"source": "user-service", "excerpt": "WARN retry succeeded on 2nd attempt; failures correlate with in-cluster name resolution, not the databases themselves"}
        ],
        "metric_snapshots": [
            {"metric": "coredns_ready_replicas", "value": "1/2", "window": "5m"},
            {"metric": "dns_query_timeout_ratio", "value": "0.08", "window": "5m"},
            {"metric": "user_db_up", "value": "1", "window": "5m"}
        ],
        "recent_deploys": []
    },
    "answer_key": {
        "ground_truth_root_cause": "cluster DNS pods were evicted under node memory pressure, causing intermittent name-resolution timeouts",
        "provenance": "correlated the eviction events for the in-cluster DNS deployment with the lookup timeouts; backend databases were healthy the whole time",
        "verified_by": "platform SRE, incident USR-1490"
    },
    "mechanism_rubric": {
        "primary_components": ["coredns", "cluster dns", "name resolution"],
        "causal_mechanisms": ["pod eviction", "evicted", "lookup timeout", "resolution failure"],
        "causal_trigger": ["node memory pressure", "dns replica loss"],
        "hallucination_check": ["database down", "application bug", "tls handshake", "code deploy", "connection pool"]
    }
})
NEW.append({
    "id": 17,
    "title": "metrics-service ingestion stopped accepting samples",
    "service": "metrics-service",
    "raw_evidence": {
        "timeline": [
            {"timestamp": "2026-01-14T02:10:00Z", "event": "New high-cardinality label rolled out on request metrics; series count doubles overnight", "source": "config-audit"},
            {"timestamp": "2026-01-14T05:41:00Z", "event": "Prometheus data volume approaches full; sample appends begin failing", "source": "prometheus-self-monitor"},
            {"timestamp": "2026-01-14T05:44:00Z", "event": "Dashboards go blank; no new samples stored; query path still serves old blocks", "source": "grafana"}
        ],
        "log_excerpts": [
            {"source": "prometheus", "excerpt": "ERROR write-ahead log: write /prometheus/wal/00004821: no space left on device"},
            {"source": "prometheus", "excerpt": "WARN compaction skipped; head block cannot be truncated; volume /prometheus at 99% (retention window not enforced against volume size)"},
            {"source": "node-exporter", "excerpt": "filesystem /prometheus size=200Gi used=198Gi avail=2Gi"}
        ],
        "metric_snapshots": [
            {"metric": "prometheus_tsdb_wal_disk_usage_pct", "value": "99", "window": "10m"},
            {"metric": "prometheus_tsdb_head_series", "value": "9100000", "window": "10m"},
            {"metric": "node_cpu_utilization{prometheus}", "value": "0.22", "window": "10m"}
        ],
        "recent_deploys": []
    },
    "answer_key": {
        "ground_truth_root_cause": "the Prometheus data volume filled up because retention did not bound on-disk size against a cardinality surge",
        "provenance": "root-caused to WAL append failures on a full volume driven by a high-cardinality label explosion; CPU and memory were fine",
        "verified_by": "observability team, incident MET-388"
    },
    "mechanism_rubric": {
        "primary_components": ["prometheus", "wal", "data volume", "tsdb"],
        "causal_mechanisms": ["no space left", "disk full", "retention not enforced", "cannot truncate"],
        "causal_trigger": ["high cardinality label", "series explosion"],
        "hallucination_check": ["out of memory", "cpu saturation", "network", "query overload", "process crash"]
    }
})
NEW.append({
    "id": 18,
    "title": "content-service serving stale pages after publish",
    "service": "content-service",
    "raw_evidence": {
        "timeline": [
            {"timestamp": "2026-02-25T11:00:00Z", "event": "Security change tightens the storage bucket permissions in prod", "source": "cloudtrail"},
            {"timestamp": "2026-02-25T11:30:00Z", "event": "Editors publish updates; readers keep seeing the old version at the edge", "source": "support-tickets"},
            {"timestamp": "2026-02-25T11:38:00Z", "event": "CDN cache-invalidation jobs report failures; origin fetches denied", "source": "cdn-console"}
        ],
        "log_excerpts": [
            {"source": "content-service", "excerpt": "ERROR CloudFront createInvalidation ok, but origin revalidation returns 403 AccessDenied from origin bucket"},
            {"source": "s3-access-logs", "excerpt": "REST.GET.OBJECT content/home.html 403 AccessDenied requester=cloudfront OAC arn:...:distribution/E12; principal not permitted by bucket policy"},
            {"source": "content-service", "excerpt": "INFO edge continues serving last-good cached object because it cannot revalidate against origin"}
        ],
        "metric_snapshots": [
            {"metric": "cdn_origin_403_ratio", "value": "1.0", "window": "8m"},
            {"metric": "stale_hit_ratio", "value": "0.97", "window": "8m"},
            {"metric": "origin_5xx_ratio", "value": "0.0", "window": "8m"}
        ],
        "recent_deploys": [
            {"repo": "infra-security", "commit": "77bc0e1", "deployed_at": "2026-02-25T11:00:00Z", "author": "sec-team", "pr_title": "restrict prod content bucket to explicit principals"}
        ]
    },
    "answer_key": {
        "ground_truth_root_cause": "a tightened storage-bucket permission stopped the CDN from reading the origin, so purges could not revalidate and stale content persisted",
        "provenance": "correlated the bucket-permission change with origin 403s to the CDN identity; the application and origin objects were otherwise healthy",
        "verified_by": "content platform team, incident CON-604"
    },
    "mechanism_rubric": {
        "primary_components": ["bucket policy", "cloudfront", "cdn", "origin access"],
        "causal_mechanisms": ["access denied", "403", "denied revalidation", "stale cache"],
        "causal_trigger": ["bucket permission change", "origin identity not permitted"],
        "hallucination_check": ["dns", "origin down", "tls", "application code bug", "out of memory"]
    }
})
NEW.append({
    "id": 19,
    "title": "ingress rejecting file uploads",
    "service": "ingress-gateway",
    "raw_evidence": {
        "timeline": [
            {"timestamp": "2026-03-01T10:15:00Z", "event": "New document-upload feature ships to users; average upload size ~3MB", "source": "product-release"},
            {"timestamp": "2026-03-01T10:18:00Z", "event": "Upload endpoint returns errors for larger files while small uploads succeed", "source": "grafana"},
            {"timestamp": "2026-03-01T10:20:00Z", "event": "Backend upload handler never receives the request; rejection happens at the edge proxy", "source": "trace-view"}
        ],
        "log_excerpts": [
            {"source": "nginx-ingress", "excerpt": "2026/03/01 10:18:42 [error] client intended to send too large body: 3145728 bytes, returning 413 Request Entity Too Large"},
            {"source": "ingress-config-snapshot", "excerpt": "annotations: (no nginx.ingress.kubernetes.io/proxy-body-size set) -> client_max_body_size defaulting to 1m"},
            {"source": "upload-service", "excerpt": "INFO 0 requests reached the handler for files > 1MB; access log shows no matching upstream entry"}
        ],
        "metric_snapshots": [
            {"metric": "ingress_http_413_total", "value": "1544", "window": "5m"},
            {"metric": "upload_success_ratio{size>1mb}", "value": "0.0", "window": "5m"},
            {"metric": "upstream_upload_handler_5xx", "value": "0", "window": "5m"}
        ],
        "recent_deploys": []
    },
    "answer_key": {
        "ground_truth_root_cause": "the ingress proxy body-size limit is smaller than the files users upload, so large requests are rejected before reaching the backend",
        "provenance": "root-caused to a default 1MB proxy body limit against multi-MB uploads, producing 413s at the edge with no backend involvement",
        "verified_by": "platform networking team, incident ING-233"
    },
    "mechanism_rubric": {
        "primary_components": ["nginx ingress", "proxy body size", "client_max_body_size"],
        "causal_mechanisms": ["413", "too large body", "rejected at edge", "limit too small"],
        "causal_trigger": ["multi-mb file upload", "default 1mb limit"],
        "hallucination_check": ["backend down", "upstream timeout", "auth failure", "out of memory", "tls"]
    }
})
NEW.append({
    "id": 20,
    "title": "analytics-service query timeouts during business hours",
    "service": "analytics-service",
    "raw_evidence": {
        "timeline": [
            {"timestamp": "2026-02-11T14:00:00Z", "event": "A schema migration is started against the reporting database during peak reporting load", "source": "migration-runner"},
            {"timestamp": "2026-02-11T14:00:20Z", "event": "Read queries begin queueing; nothing is being deleted, but everything waits", "source": "grafana"},
            {"timestamp": "2026-02-11T14:01:30Z", "event": "PagerDuty critical: analytics query p99 > 30s; queries pile up behind a single blocked statement", "source": "pagerduty"}
        ],
        "log_excerpts": [
            {"source": "postgres-reporting", "excerpt": "LOG: process 4471 still waiting for AccessExclusiveLock on relation events_fact after 30012.114 ms"},
            {"source": "postgres-reporting", "excerpt": "STATEMENT: ALTER TABLE events_fact ADD COLUMN campaign_id bigint; -- holds the table, blocks all readers"},
            {"source": "analytics-service", "excerpt": "WARN 100% of SELECTs on events_fact blocked; connections healthy, CPU low, they are simply queued behind the ALTER"}
        ],
        "metric_snapshots": [
            {"metric": "pg_blocked_queries{relation=events_fact}", "value": "212", "window": "3m"},
            {"metric": "pg_lock_wait_seconds_max", "value": "31", "window": "3m"},
            {"metric": "reporting_db_cpu_pct", "value": "18", "window": "3m"}
        ],
        "recent_deploys": [
            {"repo": "analytics-migrations", "commit": "a0f9b12", "deployed_at": "2026-02-11T14:00:00Z", "author": "data-eng", "pr_title": "add campaign_id column to events_fact"}
        ]
    },
    "answer_key": {
        "ground_truth_root_cause": "a schema migration took a table-wide exclusive lock during peak traffic, blocking all reads on the reporting table",
        "provenance": "root-caused to an ALTER holding an AccessExclusiveLock while readers queued behind it; there was no deadlock and resources were idle",
        "verified_by": "data engineering team, incident ANA-980"
    },
    "mechanism_rubric": {
        "primary_components": ["schema migration", "alter table", "access exclusive lock", "events_fact"],
        "causal_mechanisms": ["exclusive lock", "blocks all readers", "lock wait", "queries queued"],
        "causal_trigger": ["migration during peak", "ddl on hot table"],
        "hallucination_check": ["deadlock", "connection pool exhausted", "out of memory", "network", "cpu saturation"]
    }
})


def _raw_blob(s: dict) -> str:
    return _norm(json.dumps(s["raw_evidence"], ensure_ascii=False))


def _validate(s: dict) -> None:
    sid = s["id"]
    raw = _raw_blob(s)
    # 1) No answer_key string may appear verbatim in raw_evidence.
    for k, v in s["answer_key"].items():
        if isinstance(v, str) and _norm(v) and _norm(v) in raw:
            raise SystemExit(f"id{sid}: answer_key['{k}'] leaks verbatim into raw_evidence")
    # 2) Solvability: at least one primary_component AND one causal_mechanism
    #    must be discoverable in the raw evidence (else the case is unfair).
    comp_hit = [c for c in s["mechanism_rubric"]["primary_components"] if _norm(c) in raw]
    mech_hit = [m for m in s["mechanism_rubric"]["causal_mechanisms"] if _norm(m) in raw]
    if not comp_hit:
        raise SystemExit(f"id{sid}: no primary_component appears in raw_evidence (unsolvable)")
    if not mech_hit:
        raise SystemExit(f"id{sid}: no causal_mechanism appears in raw_evidence (unsolvable)")


def main() -> None:
    with open(PATH, "r", encoding="utf-8") as f:
        scenarios = json.load(f)
    existing_ids = {s["id"] for s in scenarios}
    for s in NEW:
        if s["id"] in existing_ids:
            raise SystemExit(f"id{s['id']} already present")
        s.setdefault("peer_reviewed", False)
        assert s["peer_reviewed"] is False, "machine-authored cases must be peer_reviewed=False"
        _validate(s)
    scenarios.extend(NEW)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(scenarios, f, indent=2, ensure_ascii=True)
        f.write("\n")
    print(f"appended {len(NEW)} scenarios; corpus now n={len(scenarios)}; "
          f"peer_reviewed={sum(1 for s in scenarios if s.get('peer_reviewed') is True)}")


if __name__ == "__main__":
    main()
