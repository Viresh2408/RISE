import { describe, it, expect, vi } from 'vitest';
import { apiClient } from '../lib/api-client';
import { mockIncidentDetail } from './test-utils';

describe('Dashboard & Action Approval Flow Unit Tests', () => {
  it('verifies every field in incident detail traces back to real Step 1.3 schema DTO fields', () => {
    expect(mockIncidentDetail.id).toBeDefined();
    expect(mockIncidentDetail.title).toBeDefined();
    expect(mockIncidentDetail.severity).toBe('SEV2');
    expect(mockIncidentDetail.status).toBe('awaiting_approval');
    expect(mockIncidentDetail.affected_service).toBe('auth-service');
    expect(mockIncidentDetail.root_cause?.cause).toContain('connection pool leak');
    expect(mockIncidentDetail.root_cause?.confidence).toBe(0.88);
    expect(mockIncidentDetail.impact?.blast_radius).toContain('auth-service');
    expect(mockIncidentDetail.decision?.risk_tier).toBe('high');
    expect(mockIncidentDetail.decision?.recommended_action.steps[0]).toContain('kubectl rollout restart');
    expect(mockIncidentDetail.verification?.checks[0].result).toBe('pass');
  });

  it('approveAction includes Idempotency-Key and calls approve endpoint', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        data: { status: 'approved', execution_status: 'queued' },
        meta: { request_id: 'req-1', timestamp: new Date().toISOString() },
        error: null,
      }),
    } as Response);

    const res = await apiClient.approveAction('test-token', 'inc-100', 'act-001', 'Approved via test');

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/v1/incidents/inc-100/actions/act-001/approve');
    expect((opts?.headers as Record<string, string>)['Authorization']).toBe('Bearer test-token');
    expect((opts?.headers as Record<string, string>)['Idempotency-Key']).toBeDefined();
    expect(res.status).toBe('approved');
    expect(res.execution_status).toBe('queued');

    fetchSpy.mockRestore();
  });

  it('rejectAction sends reason to Section 5 endpoint', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        data: { status: 'rejected' },
        meta: { request_id: 'req-2', timestamp: new Date().toISOString() },
        error: null,
      }),
    } as Response);

    const res = await apiClient.rejectAction('test-token', 'inc-100', 'act-001', 'High risk window');

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/v1/incidents/inc-100/actions/act-001/reject');
    expect(opts?.body).toContain('High risk window');
    expect(res.status).toBe('rejected');

    fetchSpy.mockRestore();
  });

  it('modifyAction executes Step 1 re-evaluation returning new risk tier', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        data: { status: 're-evaluated', new_risk_tier: 'medium' },
        meta: { request_id: 'req-3', timestamp: new Date().toISOString() },
        error: null,
      }),
    } as Response);

    const res = await apiClient.modifyAction('test-token', 'inc-100', 'act-001', {
      id: 'plan-001',
      description: 'Modified plan description',
      steps: ['kubectl rollout restart deployment auth-service'],
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(res.status).toBe('re-evaluated');
    expect(res.new_risk_tier).toBe('medium');

    fetchSpy.mockRestore();
  });

  it('handles 409 ACTION_PLAN_CHANGED error envelope correctly', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({
        data: null,
        meta: { request_id: 'req-4', timestamp: new Date().toISOString() },
        error: {
          code: 'ACTION_PLAN_CHANGED',
          message: 'Action plan hash changed since approval was requested',
        },
      }),
    } as Response);

    await expect(apiClient.approveAction('test-token', 'inc-100', 'act-001')).rejects.toThrow(
      'Action plan hash changed since approval was requested'
    );

    fetchSpy.mockRestore();
  });
});
