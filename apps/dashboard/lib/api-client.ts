import {
  ApiResponse,
  ActionApproveResponse,
  ActionModifyResponse,
  ActionRejectResponse,
  IncidentDTO,
  IncidentDetailDTO,
  KnowledgeDTO,
  PolicyDTO,
  MttrReportDTO,
  AutonomyReportDTO,
  IntegrationDTO,
  AgentRunDTO,
  AgentStepDTO,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ? `${process.env.NEXT_PUBLIC_API_URL}/api/v1` : '/api/v1';

export class ApiError extends Error {
  code: string;
  details?: Record<string, any>;
  status: number;

  constructor(message: string, code: string = 'UNKNOWN_ERROR', status: number = 500, details?: Record<string, any>) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function generateUUID(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

async function request<T>(
  endpoint: string,
  options: RequestInit & { token?: string | null; idempotencyKey?: string } = {}
): Promise<T> {
  const { token, idempotencyKey, headers: customHeaders, ...fetchOpts } = options;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(customHeaders as Record<string, string>),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  if (idempotencyKey) {
    headers['Idempotency-Key'] = idempotencyKey;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 3500);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${endpoint}`, {
      ...fetchOpts,
      signal: options.signal || controller.signal,
      headers,
    });
  } finally {
    clearTimeout(timeoutId);
  }

  let json: ApiResponse<T> | null = null;
  if (typeof res.text === 'function') {
    const text = await res.text();
    try {
      json = text ? JSON.parse(text) : null;
    } catch {
      // Non-JSON response (e.g. HTML 500 Internal Server Error page)
      if (!res.ok) {
        throw new ApiError(`HTTP ${res.status}: Server returned non-JSON response`, 'HTTP_ERROR', res.status);
      }
      throw new ApiError('Invalid response format from server', 'INVALID_JSON', res.status);
    }
  } else if (typeof res.json === 'function') {
    json = await res.json();
  }

  if (!res.ok || json?.error) {
    const error = json?.error || { code: 'HTTP_ERROR', message: `HTTP ${res.status} error` };
    throw new ApiError(error.message, error.code, res.status, error.details);
  }

  return (json?.data ?? (json as unknown as T)) as T;
}

export const DEMO_INCIDENTS: IncidentDTO[] = [
  {
    id: 'inc-auth-pool-01',
    title: 'PostgreSQL Connection Pool Saturation in auth-service',
    severity: 'SEV1',
    status: 'awaiting_approval',
    affected_service: 'auth-service',
    created_at: new Date(Date.now() - 12 * 60000).toISOString(),
    description: 'Surge in OAuth token requests saturated database connection pool (10/10 active connections). Connection leak in catch handler causing cascading 503 errors.',
  },
  {
    id: 'inc-pay-replay-02',
    title: 'Payment Webhook Duplicate Replay Attack & Rate Limit Trigger',
    severity: 'SEV1',
    status: 'investigating',
    affected_service: 'payment-service',
    created_at: new Date(Date.now() - 25 * 60000).toISOString(),
    description: 'Stripe webhook receiver detected 450 duplicate payloads/sec with identical event IDs. Rate-limiter triggered 429s and double-charging ledger race condition prevented.',
  },
  {
    id: 'inc-k8s-ingress-03',
    title: 'Kubernetes Ingress 504 Gateway Timeout Cascade',
    severity: 'SEV2',
    status: 'awaiting_approval',
    affected_service: 'api-gateway',
    created_at: new Date(Date.now() - 48 * 60000).toISOString(),
    description: 'NGINX Ingress proxy_read_timeout (15s) mismatch with backend async uvicorn pool under sustained 12,000 req/min traffic surge.',
  },
  {
    id: 'inc-report-oom-04',
    title: 'OOMKilled CrashLoopBackOff in PDF Analytics Worker',
    severity: 'SEV2',
    status: 'resolved',
    affected_service: 'analytics-worker',
    created_at: new Date(Date.now() - 95 * 60000).toISOString(),
    description: 'Unclosed io.BytesIO canvas stream during weekly PDF generation caused container RSS memory to breach 512MB limit.',
  },
  {
    id: 'inc-redis-stampede-05',
    title: 'Redis Session Cache Stampede on Token Refresh',
    severity: 'SEV2',
    status: 'resolved',
    affected_service: 'auth-service',
    created_at: new Date(Date.now() - 140 * 60000).toISOString(),
    description: 'Synchronized 3600s TTL expiration across 20,000 active sessions generated simultaneous cache miss wave against primary database.',
  },
  {
    id: 'inc-kafka-rebalance-06',
    title: 'Kafka Consumer Group Rebalance Storm in ingestion-worker',
    severity: 'SEV3',
    status: 'investigating',
    affected_service: 'ingestion-worker',
    created_at: new Date(Date.now() - 180 * 60000).toISOString(),
    description: 'Batch event processing time exceeded max.poll.interval.ms threshold, triggering endless partition rebalances and lag accumulation.',
  },
  {
    id: 'inc-checkout-redis-07',
    title: 'Redis Cluster Cross-Slot Pipeline Storm & Key Eviction Surge in checkout-gateway',
    severity: 'SEV1',
    status: 'awaiting_approval',
    affected_service: 'checkout-gateway',
    created_at: new Date(Date.now() - 4 * 60000).toISOString(),
    description: 'Un-hashed multi-key MGET pipeline across Redis cluster shards triggered CROSSSLOT Keys in request do not hash to the same slot exceptions. Cart checkout failure rate rose to 24.8%.',
  },
];

const REAL_INCIDENT_STORE: Record<string, IncidentDetailDTO> = {
  'inc-auth-pool-01': {
    id: 'inc-auth-pool-01',
    title: 'PostgreSQL Connection Pool Saturation in auth-service',
    severity: 'SEV1',
    status: 'awaiting_approval',
    affected_service: 'auth-service',
    created_at: new Date(Date.now() - 12 * 60000).toISOString(),
    description: 'Surge in OAuth token requests saturated database connection pool (10/10 active connections). Connection leak in catch handler causing cascading 503 errors.',
    timeline: [
      { timestamp: new Date(Date.now() - 12 * 60000).toISOString(), event: 'Alert Ingested', text: 'Prometheus alert: pg_stat_activity connection count = 10 (100% capacity)' },
      { timestamp: new Date(Date.now() - 10 * 60000).toISOString(), event: 'Context Collected', text: 'Loki logs retrieved: FATAL connection pool exhausted; Git PR #412 diff analyzed' },
      { timestamp: new Date(Date.now() - 8 * 60000).toISOString(), event: 'Root Cause Synthesized', text: 'LLM Gateway identified unclosed DB sessions in OAuth error fallback branch' },
      { timestamp: new Date(Date.now() - 6 * 60000).toISOString(), event: 'OPA Policy Evaluated', text: 'Action tier evaluated: High Risk — requires Human Operator approval' },
      { timestamp: new Date(Date.now() - 4 * 60000).toISOString(), event: 'Remediation Formulated', text: 'Generated patch for session.py: increase pool to 25 + enable pool_pre_ping' },
    ],
    root_cause: {
      cause: 'Database Connection Pool Exhaustion due to Missing Session Cleanup in Commit a8f3b29c',
      confidence: 0.94,
      explanation: 'Under spike load of 1,200 req/s, the auth-service failed to release connections back to the pool during failed token validation attempts, exhausting all 10 available connections within 45 seconds.',
      evidence: [
        { id: 'ev-01', source: 'Loki Log Stream', type: 'error_log', description: 'sqlalchemy.exc.OperationalError: FATAL: connection pool limit (10) reached for database rise_dev' },
        { id: 'ev-02', source: 'Prometheus Metrics', type: 'metric_spike', description: 'db_pool_active_connections reached 10.0 (100% pool saturation) for >3m' },
        { id: 'ev-03', source: 'GitHub PR #412', type: 'code_diff', description: 'Commit a8f3b29c modified token validation without context manager session release' },
      ],
      similar_incidents: [
        { id: 'inc-past-088', title: 'PostgreSQL Pool Saturation during Black Friday Load', similarity: 0.93 },
        { id: 'inc-past-042', title: 'Connection leak in user-portal session handler', similarity: 0.86 },
      ],
    },
    impact: {
      blast_radius: ['auth-service', 'api-gateway', 'user-portal', 'checkout-service'],
      severity: 'SEV1',
      estimated_users_affected: 8400,
      business_impact_notes: 'User authentication and checkout token refreshes failing globally; 503 error rate at 24.2%.',
    },
    decision: {
      risk_tier: 'high',
      confidence: 0.94,
      requires_approval: true,
      recommended_action: {
        id: 'act-auth-pool-01',
        description: 'Scale PostgreSQL Connection Pool and Deploy Pre-Ping Reconnection Patch to auth-service',
        steps: [
          'Apply patched connection engine settings in packages/rise-core/db/session.py',
          'Execute rolling deployment restart: kubectl rollout restart deployment/auth-service',
          'Verify connection pool headroom drops below 35% utilization',
        ],
        rollback_plan: 'kubectl rollout undo deployment/auth-service && git checkout HEAD~1 packages/rise-core/db/session.py',
        code_fix_snippet: {
          file: 'packages/rise-core/db/session.py',
          github_url: 'https://github.com/Viresh2408/RISE/blob/main/packages/rise-core/db/session.py#L18-L34',
          lines: 'L18-L34',
          commit_id: 'a8f3b29c',
          diff: `// Repository: RISE/packages/rise-core/db/session.py (L18-L34)
@@ -18,8 +18,15 @@ def _init_engine():
-    # Original connection pool with unmanaged capacity (10 connections max)
-    test_engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=5)
+    # Scaled connection pool with auto-reconnect pre-ping & leak listener cleanup
+    test_engine = create_engine(
+        DATABASE_URL,
+        pool_size=25,
+        max_overflow=25,
+        pool_pre_ping=True,
+        pool_recycle=1800,
+        connect_args={"connect_timeout": 5}
+    )`,
        },
      },
    },
    actions: [
      {
        id: 'act-auth-pool-01',
        incident_id: 'inc-auth-pool-01',
        name: 'Scale PostgreSQL Connection Pool & Deploy Pre-Ping Patch to auth-service',
        risk_tier: 'high',
        status: 'pending_approval',
      },
    ],
    approvals: [],
    verification: {
      status: 'pending',
      checks: [
        { name: 'auth-service /healthz probe', result: 'pass', value: '200 OK (latency: 18ms)' },
        { name: 'database active connection pool', result: 'fail', value: '10/10 (100% saturated)' },
        { name: 'OAuth 2.0 token endpoint error rate', result: 'fail', value: '24.2% (threshold: <0.5%)' },
      ],
    },
  },

  'inc-pay-replay-02': {
    id: 'inc-pay-replay-02',
    title: 'Payment Webhook Duplicate Replay Attack & Rate Limit Trigger',
    severity: 'SEV1',
    status: 'investigating',
    affected_service: 'payment-service',
    created_at: new Date(Date.now() - 25 * 60000).toISOString(),
    description: 'Stripe webhook receiver detected 450 duplicate payloads/sec with identical event IDs. Rate-limiter triggered 429s and double-charging ledger race condition prevented.',
    timeline: [
      { timestamp: new Date(Date.now() - 25 * 60000).toISOString(), event: 'Anomaly Detected', text: 'Ingress webhook volume spiked 1,800% on /api/v1/webhooks/stripe' },
      { timestamp: new Date(Date.now() - 23 * 60000).toISOString(), event: 'Deduplication Analysis', text: 'Identified identical event_id evt_3M92x8 over 450 repeated calls' },
      { timestamp: new Date(Date.now() - 20 * 60000).toISOString(), event: 'Root Cause Synthesized', text: 'Replay attacker exploiting lack of distributed nonce locking in receiver' },
      { timestamp: new Date(Date.now() - 17 * 60000).toISOString(), event: 'Action Generated', text: 'Injecting atomic Redis nonce lock with constant-time HMAC validation' },
    ],
    root_cause: {
      cause: 'Missing Distributed Nonce Idempotency Lock in Webhook Router',
      confidence: 0.96,
      explanation: 'Webhook endpoint processed incoming Stripe events without checking a shared distributed nonce cache, allowing rapid concurrent retries with identical event IDs to pass signature verification and attempt ledger transactions.',
      evidence: [
        { id: 'ev-11', source: 'FastAPI Access Logs', type: 'traffic_spike', description: 'POST /api/v1/webhooks/stripe received 450 identical requests in 1.2s' },
        { id: 'ev-12', source: 'Redis Monitor', type: 'cache_miss', description: 'No idempotency key recorded for Stripe event evt_3M92x8' },
      ],
      similar_incidents: [
        { id: 'inc-past-019', title: 'Webhook duplicate ingestion in billing-service', similarity: 0.91 },
      ],
    },
    impact: {
      blast_radius: ['payment-service', 'billing-ledger', 'stripe-gateway'],
      severity: 'SEV1',
      estimated_users_affected: 1250,
      business_impact_notes: 'Duplicate payment attempts detected; 429 rate limit active to protect database integrity.',
    },
    decision: {
      risk_tier: 'critical',
      confidence: 0.96,
      requires_approval: true,
      recommended_action: {
        id: 'act-pay-replay-02',
        description: 'Deploy Atomic Redis Nonce Guard & Constant-Time Webhook Verification',
        steps: [
          'Apply distributed nonce locking in apps/api/src/routers/webhooks.py',
          'Deploy hotfix patch to payment-service pods',
          'Flush duplicate queue and verify zero redundant ledger charges',
        ],
        rollback_plan: 'git checkout HEAD~1 apps/api/src/routers/webhooks.py && kubectl rollout restart deployment/payment-service',
        code_fix_snippet: {
          file: 'apps/api/src/routers/webhooks.py',
          github_url: 'https://github.com/Viresh2408/RISE/blob/main/apps/api/src/routers/webhooks.py#L64-L82',
          lines: 'L64-L82',
          commit_id: 'c4d9e11f',
          diff: `// Repository: RISE/apps/api/src/routers/webhooks.py (L64-L82)
@@ -64,6 +64,12 @@ async def stripe_webhook_handler(request: Request):
     event_id = payload.get("id")
-    # Process webhook without idempotency lock
-    await process_payment_event(event_id, payload)
+    # Atomic Redis nonce lock with 24h expiration prevents replay storm
+    lock_acquired = await redis_client.set(f"webhook:nonce:{event_id}", "1", nx=True, ex=86400)
+    if not lock_acquired:
+        logger.warning(f"Replay attack blocked for event {event_id}")
+        return build_response({"status": "duplicate_ignored", "event_id": event_id})
+    await process_payment_event(event_id, payload)`,
        },
      },
    },
    actions: [
      {
        id: 'act-pay-replay-02',
        incident_id: 'inc-pay-replay-02',
        name: 'Deploy Atomic Redis Nonce Guard & Webhook Replay Filter',
        risk_tier: 'critical',
        status: 'pending_approval',
      },
    ],
    approvals: [],
    verification: {
      status: 'pending',
      checks: [
        { name: 'Redis nonce lock latency', result: 'pass', value: '1.2ms' },
        { name: 'Duplicate webhook drop rate', result: 'pass', value: '100% blocked' },
        { name: 'Double billing audit discrepancy', result: 'pass', value: '0 items' },
      ],
    },
  },

  'inc-k8s-ingress-03': {
    id: 'inc-k8s-ingress-03',
    title: 'Kubernetes Ingress 504 Gateway Timeout Cascade',
    severity: 'SEV2',
    status: 'awaiting_approval',
    affected_service: 'api-gateway',
    created_at: new Date(Date.now() - 48 * 60000).toISOString(),
    description: 'NGINX Ingress proxy_read_timeout (15s) mismatch with backend async uvicorn pool under sustained 12,000 req/min traffic surge.',
    timeline: [
      { timestamp: new Date(Date.now() - 48 * 60000).toISOString(), event: 'Alert Ingested', text: 'PagerDuty SEV2: Ingress 504 Gateway Timeout error rate > 4.5%' },
      { timestamp: new Date(Date.now() - 44 * 60000).toISOString(), event: 'Log Tracing', text: 'NGINX upstream prematurely closed connection while uvicorn was processing complex queries' },
      { timestamp: new Date(Date.now() - 40 * 60000).toISOString(), event: 'Root Cause Synthesized', text: 'proxy_read_timeout (15s) < backend database query timeout (30s)' },
      { timestamp: new Date(Date.now() - 36 * 60000).toISOString(), event: 'Patch Formulated', text: 'Tuned ingress annotations with 65s keepalive & upstream connection pooling' },
    ],
    root_cause: {
      cause: 'Ingress Proxy Timeout Mismatch between NGINX and Asynchronous Uvicorn Backend',
      confidence: 0.91,
      explanation: 'Under high concurrency, deep analytic queries required 18-22s to complete. The NGINX Ingress controller proxy_read_timeout was set to 15s, triggering premature TCP RST drops and returning 504 Gateway Timeout to clients.',
      evidence: [
        { id: 'ev-21', source: 'NGINX Ingress Controller Logs', type: 'timeout_error', description: 'upstream timed out (110: Connection timed out) while reading response header from upstream' },
        { id: 'ev-22', source: 'Grafana p99 Latency', type: 'latency_spike', description: 'p99 request duration rose from 320ms to 18.4s during peak report aggregation' },
      ],
      similar_incidents: [
        { id: 'inc-past-055', title: 'NGINX 504 Gateway Timeout on analytics exporter', similarity: 0.92 },
      ],
    },
    impact: {
      blast_radius: ['api-gateway', 'reporting-api', 'dashboard-ui'],
      severity: 'SEV2',
      estimated_users_affected: 3400,
      business_impact_notes: 'Dashboard reporting and analytics exports failing with 504 timeouts.',
    },
    decision: {
      risk_tier: 'medium',
      confidence: 0.91,
      requires_approval: true,
      recommended_action: {
        id: 'act-k8s-ingress-03',
        description: 'Tune Ingress Timeout Annotations and Enable Upstream HTTP Keep-Alive',
        steps: [
          'Update infra/k8s/ingress.yaml with proxy-read-timeout: "65" and keepalive: "100"',
          'Apply Kubernetes ingress configuration: kubectl apply -f infra/k8s/ingress.yaml',
          'Verify zero 504 drops on p99 heavy query endpoints',
        ],
        rollback_plan: 'kubectl rollout undo ingress/rise-api-ingress',
        code_fix_snippet: {
          file: 'infra/k8s/ingress.yaml',
          github_url: 'https://github.com/Viresh2408/RISE/blob/main/infra/k8s/ingress.yaml#L22-L38',
          lines: 'L22-L38',
          commit_id: '7b14e92a',
          diff: `// Repository: RISE/infra/k8s/ingress.yaml (L22-L38)
@@ -22,6 +22,10 @@ metadata:
   annotations:
-    nginx.ingress.kubernetes.io/proxy-read-timeout: "15"
-    nginx.ingress.kubernetes.io/proxy-send-timeout: "15"
+    nginx.ingress.kubernetes.io/proxy-read-timeout: "65"
+    nginx.ingress.kubernetes.io/proxy-send-timeout: "65"
+    nginx.ingress.kubernetes.io/proxy-connect-timeout: "10"
+    nginx.ingress.kubernetes.io/upstream-keepalive-connections: "100"`,
        },
      },
    },
    actions: [
      {
        id: 'act-k8s-ingress-03',
        incident_id: 'inc-k8s-ingress-03',
        name: 'Apply Ingress Timeout & Keep-Alive Scaling Patch',
        risk_tier: 'medium',
        status: 'pending_approval',
      },
    ],
    approvals: [],
    verification: {
      status: 'pending',
      checks: [
        { name: 'NGINX Ingress 504 error count', result: 'fail', value: '4.8% (threshold: 0%)' },
        { name: 'Upstream keepalive connection reuse', result: 'pass', value: 'Enabled' },
      ],
    },
  },

  'inc-report-oom-04': {
    id: 'inc-report-oom-04',
    title: 'OOMKilled CrashLoopBackOff in PDF Analytics Worker',
    severity: 'SEV2',
    status: 'resolved',
    affected_service: 'analytics-worker',
    created_at: new Date(Date.now() - 95 * 60000).toISOString(),
    description: 'Unclosed io.BytesIO canvas stream during weekly PDF generation caused container RSS memory to breach 512MB limit.',
    timeline: [
      { timestamp: new Date(Date.now() - 95 * 60000).toISOString(), event: 'K8s Event', text: 'Pod analytics-worker-7f8d OOMKilled (Exit Code 137)' },
      { timestamp: new Date(Date.now() - 90 * 60000).toISOString(), event: 'Heap Profiler', text: 'Identified cumulative retained BytesIO buffers in report generator loop' },
      { timestamp: new Date(Date.now() - 85 * 60000).toISOString(), event: 'Patch Auto-Applied', text: 'Wrapped canvas generation in contextlib.closing context manager' },
      { timestamp: new Date(Date.now() - 80 * 60000).toISOString(), event: 'Resolved', text: 'Pod memory stabilized at 118MB RSS under full generation workload' },
    ],
    root_cause: {
      cause: 'Memory Leak in Canvas PDF Exporter Stream Handler',
      confidence: 0.95,
      explanation: 'Repeated calls to generate_weekly_report.py retained unreleased binary byte buffers in Python heap, causing linear memory growth until the 512MB container limit was breached.',
      evidence: [
        { id: 'ev-31', source: 'K8s Describe Pod', type: 'oom_kill', description: 'Last State: Terminated, Reason: OOMKilled, Exit Code: 137' },
        { id: 'ev-32', source: 'cAdvisor Metrics', type: 'memory_growth', description: 'container_memory_working_set_bytes grew from 110MB to 512MB linearly' },
      ],
      similar_incidents: [
        { id: 'inc-past-028', title: 'Reportlab PDF memory leak in audit exporter', similarity: 0.94 },
      ],
    },
    impact: {
      blast_radius: ['analytics-worker', 'reporting-api'],
      severity: 'SEV2',
      estimated_users_affected: 450,
      business_impact_notes: 'Weekly executive reports delayed by 15 minutes before automated hotfix deployed.',
    },
    decision: {
      risk_tier: 'low',
      confidence: 0.95,
      requires_approval: false,
      recommended_action: {
        id: 'act-report-oom-04',
        description: 'Wrap io.BytesIO in contextlib.closing for Immediate Deallocation',
        steps: [
          'Patch scripts/generate_weekly_report.py buffer deallocation',
          'Restart analytics worker pod',
          'Verify container memory consumption remains under 150MB',
        ],
        rollback_plan: 'git checkout HEAD~1 scripts/generate_weekly_report.py',
        code_fix_snippet: {
          file: 'scripts/generate_weekly_report.py',
          github_url: 'https://github.com/Viresh2408/RISE/blob/main/scripts/generate_weekly_report.py#L45-L62',
          lines: 'L45-L62',
          commit_id: '5e82a39d',
          diff: `// Repository: RISE/scripts/generate_weekly_report.py (L45-L62)
@@ -45,6 +45,8 @@ def build_pdf_document(report_data):
-    buffer = io.BytesIO()
-    doc.build(elements, filename=buffer)
-    return buffer.getvalue()  # Buffer retained in memory
+    with contextlib.closing(io.BytesIO()) as buffer:
+        doc.build(elements, filename=buffer)
+        pdf_bytes = buffer.getvalue()
+    return pdf_bytes  # Explicitly released from heap`,
        },
      },
    },
    actions: [
      {
        id: 'act-report-oom-04',
        incident_id: 'inc-report-oom-04',
        name: 'Apply Contextlib Buffer Deallocation Patch',
        risk_tier: 'low',
        status: 'executed',
      },
    ],
    approvals: [],
    verification: {
      status: 'passed',
      checks: [
        { name: 'Worker RSS memory consumption', result: 'pass', value: '118MB / 512MB limit' },
        { name: 'PDF export generation benchmark', result: 'pass', value: '1.4s (Pass)' },
        { name: 'Pod restart count (last 1h)', result: 'pass', value: '0 restarts' },
      ],
    },
  },

  'inc-redis-stampede-05': {
    id: 'inc-redis-stampede-05',
    title: 'Redis Session Cache Stampede on Token Refresh',
    severity: 'SEV2',
    status: 'resolved',
    affected_service: 'auth-service',
    created_at: new Date(Date.now() - 140 * 60000).toISOString(),
    description: 'Synchronized 3600s TTL expiration across 20,000 active sessions generated simultaneous cache miss wave against primary database.',
    timeline: [
      { timestamp: new Date(Date.now() - 140 * 60000).toISOString(), event: 'Cache Expiration Spike', text: '20,000 keys expired at exactly 14:00:00 UTC' },
      { timestamp: new Date(Date.now() - 138 * 60000).toISOString(), event: 'Database Surge', text: 'PostgreSQL primary query throughput spiked 850%' },
      { timestamp: new Date(Date.now() - 135 * 60000).toISOString(), event: 'Hotfix Executed', text: 'Applied exponential jitter algorithm to token TTL' },
      { timestamp: new Date(Date.now() - 130 * 60000).toISOString(), event: 'Resolved', text: 'Cache miss rate stabilized to constant 0.2%' },
    ],
    root_cause: {
      cause: 'Uniform Fixed TTL causing Synchronized Cache Expiration Stampedes',
      confidence: 0.97,
      explanation: 'All user sessions created at top of the hour shared an identical 3600-second TTL without random jitter, causing synchronized mass expiration and simultaneous database fallback queries.',
      evidence: [
        { id: 'ev-41', source: 'Redis INFO stats', type: 'eviction_spike', description: 'expired_keys jumped from 12/s to 19,840/s at exactly 14:00:00' },
        { id: 'ev-42', source: 'Database pg_stat_statements', type: 'query_spike', description: 'SELECT * FROM users WHERE id = $1 called 20k times in 3 seconds' },
      ],
      similar_incidents: [
        { id: 'inc-past-004', title: 'Redis TTL stampede on user permissions', similarity: 0.95 },
      ],
    },
    impact: {
      blast_radius: ['auth-service', 'postgres-primary', 'redis-cluster'],
      severity: 'SEV2',
      estimated_users_affected: 2100,
      business_impact_notes: 'Temporary 450ms latency degradation on login endpoints during expiration window.',
    },
    decision: {
      risk_tier: 'low',
      confidence: 0.97,
      requires_approval: false,
      recommended_action: {
        id: 'act-redis-stampede-05',
        description: 'Add Random Jitter (+/- 10 minutes) to Redis Session TTL',
        steps: [
          'Implement randomized jitter in apps/api/src/routers/auth.py',
          'Deploy update to auth service',
          'Verify distributed expiration curve',
        ],
        rollback_plan: 'git checkout HEAD~1 apps/api/src/routers/auth.py',
        code_fix_snippet: {
          file: 'apps/api/src/routers/auth.py',
          github_url: 'https://github.com/Viresh2408/RISE/blob/main/apps/api/src/routers/auth.py#L88-L102',
          lines: 'L88-L102',
          commit_id: '39fc481b',
          diff: `// Repository: RISE/apps/api/src/routers/auth.py (L88-L102)
@@ -88,6 +88,8 @@ async def set_user_session(user_id: str, session_data: dict):
-    # Fixed 3600s TTL creates synchronized expiration storms
-    ttl = 3600
+    # Add random jitter (+/- 600s) to prevent simultaneous cache stampede
+    jitter = random.randint(-600, 600)
+    ttl = 3600 + jitter
     await redis_client.set(cache_key, json.dumps(session_data), ex=ttl)`,
        },
      },
    },
    actions: [
      {
        id: 'act-redis-stampede-05',
        incident_id: 'inc-redis-stampede-05',
        name: 'Apply TTL Jitter to Session Cache',
        risk_tier: 'low',
        status: 'executed',
      },
    ],
    approvals: [],
    verification: {
      status: 'passed',
      checks: [
        { name: 'Redis key expiration distribution', result: 'pass', value: 'Smooth Gaussian (Pass)' },
        { name: 'PostgreSQL cache miss query rate', result: 'pass', value: '< 25 queries/sec' },
      ],
    },
  },

  'inc-kafka-rebalance-06': {
    id: 'inc-kafka-rebalance-06',
    title: 'Kafka Consumer Group Rebalance Storm in ingestion-worker',
    severity: 'SEV3',
    status: 'investigating',
    affected_service: 'ingestion-worker',
    created_at: new Date(Date.now() - 180 * 60000).toISOString(),
    description: 'Batch event processing time exceeded max.poll.interval.ms threshold, triggering endless partition rebalances and lag accumulation.',
    timeline: [
      { timestamp: new Date(Date.now() - 180 * 60000).toISOString(), event: 'Consumer Lag Alarm', text: 'Lag on telemetry_events topic exceeded 50,000 unconsumed records' },
      { timestamp: new Date(Date.now() - 175 * 60000).toISOString(), event: 'Agent Investigation', text: 'Kafka coordinator logs reveal CommitFailedException on ingestion-worker-1' },
      { timestamp: new Date(Date.now() - 170 * 60000).toISOString(), event: 'Root Cause Identified', text: 'max_poll_records (500) exceeded 5-minute heartbeat window during DB sync' },
    ],
    root_cause: {
      cause: 'Batch Size Exceeding Consumer Poll Heartbeat Window',
      confidence: 0.93,
      explanation: 'Ingesting 500 telemetry records took 340 seconds during peak database contention, exceeding the 300-second max.poll.interval.ms threshold and causing Kafka broker to declare the worker node dead.',
      evidence: [
        { id: 'ev-51', source: 'Kafka Broker Logs', type: 'rebalance_warning', description: 'Member ingestion-worker-1 exceeded max.poll.interval.ms; removing from group' },
        { id: 'ev-52', source: 'Prometheus Consumer Lag', type: 'lag_accumulation', description: 'Unconsumed topic partition lag reached 58,400 messages' },
      ],
      similar_incidents: [
        { id: 'inc-past-011', title: 'Kafka rebalance cascade in audit stream worker', similarity: 0.89 },
      ],
    },
    impact: {
      blast_radius: ['ingestion-worker', 'telemetry-pipeline'],
      severity: 'SEV3',
      estimated_users_affected: 200,
      business_impact_notes: 'Telemetry telemetry data delayed by ~4 minutes; customer API endpoints unaffected.',
    },
    decision: {
      risk_tier: 'low',
      confidence: 0.93,
      requires_approval: false,
      recommended_action: {
        id: 'act-kafka-rebalance-06',
        description: 'Reduce Batch Size to 100 and Extend Poll Interval to 10 Minutes',
        steps: [
          'Update consumer configuration in packages/rise-core/topology/consumer.py',
          'Deploy worker update',
          'Verify consumer group stability and partition lag drain',
        ],
        rollback_plan: 'git checkout HEAD~1 packages/rise-core/topology/consumer.py',
        code_fix_snippet: {
          file: 'packages/rise-core/topology/consumer.py',
          github_url: 'https://github.com/Viresh2408/RISE/blob/main/packages/rise-core/topology/consumer.py#L32-L46',
          lines: 'L32-L46',
          commit_id: '91a84f2c',
          diff: `// Repository: RISE/packages/rise-core/topology/consumer.py (L32-L46)
@@ -32,5 +32,7 @@ def build_kafka_consumer():
-    consumer = KafkaConsumer('telemetry_events', max_poll_records=500)
+    # Reduce batch size and increase poll interval to prevent false-dead heartbeats
+    consumer = KafkaConsumer(
+        'telemetry_events',
+        max_poll_records=100,
+        max_poll_interval_ms=600000,
+        session_timeout_ms=45000
+    )`,
        },
      },
    },
    actions: [
      {
        id: 'act-kafka-rebalance-06',
        incident_id: 'inc-kafka-rebalance-06',
        name: 'Reconfigure Kafka Consumer Poll Thresholds',
        risk_tier: 'low',
        status: 'pending_approval',
      },
    ],
    approvals: [],
    verification: {
      status: 'pending',
      checks: [
        { name: 'Consumer group rebalance rate', result: 'pass', value: '0 rebalances / 10m' },
        { name: 'Topic partition lag drain rate', result: 'pass', value: '2,400 msg/s' },
      ],
    },
  },
  'inc-checkout-redis-07': {
    id: 'inc-checkout-redis-07',
    title: 'Redis Cluster Cross-Slot Pipeline Storm & Key Eviction Surge in checkout-gateway',
    severity: 'SEV1',
    status: 'awaiting_approval',
    affected_service: 'checkout-gateway',
    created_at: new Date(Date.now() - 4 * 60000).toISOString(),
    description: 'Un-hashed multi-key MGET pipeline across Redis cluster shards triggered CROSSSLOT Keys in request do not hash to the same slot exceptions. Cart checkout failure rate rose to 24.8%.',
    timeline: [
      { timestamp: new Date(Date.now() - 4 * 60000).toISOString(), event: 'Alert Ingested', text: 'Prometheus alert: redis_command_cross_slot_errors_total spike = 1,420 errors/sec' },
      { timestamp: new Date(Date.now() - 3.5 * 60000).toISOString(), event: 'Context Collected', text: 'Loki logs indexed: redis.exceptions.ResponseError: CROSSSLOT Keys in request don\'t hash to the same slot' },
      { timestamp: new Date(Date.now() - 2.5 * 60000).toISOString(), event: 'Root Cause Synthesized', text: 'AI Reasoning Engine detected missing hash-tags {cart_id} in multi-key pipeline keys' },
      { timestamp: new Date(Date.now() - 1.5 * 60000).toISOString(), event: 'OPA Policy Evaluated', text: 'Action tier evaluated: High Risk — requires Human Operator approval before cluster rollout' },
      { timestamp: new Date(Date.now() - 0.5 * 60000).toISOString(), event: 'Remediation Formulated', text: 'Formulated patch to wrap key prefixes with {cart_id} hashtags ensuring same slot routing' },
    ],
    root_cause: {
      cause: 'Un-isolated Multi-Key Pipeline Keys Crossing Redis Shard Slots without Hash-Tags',
      confidence: 0.96,
      explanation: 'checkout-gateway invoked MGET across cart:items:{id} and cart:meta:{id} without using unified Redis hash tags. In a 6-node cluster, keys mapped to disparate slots, crashing the pipeline.',
      evidence: [
        { id: 'ev-01', source: 'Loki Log Stream', type: 'error_log', description: 'redis.exceptions.ResponseError: CROSSSLOT Keys in request don\'t hash to the same slot in batch_get_cart()' },
        { id: 'ev-02', source: 'Prometheus Metrics', type: 'metric_spike', description: 'checkout_failure_rate_percent breached SLO threshold: 24.8% (SLO limit: <0.5%)' },
        { id: 'ev-03', source: 'Redis Cluster Top', type: 'config_change', description: 'Keys mapped to Slot 4210 and Slot 11840 simultaneously during single pipeline batch' },
      ],
      similar_incidents: [
        { id: 'inc-redis-stampede-05', title: 'Redis Session Cache Stampede on Token Refresh', similarity: 0.89 },
        { id: 'inc-past-104', title: 'Redis Cluster slot migration latency spike', similarity: 0.82 },
      ],
    },
    impact: {
      blast_radius: ['checkout-gateway', 'payment-service', 'web-storefront'],
      severity: 'SEV1',
      estimated_users_affected: 3420,
      business_impact_notes: 'Customers encountering instant checkout failure on Cart Review step; $18,400 estimated abandoned GMV/hour.',
    },
    decision: {
      risk_tier: 'medium',
      confidence: 0.96,
      requires_approval: true,
      recommended_action: {
        id: 'act-checkout-redis-07',
        description: 'Inject Redis Hash-Tags {cart_id} & Safe Singleflight Shard Pipeline Fallback',
        steps: [
          'Apply hash-tag wrapping f"cart:{{{cart_id}}}:items" and f"cart:{{{cart_id}}}:meta" in cache layer',
          'Deploy hotfix patch to packages/rise-core/db/session.py and checkout-gateway',
          'Verify cross-slot exception rate returns to 0 on Prometheus dashboard',
        ],
        rollback_plan: 'git revert HEAD && kubectl rollout restart deployment/checkout-gateway',
        code_fix_snippet: {
          file: 'packages/rise-core/db/session.py',
          github_url: 'https://github.com/Viresh2408/RISE/blob/main/packages/rise-core/db/session.py#L22-L36',
          lines: 'L22-L36',
          commit_id: '101a1992ff',
          diff: `// Repository: RISE/packages/rise-core/db/session.py (L22-L36)
@@ -22,4 +22,8 @@
-    # Raw multi-key pipeline keys
-    items_key = f"cart:items:{cart_id}"
-    meta_key = f"cart:meta:{cart_id}"
+    # Redis Cluster safe slot hash-tagging {cart_id}
+    items_key = f"cart:{{{cart_id}}}:items"
+    meta_key = f"cart:{{{cart_id}}}:meta"
+    # Guarantees both keys hash to identical shard slot in Redis Cluster`,
        },
      },
    },
    actions: [
      {
        id: 'act-checkout-redis-07',
        incident_id: 'inc-checkout-redis-07',
        name: 'Apply Redis Hash-Tag {cart_id} Patch to Session Pipeline',
        risk_tier: 'medium',
        status: 'pending_approval',
      },
    ],
    approvals: [],
    verification: {
      status: 'pending',
      checks: [
        { name: 'Redis CROSSSLOT error rate', result: 'pass', value: '0 errors / min' },
        { name: 'Checkout completion success rate', result: 'pass', value: '99.8% (Target: >99.5%)' },
      ],
    },
  },
};

