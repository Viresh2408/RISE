/**
 * RISE design-system primitives (Phase 0 foundation).
 *
 * Single import surface for the consolidated severity / status / confidence /
 * lifecycle / elevation primitives and their pure logic. Downstream pages
 * import from here rather than re-implementing any of these mappings.
 */

// Pure logic + shared token maps
export * from './tokens';

// Dimensional surface
export { ElevationSurface } from './ElevationSurface';
export type { ElevationSurfaceProps } from './ElevationSurface';

// Status / severity / risk
export { StatusBadge } from './StatusBadge';
export type { StatusBadgeProps } from './StatusBadge';
export { SeverityMarker } from './SeverityMarker';
export type { SeverityMarkerProps } from './SeverityMarker';
export { IncidentState } from './IncidentState';
export type { IncidentStateProps } from './IncidentState';
export { RiskTierBadge } from './RiskTierBadge';
export type { RiskTierBadgeProps } from './RiskTierBadge';

// Confidence
export { ConfidenceRing } from './ConfidenceRing';
export type { ConfidenceRingProps } from './ConfidenceRing';
export { ConfidenceBar } from './ConfidenceBar';
export type { ConfidenceBarProps } from './ConfidenceBar';

// Agent pipeline
export { AgentNode } from './AgentNode';
export type { AgentNodeProps } from './AgentNode';
export { LifecycleStage, StageMarker } from './LifecycleStage';
export type { LifecycleStageProps } from './LifecycleStage';
export { Spine } from './Spine';
export type { SpineProps, SpineStage } from './Spine';

// Approval + evidence
export { ApprovalAction } from './ApprovalAction';
export type { ApprovalActionProps } from './ApprovalAction';
export { EvidenceLink } from './EvidenceLink';
export type { EvidenceLinkProps } from './EvidenceLink';
