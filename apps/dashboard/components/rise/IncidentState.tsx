import React from 'react';
import type { IncidentStatus } from '../../lib/types';
import { INCIDENT_STATUS_META } from './tokens';
import { StatusBadge } from './StatusBadge';

/**
 * Incident lifecycle status badge. Thin mapping of {@link IncidentStatus} onto
 * the canonical <StatusBadge> — the incident-card colour language, defined once.
 */
export interface IncidentStateProps {
  status: IncidentStatus;
  dot?: boolean;
  className?: string;
}

export function IncidentState({ status, dot = true, className }: IncidentStateProps) {
  const meta = INCIDENT_STATUS_META[status];
  return <StatusBadge tone={meta.tone} label={meta.label} dot={dot} className={className} />;
}
