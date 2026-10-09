/**
 * RISE primitive logic — pure, side-effect-free mappings shared by the
 * components in this directory and exercised directly by the Vitest suite
 * (which runs in a `node` environment, so component rendering is not testable
 * but this logic is).
 *
 * Honesty rule (see CLAUDE.md): the UI must never be more confident than the
 * evidence supports. `resolveConfidence` therefore treats a null/undefined
 * score as "Not computed" and NEVER substitutes a fabricated default.
 *
 * Every class string here is a complete literal so Tailwind's content scanner
 * generates it. The semantic color utilities rely on the channel-form colors
 * registered in tailwind.config.js (e.g. `bg-sev1/15`).
 */
import type { SeverityLevel, IncidentStatus, RiskTier } from '../../lib/types';

export type Tone = 'violet' | 'amber' | 'green' | 'red' | 'slate' | 'neutral';

/** Soft-filled, outlined chip classes per tone. */
export const TONE_BADGE_CLASSES: Record<Tone, string> = {
  violet: 'border-violet-accent/30 bg-violet-accent/15 text-violet-accent',
  amber: 'border-amber-accent/30 bg-amber-accent/15 text-amber-accent',
  green: 'border-status-approved/30 bg-status-approved/15 text-status-approved',
  red: 'border-status-rejected/30 bg-status-rejected/15 text-status-rejected',
  slate: 'border-sev4/30 bg-sev4/15 text-sev4',
  neutral: 'border-warm-grey-600/30 bg-warm-grey-600/10 text-warm-grey-100',
};

/** Solid dot / indicator fill per tone. */
export const TONE_DOT_CLASSES: Record<Tone, string> = {
  violet: 'bg-violet-accent',
  amber: 'bg-amber-accent',
  green: 'bg-status-approved',
  red: 'bg-status-rejected',
  slate: 'bg-sev4',
  neutral: 'bg-warm-grey-600',
};

/** Foreground / icon color per tone (for use on transparent backgrounds). */
export const TONE_TEXT_CLASSES: Record<Tone, string> = {
  violet: 'text-violet-accent',
  amber: 'text-amber-accent',
  green: 'text-status-approved',
  red: 'text-status-rejected',
  slate: 'text-sev4',
  neutral: 'text-warm-grey-100',
};

export interface SeverityMeta {
  label: string;
  badgeClass: string;
  accentBorderClass: string;
  dotClass: string;
}

/** SEV1 (most severe) → SEV4. Each keeps its own hue rather than a shared tone. */
export const SEVERITY_META: Record<SeverityLevel, SeverityMeta> = {
  SEV1: { label: 'SEV1', badgeClass: 'border-sev1/30 bg-sev1/15 text-sev1', accentBorderClass: 'border-sev1', dotClass: 'bg-sev1' },
  SEV2: { label: 'SEV2', badgeClass: 'border-sev2/30 bg-sev2/15 text-sev2', accentBorderClass: 'border-sev2', dotClass: 'bg-sev2' },
  SEV3: { label: 'SEV3', badgeClass: 'border-sev3/30 bg-sev3/15 text-sev3', accentBorderClass: 'border-sev3', dotClass: 'bg-sev3' },
  SEV4: { label: 'SEV4', badgeClass: 'border-sev4/30 bg-sev4/15 text-sev4', accentBorderClass: 'border-sev4', dotClass: 'bg-sev4' },
};

export interface StatusMeta {
  label: string;
  tone: Tone;
}

/**
 * Incident lifecycle status → display tone. Mirrors the existing
 * incident-card colour language so consolidating onto <StatusBadge> is a
 * visual no-op.
 */
export const INCIDENT_STATUS_META: Record<IncidentStatus, StatusMeta> = {
  open: { label: 'Open', tone: 'red' },
  investigating: { label: 'Investigating', tone: 'violet' },
  awaiting_approval: { label: 'Awaiting approval', tone: 'amber' },
  resolved: { label: 'Resolved', tone: 'green' },
  closed: { label: 'Closed', tone: 'green' },
};

/** Risk tier → tone (hotter tier = hotter hue). */
export const RISK_TIER_META: Record<RiskTier, StatusMeta> = {
  low: { label: 'Low risk', tone: 'slate' },
  medium: { label: 'Medium risk', tone: 'amber' },
  high: { label: 'High risk', tone: 'red' },
  critical: { label: 'Critical risk', tone: 'red' },
};

