// ========== API v1 Types ==========

// --- Flows ---

export interface FlowListItem {
  id: string;
  name: string;
  version?: string;
  description?: string;
  created_at: string;
}

export interface FlowListResponse {
  items: FlowListItem[];
  total: number;
}

export interface RegisterFlowRequest {
  yaml: string;
}

export interface RegisterFlowResponse {
  id: string;
  name: string;
  version?: string;
  description?: string;
  created_at: string;
  workflow_summary: WorkflowSummary;
  form_schema: {
    properties?: Record<string, any>;
    required?: string[];
  };
}

export interface FlowDetailResponse {
  id: string;
  name: string;
  version?: string;
  description?: string;
  definition: Record<string, any>;
  triggers?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

// --- Runs ---

export interface RunListItem {
  id: string;
  flow_id: string;
  status: string;
  created_at: string;
  completed_at?: string;
}

export interface RunListResponse {
  items: RunListItem[];
  total: number;
}

export interface CreateRunRequest {
  flow_id: string;
  payload: Record<string, any>;
}

export interface CreateRunResponse {
  id: string;
  flow_id: string;
  status: string;
}

export interface RunDetailResponse {
  id: string;
  run_id: string;
  flow_id: string;
  flow_name?: string;
  status: string;
  payload?: any;
  error?: any;
  cost_cents?: number;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  totals: {
    tokens: number;
    cost_usd: number;
  };
  steps: RunStep[];
  artifacts?: any[];
  artifact_count?: number;
}

export interface RunStep {
  number: number;
  id: string;
  name: string;
  type?: string;
  status: 'queued' | 'running' | 'suspended' | 'failed' | 'completed';
  start_ts: string;
  end_ts?: string;
  duration_ms?: number;
  retry_count: number;
  artifact_ids?: string[];
  error?: any;
  tokens?: number;
  cost_usd?: number;
  input?: any;
  output?: any;
  failure?: any;
}

export interface RunStepsResponse {
  run_id: string;
  steps: RunStep[];
}

export interface AdvanceRunRequest {
  approval_data?: Record<string, any>;
}

export interface AdvanceRunResponse {
  run_id: string;
  status: string;
  message: string;
}

export interface RetryRunResponse {
  original_run_id: string;
  new_run_id: string;
  failing_step: number;
  status: string;
}

export interface ReplayRunResponse {
  original_run_id: string;
  new_run_id: string;
  from_step: number;
  status: string;
}

// --- Artifacts ---

export interface ArtifactItem {
  id: string;
  step_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface ArtifactListResponse {
  run_id: string;
  artifacts: ArtifactItem[];
}

// --- Credentials ---

export interface CredentialResponse {
  name: string;
  type: string;
  created_at: string;
  updated_at: string;
  description?: string;
}

export interface CredentialListResponse {
  items: CredentialResponse[];
  total: number;
}

export interface CreateCredentialRequest {
  name: string;
  credential_type: string;
  data: Record<string, any>;
  description?: string;
}

export interface UpdateCredentialRequest {
  data: Record<string, any>;
  description?: string;
}

// --- Graph Visualization ---

export interface GraphNode {
  id: string;
  label: string;
  type: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  label?: string;
}

export interface FlowGraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export type StepStatus =
  | 'queued'
  | 'running'
  | 'suspended'
  | 'failed'
  | 'completed'
  | 'pending'
  | 'success';

export interface RunGraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  status_by_step: Record<string, StepStatus>;
}

// --- WebSocket Events ---

export interface WSEvent {
  type: 'run.status' | 'step.started' | 'step.finished' | 'ping';
  run_id: string;
  timestamp: string;
  data: Record<string, any>;
}

// ========== Additional Types ==========

export interface WorkflowSummary {
  steps_count: number;
  ai_steps: number;
  credentials: string[];
}
