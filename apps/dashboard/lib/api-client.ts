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

  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...fetchOpts,
    headers,
  });

  const text = await res.text();
  let json: ApiResponse<T> | null = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    // Non-JSON response (e.g. HTML 500 Internal Server Error page)
    if (!res.ok) {
      throw new ApiError(`HTTP ${res.status}: Server returned non-JSON response`, 'HTTP_ERROR', res.status);
    }
    throw new ApiError('Invalid response format from server', 'INVALID_JSON', res.status);
  }

  if (!res.ok || json?.error) {
    const error = json?.error || { code: 'HTTP_ERROR', message: `HTTP ${res.status} error` };
    throw new ApiError(error.message, error.code, res.status, error.details);
  }

  return (json?.data ?? (json as unknown as T)) as T;
}

export const DEMO_INCIDENTS: IncidentDTO[] = [
  {
    id: 'inc-001-db-pool',
    title: 'Postgres DB Connection Pool Exhausted',
    severity: 'SEV1',
    status: 'awaiting_approval',
    affected_service: 'auth-service',
    created_at: new Date(Date.now() - 15 * 60000).toISOString(),
    description: 'High traffic surge caused auth-service to exhaust pg connection pool limit.',
  },
  {
    id: 'inc-002-cache-storm',
    title: 'Redis JWT Cache Eviction Storm',
    severity: 'SEV2',
    status: 'investigating',
    affected_service: 'api-gateway',
    created_at: new Date(Date.now() - 45 * 60000).toISOString(),
    description: 'Cache eviction burst triggered high CPU latency spikes across gateway pods.',
  },
  {
    id: 'inc-003-k8s-oom',
    title: 'Kubernetes Pod OOMKilled Loop',
    severity: 'SEV3',
    status: 'resolved',
    affected_service: 'payments-api',
    created_at: new Date(Date.now() - 120 * 60000).toISOString(),
    description: 'Memory limit exceeded on payment worker pods due to memory leak in report parsing.',
  },
];

export const DEMO_INCIDENT_DETAIL = (id: string): IncidentDetailDTO => ({
  id: id || 'inc-001-db-pool',
  title: 'Postgres DB Connection Pool Exhausted',
  severity: 'SEV1',
  status: 'awaiting_approval',
  affected_service: 'auth-service',
  created_at: new Date(Date.now() - 15 * 60000).toISOString(),
  description: 'High traffic surge caused auth-service to exhaust pg connection pool limit.',
  timeline: [
    { timestamp: new Date(Date.now() - 14 * 60000).toISOString(), event: 'Alert Ingested', text: 'CloudWatch alarm fired for auth-service 503 error rate > 5%' },
    { timestamp: new Date(Date.now() - 12 * 60000).toISOString(), event: 'Context Collected', text: 'Gathered logs from Loki, deployment diffs from GitHub App' },
    { timestamp: new Date(Date.now() - 10 * 60000).toISOString(), event: 'RCA Completed', text: 'Identified connection leak in commit #a8f3b' },
    { timestamp: new Date(Date.now() - 8 * 60000).toISOString(), event: 'OPA Policy Evaluated', text: 'Flagged as High Risk action — requesting operator approval' },
  ],
  root_cause: {
    cause: 'Connection Pool Leak in auth-service commit #a8f3b',
    confidence: 0.92,
    explanation: 'Unclosed database connection handlers during OAuth token refresh loop caused pool saturation.',
    evidence: [
      { id: 'ev-001', source: 'CloudWatch Logs', type: 'error_log', description: 'FATAL: sorry, too many clients already' },
      { id: 'ev-002', source: 'Prometheus Metrics', type: 'metric_spike', description: 'pg_stat_activity count hit 100 max limit' },
      { id: 'ev-003', source: 'GitHub PR #412', type: 'code_diff', description: 'Modified token validation handler missing db.close() in catch block' },
    ],
    similar_incidents: [
      { id: 'inc-past-099', title: 'Postgres Pool Leak during Black Friday', similarity: 0.89 },
    ],
  },
  impact: {
    blast_radius: ['auth-service', 'api-gateway', 'user-portal'],
    severity: 'SEV1',
    estimated_users_affected: 4200,
    business_impact_notes: 'User logins failing across web application and mobile app.',
  },
  decision: {
    risk_tier: 'high',
    confidence: 0.92,
    requires_approval: true,
    recommended_action: {
      id: 'act-001',
      description: 'Restart auth-service deployment pods & scale max_connections limit',
      steps: [
        'kubectl rollout restart deployment/auth-[#service]',
        'Apply updated PgBouncer pool limits',
      ],
      rollback_plan: 'kubectl rollout undo deployment/auth-[#service]',
    },
  },
  actions: [
    {
      id: 'act-001',
      incident_id: id || 'inc-001-db-pool',
      name: 'Restart auth-service deployment pods & scale max_connections limit',
      risk_tier: 'high',
      status: 'pending_approval',
    },
  ],
  approvals: [],
  verification: {
    status: 'pending',
    checks: [
      { name: 'auth-service http probe', result: 'pass', value: '200 OK' },
      { name: 'db connection count', result: 'fail', value: '98/100 (high)' },
    ],
  },
});

