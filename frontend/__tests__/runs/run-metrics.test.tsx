/**
 * useRunMetrics must reflect the run's EFFECTIVE state after retry.
 *
 * A retried run keeps historical step rows (same-run retry preserves all
 * attempts). Counting every attempt inflates totals and — worse — keeps
 * showing an old failed attempt as a current failure after the retry
 * succeeded. Status counts must dedupe to the latest attempt per step name.
 * Tokens/cost intentionally aggregate ALL attempts: every attempt spent
 * real tokens and money (matches backend budget semantics).
 */

import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useRunMetrics } from '@/lib/use-run-metrics';
import type { RunDetailResponse, RunStep } from '@/lib/types';

function step(
  name: string,
  attempt: number,
  status: RunStep['status'],
  extras: Partial<RunStep> = {},
): RunStep {
  return {
    id: `db-${name}-a${attempt}`,
    number: 0,
    name,
    attempt,
    step_type: 'tool.call',
    status,
    retry_count: 0,
    ...extras,
  };
}

function makeRun(steps: RunStep[]): RunDetailResponse {
  return {
    id: 'run_1',
    flow_id: 'flow_1',
    flow_name: 'flow',
    status: 'completed',
    planner_mode: 'deterministic',
    payload: {},
    created_at: '2026-07-10T10:00:00Z',
    started_at: '2026-07-10T10:00:00Z',
    completed_at: '2026-07-10T10:01:00Z',
    total_tokens: 0,
    total_cost_usd: 0,
    planned_steps: [],
    steps,
  };
}

describe('useRunMetrics — retry attempt dedupe', () => {
  it('REGRESSION: a step that failed then succeeded on retry is not counted as failed', () => {
    const run = makeRun([
      step('extract', 1, 'failed'),
      step('extract', 2, 'completed'),
      step('notify', 1, 'completed'),
    ]);

    const { result } = renderHook(() => useRunMetrics(run));

    // 2 workflow steps, both effectively completed; the historical failed
    // attempt must not surface as a current failure.
    expect(result.current.totalSteps).toBe(2);
    expect(result.current.completedSteps).toBe(2);
    expect(result.current.failedSteps).toBe(0);
    expect(result.current.runningSteps).toBe(0);
  });

  it('a step whose LATEST attempt failed still counts as failed', () => {
    const run = makeRun([step('extract', 1, 'failed'), step('extract', 2, 'failed')]);

    const { result } = renderHook(() => useRunMetrics(run));

    expect(result.current.totalSteps).toBe(1);
    expect(result.current.failedSteps).toBe(1);
    expect(result.current.completedSteps).toBe(0);
  });

  it('tokens and cost aggregate ALL attempts (every attempt spent them)', () => {
    const run = makeRun([
      step('extract', 1, 'failed', { tokens: 100, cost_usd: 0.5 }),
      step('extract', 2, 'completed', { tokens: 50, cost_usd: 0.25 }),
      step('notify', 1, 'completed', { tokens: 25, cost_usd: 0.1 }),
    ]);

    const { result } = renderHook(() => useRunMetrics(run));

    expect(result.current.totalTokens).toBe(175);
    expect(result.current.totalCost).toBeCloseTo(0.85);
  });

  it('no retry: counts are unchanged', () => {
    const run = makeRun([
      step('extract', 1, 'completed'),
      step('draft', 1, 'running'),
      step('notify', 1, 'failed'),
    ]);

    const { result } = renderHook(() => useRunMetrics(run));

    expect(result.current.totalSteps).toBe(3);
    expect(result.current.completedSteps).toBe(1);
    expect(result.current.runningSteps).toBe(1);
    expect(result.current.failedSteps).toBe(1);
  });
});
