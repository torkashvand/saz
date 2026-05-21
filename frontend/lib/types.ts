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

export interface CompileError {
  code: string;
  message: string;
  section?: string | null;
  step_id?: string | null;
  json_pointer?: string | null;
}

export interface CompileFlowResponse {
  valid: boolean;
  flow_name: string;
  flow_version?: string;
  flow_description?: string;
  form_schema: {
    properties?: Record<string, any>;
    required?: string[];
  };
  workflow_summary: WorkflowSummary;
  warnings: string[];
  errors?: CompileError[];
  normalized_dsl?: Record<string, unknown> | null;
}

export interface UpdateFlowRequest {
  yaml: string;
}

export interface DslMetadataStepType {
  name: string;
  label: string;
  category: string;
  requires_instruction: boolean;
  requires_expect: boolean;
  requires_description: boolean;
  requires_params: boolean;
  accepts_uses_credentials: boolean;
  accepts_retry: boolean;
  requires_if?: boolean;
  requires_tool?: boolean;
  ai_op?: {
    description: string;
    output_format: 'json' | 'text';
    default_temperature: number;
    default_max_tokens: number;
    default_expect_schema: Record<string, unknown>;
    input_extras: Record<string, unknown>;
  };
}

export interface DslMetadata {
  schema_version: number;
  planner_modes: string[];
  step_types: DslMetadataStepType[];
  form_fields: {
    types: string[];
    constraints: Record<string, string[]>;
    formats: string[];
    aliases: Record<string, string[]>;
  };
  policies: Record<string, unknown>;
  telemetry: Record<string, unknown>;
  expression_helpers: Array<{
    name: string;
    syntax: string;
    description: string;
    needs_argument: boolean;
    argument_kind: string;
  }>;
  tools: Array<{ name: string; description: string }>;
}

export interface FlowDetailResponse {
  id: string;
  name: string;
  version?: string;
  description?: string;
  definition: Record<string, any>;
  original_yaml: string | null;
  planner_mode: string;
  policies: {
    max_steps: number;
    max_cost_usd: number;
    max_tokens: number;
  };
  step_count: number;
  created_at: string;
}

// --- Runs ---

export interface RunListItem {
  id: string;
  flow_id: string;
  flow_name: string;
  status: string;
  created_at: string;
  completed_at?: string;
  total_tokens: number;
  total_cost_usd: number;
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
  flow_id: string;
  flow_name: string;
  status: string;
  planner_mode: string;
  payload: Record<string, any>;
  error?: any;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  total_tokens: number;
  total_cost_usd: number;
  total_events?: number;
  error_count?: number;
  policy_violations?: any;
  steps: RunStep[];
  artifacts?: string[];

  // Enhanced UX fields
  error_summary?: {
    message: string;
    category: string;
    failed_step_number: number | null;
    failed_step_name: string | null;
    remediation_actions: string[];
    technical_details: Record<string, any>;
  };
  run_metadata?: {
    total_steps: number;
    succeeded_steps: number;
    failed_steps: number;
    running_steps: number;
    skipped_steps: number;
  };
  triggered_by?: {
    type: string;
    user_id?: string;
    user_name?: string;
  };
  planned_steps: PlannedStep[];
}

export interface PlannedStep {
  index: number;
  id: string;
  name: string;
  step_type: string | null;
}

export interface RunStep {
  id: string;
  number: number;
  name: string;
  attempt: number;
  step_type: string;
  status: 'queued' | 'running' | 'suspended' | 'failed' | 'completed';
  start_ts?: string;
  end_ts?: string;
  duration_ms?: number;
  retry_count: number;
  tokens?: number;
  cost_usd?: number;
  input?: any;
  output?: any;
  error?: any;

