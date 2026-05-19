/**
 * Tests for retry API calls — same-run lifecycle semantics.
 *
 * Covers:
 * - Retry sends valid JSON body and returns same run_id (not new_run_id)
 * - Response types match same-run contract (run_id, status)
 * - No navigation to a new run (no new_run_id in response)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mock fetch to inspect actual request parameters
// ---------------------------------------------------------------------------

const mockFetch = vi.fn();

// Save original and replace
beforeEach(() => {
  globalThis.fetch = mockFetch as any;
  mockFetch.mockReset();
});

async function callRetryRun(runId: string) {
  const { api } = await import('@/lib/api');
  return api.retryRun(runId);
}

// ---------------------------------------------------------------------------
// A. Retry sends a valid JSON body (same-run semantics)
// ---------------------------------------------------------------------------

describe('api.retryRun (same-run)', () => {
  it('sends POST with JSON body (not empty)', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({
        run_id: 'run-456',
        status: 'queued',
      }),
    });

    await callRetryRun('run-456');

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, options] = mockFetch.mock.calls[0];

    expect(url).toContain('/api/v1/runs/run-456/retry');
    expect(options.method).toBe('POST');
    expect(options.body).toBeDefined();
    expect(options.body).not.toBe('');

    const parsed = JSON.parse(options.body);
    expect(typeof parsed).toBe('object');
  });

  it('includes Content-Type: application/json header', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({
        run_id: 'run-456',
        status: 'queued',
      }),
    });

    await callRetryRun('run-456');

    const [, options] = mockFetch.mock.calls[0];
    expect(options.headers['Content-Type']).toBe('application/json');
  });

  it('returns response with run_id (not new_run_id)', async () => {
    const responseData = {
      run_id: 'run-xyz',
      status: 'queued',
    };

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => responseData,
    });

    const result = await callRetryRun('run-xyz');
    expect(result).toEqual(responseData);
    expect(result.run_id).toBe('run-xyz');
    // Same-run semantics: no new_run_id field
    expect((result as any).new_run_id).toBeUndefined();
  });

  it('throws on HTTP error (e.g. 422 from missing body)', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      headers: new Headers({ 'content-type': 'application/json' }),
      text: async () =>
        JSON.stringify({
          detail: [{ loc: ['body'], msg: 'field required', type: 'value_error.missing' }],
        }),
    });

    await expect(callRetryRun('bad-id')).rejects.toMatchObject({
      kind: 'validation',
      status: 422,
    });
  });
});

// ---------------------------------------------------------------------------
// B. Debug console.log regression — step-card must not log on import
// ---------------------------------------------------------------------------

describe('step-card debug logging', () => {
  it('getStepTypeIcon does not produce console output', async () => {
    const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

    await import('@/lib/runs/display-steps');

    expect(consoleSpy).not.toHaveBeenCalled();
    consoleSpy.mockRestore();
  });
});
