import type {
  // Flows
  FlowListResponse,
  RegisterFlowRequest,
  RegisterFlowResponse,
  CompileFlowRequest,
  CompileFlowResponse,
  FlowLintResponse,
  FlowDetailResponse,
  UpdateFlowRequest,
  DslMetadata,
  // Runs
  RunListResponse,
  CreateRunRequest,
  CreateRunResponse,
  RunDetailResponse,
  RunStepsResponse,
  ResumeRunRequest,
  ResumeRunResponse,
  RetryRunResponse,
  StreamTicketResponse,
  WebhookCallbackRequest,
  WebhookCallbackResponse,
  // Events
  Event,
  EventListResponse,
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
  // Auth
  LoginRequest,
  ChangePasswordRequest,
  TokenResponse,
  CurrentUser,
  UserRole,
  PublicProvider,
  AuthProvider,
  AuthProviderListResponse,
  CreateAuthProviderRequest,
  UpdateAuthProviderRequest,
  ProviderTestResult,
  // Admin
  AdminUser,
  AdminUserListResponse,
  AdminCreateUserRequest,
  AdminUpdateUserRequest,
  AdminSessionListResponse,
} from './types';
import { fromHttpError, fromNetworkError, fromUnknownError } from './errors';
import { captureAppError } from './monitoring';
import { getAccessToken, _internalAuth } from './auth';

// Single client-side home for the API origin. (The OIDC route handler keeps
// its own copy — it runs server-side and must not import this client module.)
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
const WS_BASE_URL = API_BASE_URL.replace('http://', 'ws://').replace('https://', 'wss://');
const DEFAULT_TIMEOUT = 30000; // 30 seconds

// Single-flight silent refresh: exchange the HttpOnly refresh cookie for a
// fresh access token. Concurrent 401s share one in-flight refresh so we don't
// stampede the endpoint or rotate the cookie multiple times.
let _refreshInFlight: Promise<boolean> | null = null;

async function tryRefreshAccessToken(): Promise<boolean> {
  if (!_refreshInFlight) {
    _refreshInFlight = (async () => {
      try {
        const resp = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        });
        if (!resp.ok) return false;
        const data = (await resp.json()) as TokenResponse;
        _internalAuth.setAccessToken(data.access_token);
        return true;
      } catch {
        return false;
      } finally {
        _refreshInFlight = null;
      }
    })();
  }
  return _refreshInFlight;
}

// A silent refresh must only be skipped for the endpoints that mint/rotate the
// session itself — refreshing on a failed login/refresh would recurse. Every
// OTHER auth endpoint (/me, /change_password, /logout, …) benefits from the
// replay just like the rest of the API.
function skipSilentRefresh(endpoint: string): boolean {
  return endpoint.startsWith('/api/v1/auth/refresh') || endpoint.startsWith('/api/v1/auth/login');
}

/**
 * Authenticated fetch with a one-shot silent-refresh replay and a timeout.
 * Returns the raw Response (caller inspects `.ok`); throws an AppError on
 * network/timeout failures. Shared by the JSON wrapper and binary downloads
 * so both get identical auth/refresh/timeout behavior.
 */
async function authedFetch(
  endpoint: string,
  options?: RequestInit,
  timeoutMs = DEFAULT_TIMEOUT,
  retried = false,
): Promise<Response> {
  const url = `${API_BASE_URL}${endpoint}`;
  const method = options?.method || 'GET';

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const token = getAccessToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...((options?.headers as Record<string, string>) || {}),
    };

    const response = await fetch(url, {
      ...options,
      headers,
      // Send/receive the HttpOnly refresh cookie. Requires the API to set
      // CORS allow_credentials + an explicit origin (it does).
      credentials: 'include',
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    // On a 401, try one silent refresh and replay the request.
    if (response.status === 401 && !retried && !skipSilentRefresh(endpoint)) {
      if (await tryRefreshAccessToken()) {
        return authedFetch(endpoint, options, timeoutMs, true);
      }
    }

    return response;
  } catch (error) {
    clearTimeout(timeoutId);

    if (error && typeof error === 'object' && 'kind' in error) {
      throw error;
    }
    if (error instanceof Error && (error.name === 'AbortError' || error.name === 'TypeError')) {
      const appError = fromNetworkError(error);
      captureAppError(appError, { url, method, endpoint });
      throw appError;
    }
    const appError = fromUnknownError(error);
    captureAppError(appError, { url, method, endpoint });
    throw appError;
  }
}

