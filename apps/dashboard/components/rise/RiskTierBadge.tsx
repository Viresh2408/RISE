import React from 'react';
import type { RiskTier } from '../../lib/types';
import { RISK_TIER_META } from './tokens';
import { StatusBadge } from './StatusBadge';

/**
 * Risk-tier badge (low → critical). Maps {@link RiskTier} onto the canonical
 * <StatusBadge>. Note: the badge is presentational only — actual auto-vs-human
 * gating is decided server-side by the Risk Engine + RiskPolicy, never here.
 */
export interface RiskTierBadgeProps {
  tier: RiskTier;
  dot?: boolean;
  className?: string;
}

export function RiskTierBadge({ tier, dot = false, className }: RiskTierBadgeProps) {
  const meta = RISK_TIER_META[tier];
  return <StatusBadge tone={meta.tone} label={meta.label} dot={dot} className={className} />;
}
