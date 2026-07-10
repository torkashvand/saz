import { useEffect, useMemo, useState } from 'react';
import { latestAttemptsByName } from './runs/display-steps';
import type { RunDetailResponse } from './types';

export interface RunMetrics {
  totalSteps: number;
  totalTokens: number | null;
  totalCost: number | null;
  durationMs: number | null;
  completedSteps: number;
  failedSteps: number;
  runningSteps: number;
}

/**
 * Calculate accurate metrics from run data.
 *
 * Key UX decisions:
 * - Return null instead of 0 when data is truly unavailable
 * - Aggregate from steps when run-level data is missing (data consistency fix)
 * - Handle running runs with live duration calculation
 */
export function useRunMetrics(run: RunDetailResponse | undefined): RunMetrics {
  // Tick once a second while the run is live so the Duration card counts up
  // instead of freezing at whatever Date.now() was on the last refetch.
  const [now, setNow] = useState(() => Date.now());
  const isLive = run?.status === 'running' && !!run.started_at && !run.completed_at;
  useEffect(() => {
    if (!isLive) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [isLive]);

  return useMemo(() => {
    if (!run) {
      return {
        totalSteps: 0,
        totalTokens: null,
        totalCost: null,
        durationMs: null,
        completedSteps: 0,
        failedSteps: 0,
        runningSteps: 0,
      };
    }

    const steps = run.steps || [];

    // Status counts reflect the run's EFFECTIVE state: after a retry the run
    // keeps historical attempt rows, and counting them all would keep showing
    // an old failed attempt as a current failure. Only the latest attempt per
    // step name is authoritative. (Tokens/cost below intentionally sum ALL
    // attempts — every attempt spent them.)
    const effectiveSteps = latestAttemptsByName(steps);
    const completedSteps = effectiveSteps.filter((s) => s.status === 'completed').length;
    const failedSteps = effectiveSteps.filter((s) => s.status === 'failed').length;
    const runningSteps = effectiveSteps.filter(
      (s) => s.status === 'running' || s.status === 'queued',
    ).length;

    // Calculate tokens: prefer run.total_tokens, fallback to sum of steps
    let totalTokens: number | null = null;
    if (run.total_tokens != null && run.total_tokens > 0) {
      totalTokens = run.total_tokens;
    } else {
      // Aggregate from steps
      const stepsWithTokens = steps.filter((s) => s.tokens != null && s.tokens > 0);
      if (stepsWithTokens.length > 0) {
        totalTokens = stepsWithTokens.reduce((sum, s) => sum + (s.tokens || 0), 0);
      }
    }

    // Calculate cost: prefer run.total_cost_usd, fallback to sum of steps
    let totalCost: number | null = null;
    if (run.total_cost_usd != null && run.total_cost_usd > 0) {
      totalCost = run.total_cost_usd;
    } else {
      // Aggregate from steps
      const stepsWithCost = steps.filter((s) => s.cost_usd != null && s.cost_usd > 0);
      if (stepsWithCost.length > 0) {
        totalCost = stepsWithCost.reduce((sum, s) => sum + (s.cost_usd || 0), 0);
      }
    }

    // Calculate duration: wall-clock time from start to end (or now if the
    // run hasn't ended). Suspended/failed runs without completed_at started
    // too — show elapsed-so-far rather than the misleading "Not started".
    let durationMs: number | null = null;
    if (run.started_at) {
      durationMs = run.completed_at
        ? new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()
        : now - new Date(run.started_at).getTime();
    } else if (run.duration_ms != null) {
      // Fallback to backend-provided duration
      durationMs = run.duration_ms;
    }

    return {
      totalSteps: effectiveSteps.length,
      totalTokens,
      totalCost,
      durationMs,
      completedSteps,
      failedSteps,
      runningSteps,
    };
  }, [run, now]);
}