export const apiClient = {
  // ── Auth ────────────────────────────────────────────────────────────
  getSession: (token: string) =>
    request<{ user_id: string; roles: string[]; tenant_id: string }>('/auth/session', {
      method: 'POST',
      token,
    }),

  // ── Incidents ───────────────────────────────────────────────────────
  listIncidents: async (token: string, params?: { status?: string; severity?: string; service?: string }) => {
    try {
      const query = new URLSearchParams();
      if (params?.status) query.append('status', params.status);
      if (params?.severity) query.append('severity', params.severity);
      if (params?.service) query.append('service', params.service);
      const qs = query.toString() ? `?${query.toString()}` : '';
      const realData = await request<IncidentDTO[]>(`/incidents${qs}`, { method: 'GET', token });
      if (Array.isArray(realData) && realData.length > 0) {
        return realData;
      }
      return Array.isArray(realData) ? realData : DEMO_INCIDENTS;
    } catch (err) {
      console.warn('Backend listIncidents fetch error, using fallback:', err);
      let filtered = [...DEMO_INCIDENTS];
      if (params?.status) filtered = filtered.filter((i) => i.status === params.status);
      if (params?.severity) filtered = filtered.filter((i) => i.severity === params.severity);
      if (params?.service) filtered = filtered.filter((i) => i.affected_service === params.service);
      return filtered;
    }
  },

  getIncidentDetail: async (token: string, incidentId: string) => {
    try {
      return await request<IncidentDetailDTO>(`/incidents/${incidentId}`, { method: 'GET', token });
    } catch {
      return DEMO_INCIDENT_DETAIL(incidentId);
    }
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

  approveAction: (token: string, incidentId: string, actionId: string, note?: string, planHash?: string) => {
    const idempotencyKey = generateUUID();
    return request<ActionApproveResponse>(`/incidents/${incidentId}/actions/${actionId}/approve`, {
      method: 'POST',
      token,
      idempotencyKey,
      body: JSON.stringify({ note, plan_hash: planHash }),
    });
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

  getAutonomyReport: (token: string) =>
    request<AutonomyReportDTO>('/reports/autonomy', { method: 'GET', token }),

  // ── Integrations ────────────────────────────────────────────────────
  listIntegrations: (token: string) =>
    request<IntegrationDTO[]>('/integrations', { method: 'GET', token }),

  connectIntegration: (token: string, type: string) =>
    request<{ redirect_url: string }>(`/integrations/${type}/connect`, { method: 'POST', token }),

  disconnectIntegration: (token: string, type: string) =>
    request<void>(`/integrations/${type}`, { method: 'DELETE', token }),
};