async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit,
  timeoutMs = DEFAULT_TIMEOUT,
): Promise<T> {
  const response = await authedFetch(endpoint, options, timeoutMs);
  const method = options?.method || 'GET';

  if (!response.ok) {
    const appError = await fromHttpError(response);
    // Log server errors for debugging
    if (response.status >= 500) {
      captureAppError(appError, { url: `${API_BASE_URL}${endpoint}`, method, endpoint });
    }
    throw appError;
  }

  // Handle empty responses. A 204 carries no JSON even when the server tags
  // it application/json; calling response.json() on it throws "Unexpected end
  // of JSON input", so short-circuit before parsing.
  if (response.status === 204) {
    return {} as T;
  }
  const contentType = response.headers.get('content-type');
  if (!contentType?.includes('application/json')) {
    return {} as T;
  }

  return await response.json();
}

export const api = {
  // ========== Auth ==========

  /**
   * Exchange username-or-email + password for a JWT access token.
   */
  login: (data: LoginRequest) =>
    fetchApi<TokenResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * Return the currently-authenticated user. Used to bootstrap the
   * session on page reload.
   */
  getCurrentUser: () => fetchApi<CurrentUser>('/api/v1/auth/me'),

  /**
   * Self-service password change. Required after an admin reset (the
   * backend gates all operational endpoints until the user picks a new
   * password).
   */
  changePassword: (data: ChangePasswordRequest) =>
    fetchApi<CurrentUser>('/api/v1/auth/change_password', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** Exchange the refresh cookie for a fresh access token. */
  refreshSession: () => fetchApi<TokenResponse>('/api/v1/auth/refresh', { method: 'POST' }),

  /** Revoke the current refresh session server-side. */
  logout: () => fetchApi<void>('/api/v1/auth/logout', { method: 'POST' }),

  /** Enabled SSO providers for the login screen (unauthenticated). */
  listPublicProviders: () => fetchApi<PublicProvider[]>('/api/v1/auth/providers'),

  // ========== Admin: OIDC providers (admin-only) ==========

  listAuthProviders: () => fetchApi<AuthProviderListResponse>('/api/v1/admin/auth/providers'),

  createAuthProvider: (data: CreateAuthProviderRequest) =>
    fetchApi<AuthProvider>('/api/v1/admin/auth/providers', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateAuthProvider: (id: string, data: UpdateAuthProviderRequest) =>
    fetchApi<AuthProvider>(`/api/v1/admin/auth/providers/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  deleteAuthProvider: (id: string) =>
    fetchApi<void>(`/api/v1/admin/auth/providers/${id}`, { method: 'DELETE' }),

  testAuthProvider: (id: string) =>
    fetchApi<ProviderTestResult>(`/api/v1/admin/auth/providers/${id}/test`, { method: 'POST' }),

  // ========== Admin: User management (admin-only) ==========

  listUsers: () => fetchApi<AdminUserListResponse>('/api/v1/admin/users'),

  getUser: (id: string) => fetchApi<AdminUser>(`/api/v1/admin/users/${id}`),

  createUser: (data: AdminCreateUserRequest) =>
    fetchApi<AdminUser>('/api/v1/admin/users', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateUser: (id: string, data: AdminUpdateUserRequest) =>
    fetchApi<AdminUser>(`/api/v1/admin/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  setUserActive: (id: string, isActive: boolean) =>
    fetchApi<AdminUser>(`/api/v1/admin/users/${id}/set_active`, {
      method: 'POST',
      body: JSON.stringify({ is_active: isActive }),
    }),

  setUserRole: (id: string, role: UserRole) =>
    fetchApi<AdminUser>(`/api/v1/admin/users/${id}/set_role`, {
      method: 'POST',
      body: JSON.stringify({ role }),
    }),

  resetUserPassword: (id: string, temporaryPassword: string) =>
    fetchApi<AdminUser>(`/api/v1/admin/users/${id}/reset_password`, {
      method: 'POST',
      body: JSON.stringify({ temporary_password: temporaryPassword }),
    }),

  /** List a user's active refresh sessions (admin). */
  listUserSessions: (id: string) =>
    fetchApi<AdminSessionListResponse>(`/api/v1/admin/users/${id}/sessions`),

  /** Revoke one of a user's sessions (admin). */
  revokeUserSession: (id: string, sessionId: string) =>
    fetchApi<void>(`/api/v1/admin/users/${id}/sessions/${sessionId}`, { method: 'DELETE' }),

  /** Revoke all of a user's sessions (admin). */
  revokeAllUserSessions: (id: string) =>
    fetchApi<{ revoked: number }>(`/api/v1/admin/users/${id}/sessions`, { method: 'DELETE' }),

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
   * Lint YAML DSL for prose↔contract consistency without registering
   */
  lintFlow: (data: { yaml: string }) =>
    fetchApi<FlowLintResponse>('/api/v1/flows/lint', {
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
   * Update an existing flow by ID. Use this in edit mode so renaming a
   * flow doesn't create a new row.
   */
  updateFlow: (id: string, data: UpdateFlowRequest) =>
    fetchApi<RegisterFlowResponse>(`/api/v1/flows/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  /**
   * Get full flow metadata
   */
  getFlow: (id: string) => fetchApi<FlowDetailResponse>(`/api/v1/flows/${id}`),

  /**
   * Get the centralized DSL metadata payload (supported step types,
   * field constraints, expression helpers, registered tools).
   */
  getDslMetadata: () => fetchApi<DslMetadata>('/api/v1/flows/dsl-metadata'),

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
    fetchApi<WebhookCallbackResponse>(`/api/v1/webhooks/callback/${callbackId}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

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
   * List artifacts for a run
   */
  getRunArtifacts: (id: string, stepId?: string) => {
    const query = stepId ? `?step_id=${encodeURIComponent(stepId)}` : '';
    return fetchApi<ArtifactListResponse>(`/api/v1/runs/${id}/artifacts${query}`);
  },

  /**
   * Download an artifact's file. The endpoint requires the Bearer token, so a
   * plain <a download> won't work — fetch with auth, then trigger a Blob save.
   * Routed through authedFetch so it gets the same silent-refresh, timeout,
   * and AppError contract as every other endpoint.
   */
  downloadArtifact: async (runId: string, artifactId: string, filename: string) => {
    const res = await authedFetch(`/api/v1/runs/${runId}/artifacts/${artifactId}/download`);
    if (!res.ok) throw await fromHttpError(res);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
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
    return fetchApi<TemplateSummary[]>(`/api/templates/${qs ? `?${qs}` : ''}`);
  },

  /**
   * Fetch the full YAML + metadata for a single template by id.
   */
  getTemplate: (id: string) => fetchApi<TemplateDetail>(`/api/templates/${encodeURIComponent(id)}`),

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
    fetchApi<CredentialResponse>(`/api/v1/credentials/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  /**
   * Delete a credential
   */
  deleteCredential: (name: string) =>
    fetchApi<{ status: string; name: string }>(`/api/v1/credentials/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  // ========== WebSocket ==========

  /**
   * Connect to WebSocket for live run event stream.
   *
   * Browsers can't set Authorization headers on a WS upgrade, and query
   * strings land in proxy/server logs — so instead of the long-lived access
   * token, the authed HTTP channel is used to mint a short-lived ticket
   * scoped to this one run, and THAT rides the URL.
   */
  connectRunEventStream: async (
    runId: string,
    onEvent: (event: Event) => void,
    onError?: (error: globalThis.Event) => void,
    onClose?: () => void,
    onGap?: () => void,
  ): Promise<WebSocket> => {
    const { ticket } = await fetchApi<StreamTicketResponse>(`/api/v1/runs/${runId}/stream_ticket`, {
      method: 'POST',
    });
    const ws = new WebSocket(
      `${WS_BASE_URL}/api/v1/runs/${runId}/stream?ticket=${encodeURIComponent(ticket)}`,
    );

    ws.onmessage = (message) => {
      try {
        const data = JSON.parse(message.data);

        // Handle control messages (keepalive, connect ack, snapshot boundary).
        // Snapshot events themselves carry event_type and flow through as
        // normal events (with a `snapshot: true` flag) so the run view can
        // replay prior state on connect.
        if (
          data.type === 'ping' ||
          data.type === 'connected' ||
          data.type === 'snapshot_complete'
        ) {
          return;
        }

        // The server dropped events for this (slow) consumer; canonical state
        // must be refetched from REST rather than trusting the live overlay.
        if (data.type === 'gap') {
          onGap?.();
          return;
        }

        // Handle event objects
        onEvent(data as Event);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    ws.onerror = (error) => {
      // A bare WebSocket error Event carries no actionable detail, and an
      // intentional teardown (component unmount / navigation closing a still-
      // CONNECTING socket) also fires this. Let the caller decide how to
      // log/report it — see useRunEvents, which suppresses teardown noise.
      onError?.(error);
    };

    ws.onclose = () => {
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
