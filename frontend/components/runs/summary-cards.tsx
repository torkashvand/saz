import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { RunMetrics } from '@/lib/use-run-metrics';

interface RunSummaryCardsProps {
  metrics: RunMetrics;
  isRunning: boolean;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function formatCost(cost: number): string {
  return `$${cost.toFixed(4)}`;
}

/**
 * Display summary metrics for a run.
 *
 * UX decision: Show "Not available" instead of misleading zeros
 * when data is truly missing. This prevents confusion for operators
 * reviewing failed or incomplete runs.
 */
export function RunSummaryCards({ metrics, isRunning }: RunSummaryCardsProps) {
  return (
    <div className="grid grid-cols-4 gap-4">
      {/* Steps count */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-medium text-slate-500">Steps</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold text-slate-900">{metrics.totalSteps}</p>
          {metrics.totalSteps > 0 && (
            <p className="text-xs text-slate-500 mt-1">
              {metrics.completedSteps} completed
              {metrics.failedSteps > 0 && (
                <span className="text-red-600 font-medium">, {metrics.failedSteps} failed</span>
              )}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Total tokens */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-medium text-slate-500">Total Tokens</CardTitle>
        </CardHeader>
        <CardContent>
          {metrics.totalTokens != null ? (
            <p className="text-2xl font-bold text-slate-900">
              {metrics.totalTokens.toLocaleString()}
            </p>
          ) : (
            <p className="text-lg text-slate-400">Not available</p>
          )}
        </CardContent>
      </Card>

      {/* Total cost */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-medium text-slate-500">Total Cost</CardTitle>
        </CardHeader>
        <CardContent>
          {metrics.totalCost != null ? (
            <p className="text-2xl font-bold text-slate-900">
              {formatCost(metrics.totalCost)}
            </p>
          ) : (
            <p className="text-lg text-slate-400">Not available</p>
          )}
        </CardContent>
      </Card>

      {/* Duration */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-medium text-slate-500">
            Duration {isRunning && <span className="text-blue-500 animate-pulse">●</span>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {metrics.durationMs != null ? (
            <p className="text-2xl font-bold text-slate-900">
              {formatDuration(metrics.durationMs)}
            </p>
          ) : (
            <p className="text-lg text-slate-400">Not started</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