/** Agent step run state. `success|failed|skipped` come from AgentStepDTO; the
 *  UI-only `running|pending` describe stages that have no result row yet. */
export type AgentRunState = 'success' | 'failed' | 'skipped' | 'running' | 'pending';

export const AGENT_STATE_META: Record<AgentRunState, StatusMeta> = {
  success: { label: 'Success', tone: 'green' },
  failed: { label: 'Failed', tone: 'red' },
  skipped: { label: 'Skipped', tone: 'neutral' },
  running: { label: 'Running', tone: 'violet' },
  pending: { label: 'Pending', tone: 'neutral' },
};

export type ConfidenceBand = 'high' | 'medium' | 'low' | 'none';

export interface ResolvedConfidence {
  /** 'computed' when a real numeric score exists (0 is valid), else 'not-computed'. */
  state: 'computed' | 'not-computed';
  /** 0..1 normalized, or null when not computed. */
  fraction: number | null;
  /** 0..100 rounded, or null when not computed. */
  percent: number | null;
  /** "88%" when computed, "—" when not. */
  display: string;
  /** "88%" when computed, "Not computed" when not — safe as an accessible label. */
  label: string;
  band: ConfidenceBand;
}

/**
 * Resolve a confidence score for display WITHOUT fabricating one.
 * `null`/`undefined`/`NaN` → "Not computed". A real 0 stays 0% (band 'low'),
 * which is the exact case the old `score || 0.85` bug corrupted into 85%.
 *
 * @param scale pass 100 when the source value is already a percentage.
 */
export function resolveConfidence(
  value: number | null | undefined,
  scale: 1 | 100 = 1,
): ResolvedConfidence {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return { state: 'not-computed', fraction: null, percent: null, display: '—', label: 'Not computed', band: 'none' };
  }
  const raw = scale === 100 ? value / 100 : value;
  const fraction = Math.min(1, Math.max(0, raw));
  const percent = Math.round(fraction * 100);
  const band: ConfidenceBand = fraction >= 0.8 ? 'high' : fraction >= 0.5 ? 'medium' : 'low';
  return { state: 'computed', fraction, percent, display: `${percent}%`, label: `${percent}%`, band };
}

export interface LifecycleStageMeta {
  key: string;
  label: string;
}

/**
 * The RISE agent pipeline's linear stages, mirroring the LangGraph node order
 * (ingest → … → verify). The terminal branches (close | rollback |
 * manual_handoff | escalate) are outcomes, not linear stages, so they are not
 * listed here.
 */
export const RISE_LIFECYCLE: readonly LifecycleStageMeta[] = [
  { key: 'ingest', label: 'Ingest' },
  { key: 'build_context', label: 'Context' },
  { key: 'investigate', label: 'Investigate' },
  { key: 'root_cause', label: 'Root cause' },
  { key: 'impact_analysis', label: 'Impact' },
  { key: 'decide', label: 'Decide' },
  { key: 'await_human', label: 'Approval' },
  { key: 'execute', label: 'Execute' },
  { key: 'verify', label: 'Verify' },
] as const;

export type StageState = 'complete' | 'active' | 'pending';

/** Coarse index of the stage a given incident status is currently at. */
const STATUS_STAGE_INDEX: Record<IncidentStatus, number> = {
  open: 0, // ingest
  investigating: 2, // investigate
  awaiting_approval: 6, // await_human
  resolved: RISE_LIFECYCLE.length - 1, // verify
  closed: RISE_LIFECYCLE.length - 1,
};

/**
 * Derive per-stage state from an incident status. Because the pipeline is
 * strictly sequential, reaching stage N structurally implies stages < N
 * completed — so marking them 'complete' is inference from the graph shape,
 * not fabricated progress. Terminal statuses mark every stage complete.
 *
 * Callers with real AgentStep rows should pass those instead of relying on
 * this coarse derivation.
 */
export function deriveLifecycle(status: IncidentStatus): Record<string, StageState> {
  const activeIndex = STATUS_STAGE_INDEX[status];
  const terminal = status === 'resolved' || status === 'closed';
  const result: Record<string, StageState> = {};
  RISE_LIFECYCLE.forEach((stage, i) => {
    if (terminal || i < activeIndex) result[stage.key] = 'complete';
    else if (i === activeIndex) result[stage.key] = 'active';
    else result[stage.key] = 'pending';
  });
  return result;
}
