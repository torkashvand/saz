// ========== Unified DSL Flow Registration ==========
export interface RegisterFlowRequest {
  yaml: string
}

export interface WorkflowSummary {
  steps_count: number
  ai_steps: number
  credentials: string[]
}

export interface RegisterFlowResponse {
  flow_id: string
  form_schema: Record<string, any>
  workflow_summary: WorkflowSummary
}

// ========== Graph Visualization ==========
export interface GraphNode {
  id: string
  label: string
  type: string
}

export interface GraphEdge {
  from: string
  to: string
  label?: string
}

export interface FlowGraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export type StepStatus = 'pending' | 'running' | 'success' | 'failed' | 'suspended'

export interface RunGraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
  status: Record<string, StepStatus>
}

// ========== Run Execution ==========
export interface CreateRunRequest {
  flow_id: string
  payload: Record<string, any>
}

export interface CreateRunResponse {
  run_id: string
  status: string
}

export interface StepFailure {
  type: string
  message: string
  issues?: string[]
  raw_critique?: any
}

export interface Step {
  id: string
  type: string
  status: StepStatus
  duration_ms?: number
  input?: Record<string, any>
  output?: any
  tokens?: number
  cost_usd?: number
  error?: string
  failure?: StepFailure
  critique?: any
}

export interface RunTotals {
  tokens: number
  cost_usd: number
}

export interface RunResponse {
  run_id: string
  flow_id: string
  status: StepStatus
  started_at?: string
  completed_at?: string
  totals: RunTotals
  steps: Step[]
  artifacts: string[]
  failure_reason?: string
  failing_step_id?: string
}

