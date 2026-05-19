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
  ResumeRunRequest,
  ResumeRunResponse,
  RetryRunResponse,
  WebhookCallbackRequest,
  WebhookCallbackResponse,
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
  // Templates
  TemplateSummary,
  TemplateDetail,
  // Graph
  RunGraphResponse,
  // Legacy
  FlowGraphResponse,
} from './types';
import { fromHttpError, fromNetworkError, fromUnknownError } from './errors';
import { addBreadcrumb, captureAppError } from './monitoring';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
const WS_BASE_URL = API_BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://');
const DEFAULT_TIMEOUT = 30000; // 30 seconds

async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit,
  timeoutMs = DEFAULT_TIMEOUT
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const method = options?.method || 'GET';

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // Add breadcrumb for debugging
  addBreadcrumb(
    `API Request: ${method} ${endpoint}`,
    'api',
    {
      method,
      endpoint,
      hasBody: !!options?.body,
    }
  );

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const appError = await fromHttpError(response);

      // Add error breadcrumb
      addBreadcrumb(
        `API Error: ${response.status} ${endpoint}`,
        'api',
        {
          status: response.status,
          errorKind: appError.kind,
        }
      );

      // Capture server errors to Sentry
      if (response.status >= 500) {
        captureAppError(appError, {
          url: url,
          method,
          endpoint,
        });
      }

      throw appError;
    }

    // Add success breadcrumb
    addBreadcrumb(
      `API Success: ${method} ${endpoint}`,
      'api',
      { status: response.status }
    );

    // Handle empty responses (204, etc.)
    const contentType = response.headers.get('content-type');
    if (!contentType?.includes('application/json')) {
      return {} as T;
    }

    return await response.json();
  } catch (error) {
    clearTimeout(timeoutId);

    // If already an AppError, rethrow
    if (error && typeof error === 'object' && 'kind' in error) {
      throw error;
    }

    // Network/timeout errors
    if (error instanceof Error && (error.name === 'AbortError' || error.name === 'TypeError')) {
      const appError = fromNetworkError(error);
      captureAppError(appError, { url, method, endpoint });
      throw appError;
    }

    // Unknown errors
    const appError = fromUnknownError(error);
    captureAppError(appError, { url, method, endpoint });
    throw appError;
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
   * Advance a suspended run past a human gate (legacy)
   */
  advanceRun: (id: string, data: AdvanceRunRequest) =>
    fetchApi<AdvanceRunResponse>(`/api/v1/runs/${id}/advance`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Resume a suspended run (human approval / webhook wait)
   */
  resumeRun: (id: string, data: ResumeRunRequest) =>
    fetchApi<ResumeRunResponse>(`/api/v1/runs/${id}/resume`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Retry a failed run (auto-detects failing step)
   */
  retryRun: (id: string) =>
    fetchApi<RetryRunResponse>(`/api/v1/runs/${id}/retry`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  /**
   * Send an approve/reject callback to a suspended webhook.wait or
   * human.approval step. The callback_id is the run.error.callback_id of
   * the suspended run.
   */
  sendWebhookCallback: (callbackId: string, body: WebhookCallbackRequest) =>
    fetchApi<WebhookCallbackResponse>(
      `/api/v1/webhooks/callback/${callbackId}`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
    ),

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

  // ========== Templates ==========

  /**
   * List flow templates (built-in YAML examples shipped with the
   * backend). Pass recommended_only=true to filter to the
   * conference-ready wedge demos.
   */
  listTemplates: (params?: { recommendedOnly?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.recommendedOnly) query.set('recommended_only', 'true');
    const qs = query.toString();
    return fetchApi<TemplateSummary[]>(
      `/api/templates/${qs ? `?${qs}` : ''}`,
    );
  },

  /**
   * Fetch the full YAML + metadata for a single template by id.
   */
  getTemplate: (id: string) =>
    fetchApi<TemplateDetail>(`/api/templates/${encodeURIComponent(id)}`),

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

  // ========== Templates ==========

  /**
   * List available AI operations with default schemas
   */
  listAIOps: () => fetchApi<import('./types').AIOpReference[]>('/api/v1/flows/ai-ops'),
};
