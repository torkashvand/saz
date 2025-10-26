export interface RegisterFormsRequest {
  form_yaml: string
  workflow_yaml?: string
}

export interface RegisterFormsResponse {
  flow_id: string
  name: string
  json_schema: Record<string, any>
  ui_schema?: Record<string, any>
}

export interface CreateRunRequest {
  flow_id: string
  payload: Record<string, any>
}

export interface CreateRunResponse {
  run_id: string
  status: string
  state: Record<string, any>
}

export interface AdvanceRunRequest {
  event?: string
  user_input?: Record<string, any>
}

export interface AdvanceRunResponse {
  run_id: string
  status: string
  state: Record<string, any>
}

export interface StepHistoryItem {
  step: string
  status: string
  ts: string
  note?: string
}

export interface RunState {
  run_id: string
  flow_id: string
  status: string
  state: Record<string, any>
  created_at: string
  completed_at?: string
  history?: StepHistoryItem[]
  current_step?: string
}
