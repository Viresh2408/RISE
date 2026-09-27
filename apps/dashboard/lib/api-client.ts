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

export const apiClient = {
  // ── Auth ────────────────────────────────────────────────────────────
  getSession: (token: string) =>
    request<{ user_id: string; roles: string[]; tenant_id: string }>('/auth/session', {
      method: 'POST',
      token,
    }),

  // ── Incidents ───────────────────────────────────────────────────────
  listIncidents: async (token: string, params?: { status?: string; severity?: string; service?: string }) => {
    const query = new URLSearchParams();
    if (params?.status) query.append('status', params.status);
    if (params?.severity) query.append('severity', params.severity);
    if (params?.service) query.append('service', params.service);
    const qs = query.toString() ? `?${query.toString()}` : '';

    // Backend is the sole source of truth. Any error propagates so the UI can render a
    // real "cannot connect to API" state; an empty result renders a real empty state.
    // No hardcoded DEMO_INCIDENTS fallback and no client-side status fabrication.
    const realData = await request<IncidentDTO[]>(`/incidents${qs}`, { method: 'GET', token });
    const rawList = Array.isArray(realData) ? realData : [];

    const seenIds = new Set<string>();
    const deduplicated: IncidentDTO[] = [];
    for (const inc of rawList) {
      if (!seenIds.has(inc.id)) {
        seenIds.add(inc.id);
        deduplicated.push(inc);
      }
    }

    return deduplicated;
  },

  getIncidentDetail: async (token: string, incidentId: string) => {
    // Backend is the sole source of truth; on failure the error propagates so the UI
    // can surface a real error state instead of a fabricated DEMO_INCIDENT_DETAIL.
    return request<IncidentDetailDTO>(`/incidents/${incidentId}`, { method: 'GET', token });
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

    // No client-side fabrication: return exactly what the backend confirms. If the
    // backend is unreachable or returns an error, that error propagates so the UI can
    // surface a real failure state — never a fabricated "approved" / commit_sha success.
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

  // ── GitHub File Preview ──────────────────────────────────────────────
  /**
   * Fetch the live GitHub file status for a monitor-detected bug pattern.
   * READ-ONLY — nothing is written to GitHub.
   */
  getGithubFilePreview: (token: string, filePath: string, patternId?: string | null) => {
    const query = new URLSearchParams({ file_path: filePath });
    if (patternId) query.append('pattern_id', patternId);
    return request<{
      file_path: string;
      github_url: string;
      file_sha: string | null;
      ref: string;
      is_bug_present: boolean | null;
      is_fixed: boolean | null;
      pattern_id: string | null;
      pattern_title: string | null;
      pattern_description: string | null;
      current_content_snippet: string | null;
      proposed_diff: string | null;
      error?: string;
    }>(`/github/file-preview?${query.toString()}`, { method: 'GET', token });
  },
};
