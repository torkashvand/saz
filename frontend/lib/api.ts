import type {
  // Flows
  FlowListResponse,
  RegisterFlowRequest,
  RegisterFlowResponse,
  CompileFlowRequest,
  CompileFlowResponse,
  FlowDetailResponse,
  // Runs
  RunListResponse,
  CreateRunRequest,
  CreateRunResponse,
  RunDetailResponse,
  RunStepsResponse,
  AdvanceRunRequest,
  AdvanceRunResponse,
  RetryRunResponse,
  ReplayRunResponse,
  // Events
  Event,
  EventListResponse,
  RunSummary,
  EventType,
  Severity,
  // Artifacts
  ArtifactListResponse,
  // Credentials
  CredentialListResponse,
  CreateCredentialRequest,
  UpdateCredentialRequest,
  CredentialResponse,
  // Graph
  RunGraphResponse,
  // Legacy
  FlowGraphResponse,
} from './types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
const WS_BASE_URL = API_BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://');

/**
 * Standardized API error matching backend ErrorResponse
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public error: string,
    message: string,
    public details?: Array<{ field?: string; message: string; code?: string }>,
    public requestId?: string,
    public timestamp?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));

      // Handle standardized error response
      if (errorData.error && errorData.message) {
        throw new ApiError(
          response.status,
          errorData.error,
          errorData.message,
          errorData.details,
          errorData.request_id,
          errorData.timestamp,
        );
      }

      // Legacy error handling
      throw new ApiError(
        response.status,
        'api_error',
        errorData.detail || `Request failed with status ${response.status}`,
        undefined,
        undefined,
        new Date().toISOString(),
      );
    }

    return await response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;

    throw new ApiError(
      0,
      'network_error',
      error instanceof Error ? error.message : 'Network error',
      undefined,
      undefined,
      new Date().toISOString(),
    );
  }
}

export const api = {
  // ========== Flow Endpoints ==========

  /**
   * List all flows with pagination
   */
  listFlows: (params?: { limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.limit) query.set('limit', params.limit.toString());
    if (params?.offset) query.set('offset', params.offset.toString());
    return fetchApi<FlowListResponse>(`/api/v1/flows?${query}`);
  },

  /**
   * Compile and validate YAML DSL without registering
   */
  compileFlow: (data: CompileFlowRequest) =>
    fetchApi<CompileFlowResponse>('/api/v1/flows/compile', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Register a new flow from YAML DSL
   */
  registerFlow: (data: RegisterFlowRequest) =>
    fetchApi<RegisterFlowResponse>('/api/v1/flows', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Get full flow metadata
   */
  getFlow: (id: string) => fetchApi<FlowDetailResponse>(`/api/v1/flows/${id}`),

  /**
   * Get flow graph visualization
   */
  getFlowGraph: (flowId: string) => fetchApi<FlowGraphResponse>(`/api/v1/flows/${flowId}/graph`),

  // ========== Run Endpoints ==========

  /**
   * List runs with optional filtering
   */
  listRuns: (params?: { flow_id?: string; status?: string; limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.flow_id) query.set('flow_id', params.flow_id);
    if (params?.status) query.set('status', params.status);
    if (params?.limit) query.set('limit', params.limit.toString());
    if (params?.offset) query.set('offset', params.offset.toString());
    return fetchApi<RunListResponse>(`/api/v1/runs?${query}`);
  },

  /**
   * Create and start a new run (async execution)
   */
  createRun: (data: CreateRunRequest) =>
    fetchApi<CreateRunResponse>('/api/v1/runs', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Get detailed run information
   */
  getRunDetails: (id: string) => fetchApi<RunDetailResponse>(`/api/v1/runs/${id}`),

  /**
   * Get ordered steps with normalized schema
   */
  getRunSteps: (id: string) => fetchApi<RunStepsResponse>(`/api/v1/runs/${id}/steps`),

  /**
   * Advance a suspended run past a human gate
   */
  advanceRun: (id: string, data: AdvanceRunRequest) =>
    fetchApi<AdvanceRunResponse>(`/api/v1/runs/${id}/advance`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Retry a failed run (auto-detects failing step)
   */
  retryRun: (id: string) =>
    fetchApi<RetryRunResponse>(`/api/v1/runs/${id}/retry`, {
      method: 'POST',
    }),

  /**
   * Replay a run from a specific step
   */
  replayRun: (id: string, fromStep: number) =>
    fetchApi<ReplayRunResponse>(`/api/v1/runs/${id}/replay?from_step=${fromStep}`, {
      method: 'POST',
    }),

  /**
   * Get run summary with aggregated event metrics
   */
  getRunSummary: (runId: string) => fetchApi<RunSummary>(`/api/v1/runs/${runId}`),

  /**
   * Get events for a run with filtering and pagination
   */
  getRunEvents: (
    runId: string,
    options?: {
      event_type?: EventType[];
      since?: string; // ISO 8601
      until?: string; // ISO 8601
      severity?: Severity;
      limit?: number;
      cursor?: string;
    },
  ) => {
    const query = new URLSearchParams();
    if (options?.event_type) {
      options.event_type.forEach((t) => query.append('event_type', t));
    }
    if (options?.since) query.set('since', options.since);
    if (options?.until) query.set('until', options.until);
    if (options?.severity) query.set('severity', options.severity);
    if (options?.limit) query.set('limit', options.limit.toString());
    if (options?.cursor) query.set('cursor', options.cursor);

    return fetchApi<EventListResponse>(`/api/v1/runs/${runId}/events?${query}`);
  },

  // ========== Introspection Endpoints ==========

  /**
   * Get run graph with status overlay
   */
  getRunGraph: (id: string) => fetchApi<RunGraphResponse>(`/api/v1/runs/${id}/graph`),

  /**
   * List artifacts for a run
   */
  getRunArtifacts: (id: string, stepId?: string) => {
    const query = stepId ? `?step_id=${stepId}` : '';
    return fetchApi<ArtifactListResponse>(`/api/v1/runs/${id}/artifacts${query}`);
  },

  // ========== Credential Endpoints ==========

  /**
   * List all credentials (no secrets)
   */
  listCredentials: () => fetchApi<CredentialListResponse>('/api/v1/credentials'),

  /**
   * Create a new credential
   */
  createCredential: (data: CreateCredentialRequest) =>
    fetchApi<CredentialResponse>('/api/v1/credentials', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Update an existing credential
   */
  updateCredential: (name: string, data: UpdateCredentialRequest) =>
    fetchApi<CredentialResponse>(`/api/v1/credentials/${name}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  /**
   * Delete a credential
   */
  deleteCredential: (name: string) =>
    fetchApi<{ status: string; name: string }>(`/api/v1/credentials/${name}`, {
      method: 'DELETE',
    }),

  // ========== WebSocket ==========

  /**
   * Connect to WebSocket for live run event stream
   */
  connectRunEventStream: (
    runId: string,
    onEvent: (event: Event) => void,
    onError?: (error: globalThis.Event) => void,
    onClose?: () => void,
  ): WebSocket => {
    const ws = new WebSocket(`${WS_BASE_URL}/api/v1/runs/${runId}/stream`);

    ws.onmessage = (message) => {
      try {
        const data = JSON.parse(message.data);

        // Handle ping/connected messages
        if (data.type === 'ping' || data.type === 'connected') {
          return;
        }

        // Handle event objects
        onEvent(data as Event);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      onError?.(error);
    };

    ws.onclose = () => {
      console.log('WebSocket closed for run:', runId);
      onClose?.();
    };

    return ws;
  },
};
