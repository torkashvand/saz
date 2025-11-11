'use client';

import { Activity, Clock, DollarSign, Zap } from 'lucide-react';
import type { TelemetryProgressEvent, TelemetryUsageEvent } from '@/lib/types';
import { Card, CardContent } from '@/components/ui/card';

interface TelemetryProgressHeaderProps {
  progressEvent?: TelemetryProgressEvent;
  usageEvents: TelemetryUsageEvent[];
  runStatus: string;
  elapsedMs?: number;
}

export function TelemetryProgressHeader({
  progressEvent,
  usageEvents,
  runStatus,
  elapsedMs,
}: TelemetryProgressHeaderProps) {
  const totalTokens = usageEvents.reduce((sum, e) => sum + e.tokens, 0);
  const totalCost = usageEvents.reduce((sum, e) => sum + e.cost_usd, 0);
  const percent = progressEvent?.percent || 0;

  const statusColor = {
    running: 'bg-blue-100 text-blue-800 border-blue-300',
    completed: 'bg-green-100 text-green-800 border-green-300',
    failed: 'bg-red-100 text-red-800 border-red-300',
    suspended: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  }[runStatus] || 'bg-gray-100 text-gray-800 border-gray-300';

  return (
    <Card className="mb-4">
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <Activity className="w-5 h-5 text-muted-foreground" />
            <h2 className="text-lg font-semibold">Execution Console</h2>
          </div>
          <div className={`px-3 py-1 rounded-full text-sm font-medium border ${statusColor}`}>
            {runStatus.charAt(0).toUpperCase() + runStatus.slice(1)}
          </div>
        </div>

        {/* Progress bar */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">
              {progressEvent
                ? `${progressEvent.completed} / ${progressEvent.total} steps`
                : 'Waiting...'}
            </span>
            <span className="text-sm text-muted-foreground">{percent.toFixed(1)}%</span>
          </div>
          <div className="h-2 bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-300"
              style={{ width: `${Math.min(percent, 100)}%` }}
            />
          </div>
        </div>

        {/* Metrics grid */}
        <div className="grid grid-cols-3 gap-4">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-indigo-500" />
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">Tokens</div>
              <div className="text-sm font-semibold">{totalTokens.toLocaleString()}</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <DollarSign className="w-4 h-4 text-green-500" />
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">Cost</div>
              <div className="text-sm font-semibold">${totalCost.toFixed(4)}</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-amber-500" />
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">Elapsed</div>
              <div className="text-sm font-semibold">
                {elapsedMs ? formatDuration(elapsedMs) : '—'}
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${ms.toFixed(0)}ms`;
  } else if (ms < 60000) {
    return `${(ms / 1000).toFixed(1)}s`;
  } else {
    const minutes = Math.floor(ms / 60000);
    const seconds = ((ms % 60000) / 1000).toFixed(0);
    return `${minutes}m ${seconds}s`;
  }
}
