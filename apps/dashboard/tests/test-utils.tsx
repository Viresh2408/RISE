import React from 'react';
import { UserSession } from '../lib/auth-context';

export function createMockAuthSession(overrides?: Partial<UserSession>): UserSession {
  return {
    user_id: 'test-user-001',
    email: 'engineer@rise.internal',
    roles: ['approver', 'engineer', 'viewer'],
    tenant_id: '00000000-0000-0000-0000-000000000001',
    token: 'mock-jwt-test-token',
    ...overrides,
  };
}

export const mockIncidentDetail = {
  id: 'inc-test-100',
  title: 'Test High CPU Alert in auth-service',
  description: 'Test incident description for schema verification',
  severity: 'SEV2' as const,
  status: 'awaiting_approval' as const,
  affected_service: 'auth-service',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  timeline: [
    { timestamp: new Date().toISOString(), event: 'detection', text: 'CloudWatch alarm triggered' },
  ],
  root_cause: {
    cause: 'Test connection pool leak in auth middleware',
    confidence: 0.88,
    evidence: [
      { id: 'ev-01', type: 'metric_spike', description: 'DB pool wait > 5s', source: 'Prometheus' },
    ],
    similar_incidents: [
      { id: 'inc-prev-01', title: 'Previous DB pool leak', similarity: 0.9 },
    ],
  },
  impact: {
    blast_radius: ['auth-service', 'api-gateway'],
    severity: 'SEV2' as const,
    estimated_users_affected: 1500,
    business_impact_notes: 'Impacts authentication flow in US-East',
  },
  decision: {
    risk_tier: 'high' as const,
    confidence: 0.88,
    recommended_action: {
      id: 'plan-001',
      description: 'Restart auth-service deployment pods gracefully',
      steps: ['kubectl rollout restart deployment auth-service'],
    },
    requires_approval: true,
  },
  actions: [
    {
      id: 'act-001',
      incident_id: 'inc-test-100',
      name: 'Restart auth-service deployment',
      risk_tier: 'high' as const,
      status: 'pending_approval' as const,
    },
  ],
  verification: {
    status: 'passed' as const,
    checks: [
      { name: 'http_error_rate', result: 'pass' as const, value: '0.01%' },
    ],
  },
  approvals: [],
};