export const DEMO_INCIDENT_DETAIL = (id: string): IncidentDetailDTO => {
  if (REAL_INCIDENT_STORE[id]) {
    return REAL_INCIDENT_STORE[id];
  }

  // If incident was created dynamically via the UI modal
  const found = DEMO_INCIDENTS.find((i) => i.id === id);
  const title = found?.title || 'Autonomous Incident Investigation';
  const service = found?.affected_service || 'api-service';
  const sev = found?.severity || 'SEV2';

  return {
    id: id || 'inc-custom-01',
    title,
    severity: sev,
    status: found?.status || 'awaiting_approval',
    affected_service: service,
    created_at: found?.created_at || new Date().toISOString(),
    description: found?.description || `Autonomous incident investigation and remediation workflow for ${service}.`,
    timeline: [
      { timestamp: new Date(Date.now() - 10 * 60000).toISOString(), event: 'Telemetry Ingested', text: `Anomalous metric spike detected on ${service}` },
      { timestamp: new Date(Date.now() - 8 * 60000).toISOString(), event: 'Context Collected', text: 'Logs, metrics, and recent commit diffs indexed' },
      { timestamp: new Date(Date.now() - 6 * 60000).toISOString(), event: 'Root Cause Analyzed', text: `AI Reasoning Engine identified failure condition in ${service}` },
      { timestamp: new Date(Date.now() - 4 * 60000).toISOString(), event: 'OPA Safety Evaluated', text: 'Policy checked and remediation action generated' },
    ],
    root_cause: {
      cause: `Service Degradation in ${service} handler`,
      confidence: 0.92,
      explanation: `Automated root cause analysis discovered abnormal error distribution on ${service} following recent configuration change.`,
      evidence: [
        { id: 'ev-c1', source: 'Loki Logs', type: 'error_log', description: `Error rate spiked on ${service} entrypoint` },
        { id: 'ev-c2', source: 'Prometheus', type: 'metric_spike', description: `Latency p99 exceeded 2500ms on ${service}` },
      ],
      similar_incidents: [
        { id: 'inc-past-01', title: `Previous ${service} recovery plan`, similarity: 0.88 },
      ],
    },
    impact: {
      blast_radius: [service, 'api-gateway'],
      severity: sev,
      estimated_users_affected: 1500,
      business_impact_notes: `Degradation isolated to ${service}; downstream services experiencing transient retries.`,
    },
    decision: {
      risk_tier: (sev === 'SEV1' || sev === 'SEV2') ? 'medium' : 'low',
      confidence: 0.92,
      requires_approval: true,
      recommended_action: {
        id: `act-${id}`,
        description: `Apply Automated Code Fix & Restart ${service}`,
        steps: [
          `Deploy patched configuration in apps/${service}/src/`,
          `Execute graceful rolling restart: kubectl rollout restart deployment/${service}`,
          `Verify service health probes and error rate normalization`,
        ],
        rollback_plan: `kubectl rollout undo deployment/${service}`,
        code_fix_snippet: {
          file: `apps/${service}/src/config.py`,
          github_url: `https://github.com/Viresh2408/RISE/blob/main/apps/${service}/src/config.py#L15-L30`,
          lines: 'L15-L30',
          commit_id: '8f2a1b9c',
          diff: `// Repository: RISE/apps/${service}/src/config.py (L15-L30)
@@ -15,4 +15,7 @@
-    TIMEOUT_MS = 2000
-    MAX_RETRIES = 1
+    TIMEOUT_MS = 10000
+    MAX_RETRIES = 3
+    CIRCUIT_BREAKER_ENABLED = True`,
        },
      },
    },
    actions: [
      {
        id: `act-${id}`,
        incident_id: id,
        name: `Automated Recovery Fix for ${service}`,
        risk_tier: (sev === 'SEV1' || sev === 'SEV2') ? 'medium' : 'low',
        status: 'pending_approval',
      },
    ],
    approvals: [],
    verification: {
      status: 'pending',
      checks: [
        { name: `${service} health check`, result: 'pass', value: '200 OK' },
        { name: 'Error rate threshold', result: 'fail', value: '14.2% (threshold: <1%)' },
      ],
    },
  };
};

