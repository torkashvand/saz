import type {
  RegisterFormsRequest,
  RegisterFormsResponse,
  CreateRunRequest,
  CreateRunResponse,
  AdvanceRunRequest,
  AdvanceRunResponse,
  RunState,
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
  registerForms: (data: RegisterFormsRequest) =>
    fetchApi<RegisterFormsResponse>('/register_forms', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  createRun: (data: CreateRunRequest) =>
    fetchApi<CreateRunResponse>('/runs', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getRun: (runId: string) =>
    fetchApi<RunState>(`/runs/${runId}`),

  advanceRun: (runId: string, data: AdvanceRunRequest) =>
    fetchApi<AdvanceRunResponse>(`/runs/${runId}/advance`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}
