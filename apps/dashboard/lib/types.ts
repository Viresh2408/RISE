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

export interface CodeFixSnippetDTO {
  file: string;
  github_url: string;
  lines: string;
  commit_id: string;
  diff: string;
}

export interface ActionPlanDTO {
  id: string;
  description: string;
  steps: string[];
  rollback_plan?: string | null;
  code_fix_snippet?: CodeFixSnippetDTO | null;
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
  execution_status: 'queued' | 'completed' | 'executed' | string;
  commit_sha?: string;
  commit_url?: string;
  commit_message?: string;
  commit_timestamp?: string;
  file_modified?: string;
  branch?: string;
  pr_url?: string;
  pr_number?: number;
}

export interface ActionRejectResponse {
  status: 'rejected';
}

export interface ActionModifyResponse {
  status: 're-evaluated';
  new_risk_tier: RiskTier;
}

// Knowledge Base / Runbooks
export interface KnowledgeDTO {
  id: string;
  title: string;
  content: string;
  service?: string | null;
  tags: string[];
  created_at: string;
  updated_at?: string | null;
}

// OPA Risk Policies
export interface PolicyDTO {
  id: string;
  name?: string;
  description?: string;
  action_types?: string[];
  action_pattern?: string;
  environment?: string;
  max_blast_radius?: number;
  risk_tier: RiskTier;
  requires_approval: boolean;
  version: number;
  created_at?: string;
}

// Reports
export interface MttrDataPoint {
  service: string;
  avg_minutes: number;
  incident_count: number;
  period: string;
}

export interface MttrReportDTO {
  overall_avg_minutes?: number;
  avg_mttr_minutes?: number;
  reduction_pct?: number;
  data_points?: MttrDataPoint[];
  trend?: Array<{ date: string; mttr_minutes?: number; mttr?: number }>;
}

export interface AutonomyReportDTO {
  auto_resolved_pct?: number;
  human_approved_pct?: number;
  human_rejected_pct?: number;
  rejected_pct?: number;
  total_incidents?: number;
  by_severity?: {
    SEV1?: number;
    SEV2?: number;
    SEV3?: number;
    SEV4?: number;
  };
}

// Integrations
export type IntegrationStatus = 'connected' | 'disconnected' | 'error';

export interface IntegrationDTO {
  type: string;
  name: string;
  description: string;
  status: IntegrationStatus;
  connected_at?: string | null;
  icon?: string;
}

// Agent Runs
export interface AgentRunDTO {
  id: string;
  incident_id: string;
  status: 'running' | 'completed' | 'failed';
  started_at: string;
  completed_at?: string | null;
  nodes_executed: number;
}

export interface AgentStepDTO {
  node: string;
  status: 'success' | 'failed' | 'skipped';
  duration_ms: number;
  output_summary?: string | null;
  started_at: string;
}

