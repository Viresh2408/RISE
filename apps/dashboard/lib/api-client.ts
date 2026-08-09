import { ApiResponse, ActionApproveResponse, ActionModifyResponse, ActionRejectResponse, IncidentDTO, IncidentDetailDTO } from './types';

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

  const json = (await res.json()) as ApiResponse<T>;

  if (!res.ok || json.error) {
    const error = json.error || { code: 'HTTP_ERROR', message: `HTTP ${res.status} error` };
    throw new ApiError(error.message, error.code, res.status, error.details);
  }

  return json.data as T;
}

export const apiClient = {
  // Auth Session
  getSession: (token: string) =>
    request<{ user_id: string; roles: string[]; tenant_id: string }>('/auth/session', {
      method: 'POST',
      token,
    }),

  // Incidents List
  listIncidents: (token: string, params?: { status?: string; severity?: string; service?: string }) => {
    const query = new URLSearchParams();
    if (params?.status) query.append('status', params.status);
    if (params?.severity) query.append('severity', params.severity);
    if (params?.service) query.append('service', params.service);
    const queryString = query.toString() ? `?${query.toString()}` : '';
    return request<IncidentDTO[]>(`/incidents${queryString}`, { method: 'GET', token });
  },

  // Incident Detail
  getIncidentDetail: (token: string, incidentId: string) =>
    request<IncidentDetailDTO>(`/incidents/${incidentId}`, { method: 'GET', token }),

  // Create Incident
  createIncident: (
    token: string,
    data: { title: string; description: string; severity: string; affected_service: string }
  ) =>
    request<IncidentDTO>('/incidents', {
      method: 'POST',
      token,
      body: JSON.stringify(data),
    }),

  // Add Comment
  addComment: (token: string, incidentId: string, text: string) =>
    request<{ id: string; text: string; created_at: string; author: string }>(`/incidents/${incidentId}/comment`, {
      method: 'POST',
      token,
      body: JSON.stringify({ text }),
    }),

  // Section 5: Decisions & Actions
  getDecision: (token: string, incidentId: string) =>
    request<any>(`/incidents/${incidentId}/decision`, { method: 'GET', token }),

  getActions: (token: string, incidentId: string) =>
    request<any[]>(`/incidents/${incidentId}/actions`, { method: 'GET', token }),

  // Section 5.2 Approve Action (backend-driven execution)
  approveAction: (token: string, incidentId: string, actionId: string, note?: string, planHash?: string) => {
    const idempotencyKey = generateUUID();
    return request<ActionApproveResponse>(`/incidents/${incidentId}/actions/${actionId}/approve`, {
      method: 'POST',
      token,
      idempotencyKey,
      body: JSON.stringify({ note, plan_hash: planHash }),
    });
  },

  // Section 5.3 Reject Action
  rejectAction: (token: string, incidentId: string, actionId: string, reason: string) =>
    request<ActionRejectResponse>(`/incidents/${incidentId}/actions/${actionId}/reject`, {
      method: 'POST',
      token,
      body: JSON.stringify({ reason }),
    }),

  // Section 5.4 Modify Action Step 1 (re-evaluation)
  modifyAction: (token: string, incidentId: string, actionId: string, modifiedPlan: { id: string; description: string; steps: string[] }) =>
    request<ActionModifyResponse>(`/incidents/${incidentId}/actions/${actionId}/modify`, {
      method: 'POST',
      token,
      body: JSON.stringify({ modified_plan: modifiedPlan }),
    }),

  // Section 4: Root Cause & Impact
  getRootCause: (token: string, incidentId: string) =>
    request<any>(`/incidents/${incidentId}/root-cause`, { method: 'GET', token }),

  getImpact: (token: string, incidentId: string) =>
    request<any>(`/incidents/${incidentId}/impact`, { method: 'GET', token }),

  // Section 6: Verification
  getVerification: (token: string, incidentId: string) =>
    request<any>(`/incidents/${incidentId}/verification`, { method: 'GET', token }),
};
