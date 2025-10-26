import type {
  RegisterFlowRequest,
  RegisterFlowResponse,
  FlowGraphResponse,
  RunGraphResponse,
  CreateRunRequest,
  CreateRunResponse,
  RunResponse,
} from './types'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

class ApiError extends Error {
  constructor(public status: number, message: string, public data?: any) {
    super(message)
    this.name = 'ApiError'
  }
}

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      throw new ApiError(
        response.status,
        errorData.detail || `Request failed with status ${response.status}`,
        errorData
      )
    }

    return await response.json()
  } catch (error) {
    if (error instanceof ApiError) throw error

    throw new ApiError(
      0,
      error instanceof Error ? error.message : 'Network error',
      error
    )
  }
}

export const api = {
  // ========== Unified DSL Endpoints ==========

  /**
   * Register a unified YAML workflow
   */
  registerFlow: (data: RegisterFlowRequest) =>
    fetchApi<RegisterFlowResponse>('/flows/register', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Get workflow graph visualization data
   */
  getFlowGraph: (flowId: string) =>
    fetchApi<FlowGraphResponse>(`/flows/${flowId}/graph`),

  /**
   * Get run graph with status overlay
   */
  getRunGraph: (runId: string) =>
    fetchApi<RunGraphResponse>(`/runs/${runId}/graph`),

  /**
   * Get detailed run information with steps, tokens, and costs
   */
  getRunDetails: (runId: string) =>
    fetchApi<RunResponse>(`/runs/${runId}`),

  /**
   * Create a new run from a registered flow
   */
  createRun: (data: CreateRunRequest) =>
    fetchApi<CreateRunResponse>('/runs', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}
