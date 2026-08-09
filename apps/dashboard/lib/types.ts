export type SeverityLevel = 'SEV1' | 'SEV2' | 'SEV3' | 'SEV4';
export type IncidentStatus = 'open' | 'investigating' | 'awaiting_approval' | 'resolved' | 'closed';
export type RiskTier = 'low' | 'medium' | 'high' | 'critical';

export interface MetaInfo {
  request_id: string;
  timestamp: string;
  next_cursor?: string | null;
}

export interface ErrorDetail {
  code: string;
  message: string;
  details?: Record<string, any>;
}

export interface ApiResponse<T> {
  data: T | null;
  meta: MetaInfo;
  error: ErrorDetail | null;
}

export interface SessionResponse {
  user_id: string;
  roles: string[];
  tenant_id: string;
}

export interface IncidentDTO {
  id: string;
  title: string;
  description: string;
  severity: SeverityLevel;
  status: IncidentStatus;
  affected_service?: string | null;
  created_at: string;
  updated_at?: string | null;
  resolution_note?: string | null;
}

export interface EvidenceDTO {
  id: string;
  type: string;
  description: string;
  source: string;
}

export interface IncidentRefDTO {
  id: string;
  title: string;
  similarity: number;
}

export interface ActionPlanDTO {
  id: string;
  description: string;
  steps: string[];
  rollback_plan?: string | null;
}

export interface RootCauseDTO {
  cause: string;
  confidence: number;
  explanation?: string | null;
  evidence_refs?: string[];
  evidence?: EvidenceDTO[];
  similar_incidents?: IncidentRefDTO[];
}

export interface ImpactDTO {
  blast_radius: string[];
  severity: SeverityLevel;
  estimated_users_affected: number;
  business_impact_notes: string;
}

export interface DecisionDTO {
  risk_tier: RiskTier;
  confidence: number;
  recommended_action: ActionPlanDTO;
  requires_approval: boolean;
}

export interface RemediationActionDTO {
  id: string;
  incident_id: string;
  name: string;
  risk_tier: RiskTier;
  status: 'pending_approval' | 'approved' | 'rejected' | 'executed' | 'failed';
}

export interface CheckItemDTO {
  name: string;
  result: 'pass' | 'fail';
  value: string;
}

export interface VerificationDTO {
  status: 'passed' | 'failed' | 'pending';
  checks: CheckItemDTO[];
}

export interface CommentDTO {
  id: string;
  incident_id: string;
  text: string;
  created_at: string;
  author: string;
}

export interface TimelineItem {
  timestamp: string;
  event: string;
  text?: string;
  author?: string;
}

export interface IncidentDetailDTO extends IncidentDTO {
  timeline: TimelineItem[];
  root_cause?: RootCauseDTO | null;
  impact?: ImpactDTO | null;
  actions: RemediationActionDTO[];
  approvals: any[];
  decision?: DecisionDTO | null;
  verification?: VerificationDTO | null;
}

export interface ActionApproveResponse {
  status: 'approved';
  execution_status: 'queued' | 'completed' | string;
}

export interface ActionRejectResponse {
  status: 'rejected';
}

export interface ActionModifyResponse {
  status: 're-evaluated';
  new_risk_tier: RiskTier;
}