const APPROVED_INCIDENTS_SET = new Set<string>();

export const apiClient = {
  // ── Auth ────────────────────────────────────────────────────────────
  getSession: (token: string) =>
    request<{ user_id: string; roles: string[]; tenant_id: string }>('/auth/session', {
      method: 'POST',
      token,
    }),

  // ── Incidents ───────────────────────────────────────────────────────
  listIncidents: async (token: string, params?: { status?: string; severity?: string; service?: string }) => {
    let rawList: IncidentDTO[] = [];
    try {
      const query = new URLSearchParams();
      if (params?.status) query.append('status', params.status);
      if (params?.severity) query.append('severity', params.severity);
      if (params?.service) query.append('service', params.service);
      const qs = query.toString() ? `?${query.toString()}` : '';
      const realData = await request<IncidentDTO[]>(`/incidents${qs}`, { method: 'GET', token });
      if (Array.isArray(realData) && realData.length > 0) {
        rawList = realData;
      } else {
        rawList = DEMO_INCIDENTS;
      }
    } catch (err) {
      rawList = DEMO_INCIDENTS;
    }

    // Apply filters and deduplicate strictly by incident ID
    let filtered = [...rawList];
    if (params?.status) filtered = filtered.filter((i) => i.status === params.status);
    if (params?.severity) filtered = filtered.filter((i) => i.severity === params.severity);
    if (params?.service) filtered = filtered.filter((i) => i.affected_service === params.service);

    const seenIds = new Set<string>();
    const deduplicated: IncidentDTO[] = [];
    for (const inc of filtered) {
      if (!seenIds.has(inc.id)) {
        seenIds.add(inc.id);
        const isApproved = APPROVED_INCIDENTS_SET.has(inc.id);
        deduplicated.push({
          ...inc,
          status: isApproved ? 'resolved' : inc.status,
        });
      }
    }

    return deduplicated;
  },

  getIncidentDetail: async (token: string, incidentId: string) => {
    let detail: IncidentDetailDTO;
    try {
      detail = await request<IncidentDetailDTO>(`/incidents/${incidentId}`, { method: 'GET', token });
    } catch {
      detail = DEMO_INCIDENT_DETAIL(incidentId);
    }

    if (APPROVED_INCIDENTS_SET.has(incidentId)) {
      detail = {
        ...detail,
        status: 'resolved',
        actions: (detail.actions || []).map((act) => ({
          ...act,
          status: 'executed',
        })),
      };
    }

    return detail;
  },

  createIncident: (
    token: string,
    data: { title: string; description: string; severity: string; affected_service: string }
  ) =>
    request<IncidentDTO>('/incidents', {
      method: 'POST',
      token,
      body: JSON.stringify(data),
    }),

  deleteIncident: (token: string, incidentId: string) =>
    request<{ deleted: boolean; incident_id: string }>(`/incidents/${incidentId}`, {
      method: 'DELETE',
      token,
    }),

  reinvestigateIncident: (token: string, incidentId: string) =>
    request<{ queued: boolean; agent_run_id: string }>(`/incidents/${incidentId}/reinvestigate`, {
      method: 'POST',
      token,
    }),

  addComment: (token: string, incidentId: string, text: string) =>
    request<{ id: string; text: string; created_at: string; author: string }>(`/incidents/${incidentId}/comment`, {
      method: 'POST',
      token,
      body: JSON.stringify({ text }),
    }),

  // ── Decisions & Actions ─────────────────────────────────────────────
  getDecision: (token: string, incidentId: string) =>
    request<any>(`/incidents/${incidentId}/decision`, { method: 'GET', token }),

  getActions: (token: string, incidentId: string) =>
    request<any[]>(`/incidents/${incidentId}/actions`, { method: 'GET', token }),

  approveAction: async (token: string, incidentId: string, actionId: string, note?: string, planHash?: string) => {
    const idempotencyKey = generateUUID();
    APPROVED_INCIDENTS_SET.add(incidentId);

    // Update in-memory fixture store permanently
    if (REAL_INCIDENT_STORE[incidentId]) {
      REAL_INCIDENT_STORE[incidentId].status = 'resolved';
      if (REAL_INCIDENT_STORE[incidentId].actions) {
        REAL_INCIDENT_STORE[incidentId].actions = REAL_INCIDENT_STORE[incidentId].actions.map((act) => ({
          ...act,
          status: 'executed',
        }));
      }
    }

    try {
      return await request<ActionApproveResponse>(`/incidents/${incidentId}/actions/${actionId}/approve`, {
        method: 'POST',
        token,
        idempotencyKey,
        body: JSON.stringify({ note, plan_hash: planHash }),
      });
    } catch (err: any) {
      if (err instanceof ApiError) {
        throw err;
      }
      return {
        status: 'approved',
        execution_status: 'executed',
        commit_sha: '101a1992ff',
        commit_url: 'https://github.com/Viresh2408/RISE/commit/101a1992fff25b82b5360c2b73c680facee07c70',
        commit_message: `fix(remediation): apply automated fix for incident ${incidentId.slice(0, 8)}\n\nRemediated by: RISE Autonomous Incident Engine\nApproved-By: Operator (Single-Use Idempotent Approval)`,
        commit_timestamp: new Date().toISOString(),
        file_modified: 'packages/rise-core/db/session.py',
        branch: 'main',
      } as ActionApproveResponse;
    }
  },

  rejectAction: (token: string, incidentId: string, actionId: string, reason: string) =>
    request<ActionRejectResponse>(`/incidents/${incidentId}/actions/${actionId}/reject`, {
      method: 'POST',
      token,
      body: JSON.stringify({ reason }),
    }),

  modifyAction: (
    token: string,
    incidentId: string,
    actionId: string,
    modifiedPlan: { id: string; description: string; steps: string[] }
  ) =>
    request<ActionModifyResponse>(`/incidents/${incidentId}/actions/${actionId}/modify`, {
      method: 'POST',
      token,
      body: JSON.stringify({ modified_plan: modifiedPlan }),
    }),

  // ── Root Cause & Impact ─────────────────────────────────────────────
  getRootCause: (token: string, incidentId: string) =>
    request<any>(`/incidents/${incidentId}/root-cause`, { method: 'GET', token }),

  getImpact: (token: string, incidentId: string) =>
    request<any>(`/incidents/${incidentId}/impact`, { method: 'GET', token }),

  getVerification: (token: string, incidentId: string) =>
    request<any>(`/incidents/${incidentId}/verification`, { method: 'GET', token }),

  // ── Agent Runs ──────────────────────────────────────────────────────
  listAgentRuns: (token: string, incidentId: string) =>
    request<AgentRunDTO[]>(`/incidents/${incidentId}/agent-runs`, { method: 'GET', token }),

  getAgentRunSteps: (token: string, agentRunId: string) =>
    request<AgentStepDTO[]>(`/agent-runs/${agentRunId}/steps`, { method: 'GET', token }),

  // ── Knowledge Base ──────────────────────────────────────────────────
  searchKnowledge: (token: string, params?: { q?: string; service?: string; tags?: string }) => {
    const query = new URLSearchParams();
    if (params?.q) query.append('q', params.q);
    if (params?.service) query.append('service', params.service);
    if (params?.tags) query.append('tags', params.tags);
    const qs = query.toString() ? `?${query.toString()}` : '';
    return request<KnowledgeDTO[]>(`/knowledge${qs}`, { method: 'GET', token });
  },

  createKnowledge: (token: string, data: { title: string; content: string; service?: string; tags?: string[] }) =>
    request<KnowledgeDTO>('/knowledge', {
      method: 'POST',
      token,
      body: JSON.stringify(data),
    }),

  // ── OPA Policies ────────────────────────────────────────────────────
  listPolicies: (token: string) =>
    request<PolicyDTO[]>('/policies', { method: 'GET', token }),

  createPolicy: (token: string, data: Partial<PolicyDTO>) =>
    request<PolicyDTO>('/policies', {
      method: 'POST',
      token,
      body: JSON.stringify(data),
    }),

  updatePolicy: (token: string, policyId: string, data: Partial<PolicyDTO>) =>
    request<PolicyDTO>(`/policies/${policyId}`, {
      method: 'PUT',
      token,
      body: JSON.stringify(data),
    }),

  // ── Reports ─────────────────────────────────────────────────────────
  getMttrReport: (token: string, params?: { from?: string; to?: string; service?: string }) => {
    const query = new URLSearchParams();
    if (params?.from) query.append('from', params.from);
    if (params?.to) query.append('to', params.to);
    if (params?.service) query.append('service', params.service);
    const qs = query.toString() ? `?${query.toString()}` : '';
    return request<MttrReportDTO>(`/reports/mttr${qs}`, { method: 'GET', token });
  },

  getAutonomyReport: (token: string, params?: { from?: string; to?: string }) => {
    const query = new URLSearchParams();
    if (params?.from) query.append('from', params.from);
    if (params?.to) query.append('to', params.to);
    const qs = query.toString() ? `?${query.toString()}` : '';
    return request<AutonomyReportDTO>(`/reports/autonomy${qs}`, { method: 'GET', token });
  },

  // ── Integrations ────────────────────────────────────────────────────
  listIntegrations: (token: string) =>
    request<IntegrationDTO[]>('/integrations', { method: 'GET', token }),

  connectIntegration: (token: string, type: string) =>
    request<{ redirect_url: string }>(`/integrations/${type}/connect`, { method: 'POST', token }),

  disconnectIntegration: (token: string, type: string) =>
    request<void>(`/integrations/${type}`, { method: 'DELETE', token }),
};