  // Enhanced UX fields
  description?: string;
  failure_reason?: string;
  error_category?: string;
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

export interface ResumeRunRequest {
  resume_data?: Record<string, any> | null;
  override_payload?: Record<string, any> | null;
}

export interface ResumeRunResponse {
  run_id: string;
  status: string;
}

/** Shape of run.error when type === 'HumanApprovalRequired' */
export interface HumanApprovalError {
  message: string;
  type: 'HumanApprovalRequired';
  step_id: string;
  reasoning?: string;
  callback_id?: string;
}

/** Shape of run.error when type === 'WebhookWait' */
export interface WebhookWaitError {
  message: string;
  type: 'WebhookWait';
  step_id: string;
  callback_id: string;
}

/** Request body for POST /api/v1/webhooks/callback/{callback_id}. */
export interface WebhookCallbackRequest {
  action: 'approve' | 'reject';
  reason?: string;
  data?: Record<string, unknown>;
}

export interface WebhookCallbackResponse {
  status: 'resumed' | 'rejected' | 'already_processed';
  run_id: string;
  message: string;
}

export interface RetryRunResponse {
  run_id: string;
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
  type: string;
  data: Record<string, any>;
  description?: string;
}

export interface UpdateCredentialRequest {
  type?: string;
  data?: Record<string, any>;
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

// --- Unified Event System ---

export type EventType =
  // Run lifecycle
  | 'run.started'
  | 'run.completed'
  | 'run.failed'
  | 'run.cancelled'
  | 'run.suspended'
  | 'run.resumed'
  // Step lifecycle
  | 'step.started'
  | 'step.completed'
  | 'step.failed'
  | 'step.skipped'
  | 'step.suspended'
  | 'step.resumed'
  // Tool execution
  | 'tool.started'
  | 'tool.succeeded'
  | 'tool.failed'
  // Planner (agentic mode)
  | 'plan.generated'
  | 'plan.updated'
  | 'branch.chosen'
  // Policy & safety
  | 'policy.pii.redacted'
  | 'policy.budget.updated'
  | 'policy.budget.exhausted'
  | 'policy.rate_limited'
  | 'policy.blocked'
  // Usage & progress
  | 'usage.recorded'
  | 'progress.updated'
  // Human interaction
  | 'approval.requested'
  | 'approval.granted'
  | 'approval.denied'
  | 'action.aborted'
  // Artifacts
  | 'artifact.created'
  // System
  | 'system.error'
  | 'system.warning';

export type Severity = 'info' | 'warn' | 'error';
export type Actor = 'system' | 'user' | 'llm';
export type PlannerMode = 'deterministic' | 'agentic';

export interface Event {
  id: string;
  event_type: EventType;
  timestamp: string; // ISO 8601
  schema_version: number;

  run_id: string;
  step_id: string | null;
  correlation_id: string | null;

  planner_mode: PlannerMode;
  severity: Severity;
  actor: Actor;

  summary: string;
  payload: Record<string, any>;
  tags: Record<string, string>;
}

export interface RunSummary {
  id: string;
  flow_id: string;
  status: string;
  planner_mode: PlannerMode;

  created_at: string;
  completed_at: string | null;
  duration_ms: number | null;

  total_events: number;
  event_counts: Record<string, number>;
  total_tokens: number;
  total_cost_usd: number;
  error_count: number;
}

export interface EventListResponse {
  events: Event[];
  total: number;
  cursor: string | null;
  has_more: boolean;
}

// Derived UI state
export interface StepTimeline {
  step_id: string;
  step_name: string;
  status: 'running' | 'completed' | 'failed' | 'skipped';
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  events: Event[];
}

export interface RunTimeline {
  run: RunSummary;
  steps: StepTimeline[];
  orphan_events: Event[]; // Events not tied to a step
}

// ========== Additional Types ==========

export interface WorkflowSummary {
  steps_count: number;
  ai_steps: number;
  credentials: string[];
}

// ========== Templates ==========

export interface TemplateSummary {
  id: string;
  title: string;
  description: string;
  tags: string[];
  complexity: string;
  recommended: boolean;
  flow_name: string;
  steps_count: number;
  ai_steps: number;
  credentials: string[];
}

export interface TemplateDetail {
  metadata: {
    id: string;
    title: string;
    description: string;
    tags: string[];
    complexity: string;
    recommended: boolean;
  };
  yaml: string;
  flow_name: string;
  flow_version: string;
  flow_description: string;
  steps_count: number;
  ai_steps: number;
  credentials: string[];
  form_schema: Record<string, any>;
}

// --- AI Operations Reference ---

export interface AIOpReference {
  name: string;
  description: string;
  output_format: 'json' | 'text';
  default_output_schema: Record<string, any>;
  extras: Record<string, any>;
}

// --- Auth ---

export interface LoginRequest {
  identifier: string;
  password: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface CurrentUser {
  id: string;
  username: string;
  email: string;
  display_name?: string | null;
  is_active: boolean;
  is_admin: boolean;
  must_change_password: boolean;
  created_at: string;
  last_login_at?: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: CurrentUser;
}

// --- Admin user management ---

export interface AdminUser {
  id: string;
  username: string;
  email: string;
  display_name?: string | null;
  is_active: boolean;
  is_admin: boolean;
  must_change_password: boolean;
  created_at: string;
  updated_at: string;
  last_login_at?: string | null;
}

export interface AdminUserListResponse {
  items: AdminUser[];
  total: number;
}

export interface AdminCreateUserRequest {
  username: string;
  email: string;
  password: string;
  display_name?: string;
  is_admin?: boolean;
  is_active?: boolean;
  must_change_password?: boolean;
}

export interface AdminUpdateUserRequest {
  username?: string;
  email?: string;
  display_name?: string;
}
