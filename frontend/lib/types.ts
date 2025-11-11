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

export interface CompileFlowRequest {
  yaml: string;
}

export interface CompileFlowResponse {
  flow_name: string;
  flow_version?: string;
  flow_description?: string;
  form_schema: {
    properties?: Record<string, any>;
    required?: string[];
  };
  workflow_summary: WorkflowSummary;
  warnings: string[];
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

// --- Telemetry Events ---

export type TelemetryEventType =
  | 'trace.plan'
  | 'trace.step.grounded'
  | 'trace.policy.check'
  | 'trace.tool.start'
  | 'trace.tool.end'
  | 'trace.route.chosen'
  | 'trace.critique'
  | 'trace.usage'
  | 'trace.progress';

export interface PIIStats {
  tokenized_count: number;
  detokenized_paths: string[];
  blocked_paths: string[];
}

export interface PlanStep {
  id: string;
  intent: string;
  deps: string[];
}

export interface TelemetryPlanEvent {
  type: 'trace.plan';
  run_id: string;
  total_steps: number;
  steps: PlanStep[];
  timestamp: string;
}

export interface TelemetryStepGroundedEvent {
  type: 'trace.step.grounded';
  run_id: string;
  step_id: string;
  intent: string;
  input_summary: string;
  timestamp: string;
}

export interface TelemetryPolicyCheckEvent {
  type: 'trace.policy.check';
  run_id: string;
  step_id: string;
  tool: string;
  allowed: boolean;
  reason?: string;
  pii_stats?: PIIStats;
  timestamp: string;
}

export interface TelemetryToolStartEvent {
  type: 'trace.tool.start';
  run_id: string;
  step_id: string;
  tool: string;
  attempt: number;
  timestamp: string;
}

export interface TelemetryToolEndEvent {
  type: 'trace.tool.end';
  run_id: string;
  step_id: string;
  tool: string;
  duration_ms: number;
  status: 'success' | 'error';
  error_type?: string;
  timestamp: string;
}

export interface TelemetryRouteChosenEvent {
  type: 'trace.route.chosen';
  run_id: string;
  step_id: string;
  route: string;
  signal_summary: string;
  timestamp: string;
}

export interface TelemetryCritiqueEvent {
  type: 'trace.critique';
  run_id: string;
  step_id: string;
  verdict: 'PASS' | 'FAIL' | 'ESCALATE' | 'REPLAN';
  confidence: number;
  issues: string[];
  summary: string;
  timestamp: string;
}

export interface TelemetryUsageEvent {
  type: 'trace.usage';
  run_id: string;
  step_id: string;
  tokens: number;
  cost_usd: number;
  duration_ms: number;
  timestamp: string;
}

export interface TelemetryProgressEvent {
  type: 'trace.progress';
  run_id: string;
  completed: number;
  total: number;
  percent: number;
  timestamp: string;
}

export type TelemetryEvent =
  | TelemetryPlanEvent
  | TelemetryStepGroundedEvent
  | TelemetryPolicyCheckEvent
  | TelemetryToolStartEvent
  | TelemetryToolEndEvent
  | TelemetryRouteChosenEvent
  | TelemetryCritiqueEvent
  | TelemetryUsageEvent
  | TelemetryProgressEvent;

// ========== Additional Types ==========

export interface WorkflowSummary {
  steps_count: number;
  ai_steps: number;
  credentials: string[];
}
