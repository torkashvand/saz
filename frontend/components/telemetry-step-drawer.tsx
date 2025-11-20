'use client';

import { X, Activity, Shield, CheckCircle2, XCircle, TrendingUp } from 'lucide-react';
import type { Event } from '@/lib/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

interface TelemetryStepDrawerProps {
  stepId: string | null;
  events: Event[];
  onClose: () => void;
}

export function TelemetryStepDrawer({ stepId, events, onClose }: TelemetryStepDrawerProps) {
  if (!stepId) {
    return null;
  }

  const stepEvents = events.filter((e) => e.step_id === stepId);

  if (stepEvents.length === 0) {
    return null;
  }

  const startEvent = stepEvents.find((e) => e.event_type === 'step.started');
  const policyEvent = stepEvents.find((e) => e.event_type.startsWith('policy.'));
  const toolStartEvent = stepEvents.find((e) => e.event_type === 'tool.started');
  const toolEndEvent = stepEvents.find((e) => e.event_type === 'tool.succeeded' || e.event_type === 'tool.failed');
  const errorEvent = stepEvents.find((e) => e.event_type === 'system.error');
  const usageEvent = stepEvents.find((e) => e.event_type === 'usage.recorded');

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-background border-l shadow-2xl z-50 overflow-hidden flex flex-col">
      <div className="flex items-center justify-between p-4 border-b">
        <h3 className="font-semibold">Step Details</h3>
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-auto p-4 space-y-4">
        <div>
          <div className="text-xs text-muted-foreground mb-1">Step ID</div>
          <div className="text-sm font-mono bg-muted p-2 rounded">{stepId}</div>
        </div>

        {startEvent && (
          <div>
            <div className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
              <Activity className="w-3 h-3" />
              Summary
            </div>
            <div className="text-sm bg-muted p-2 rounded">{startEvent.summary}</div>
          </div>
        )}

        {toolStartEvent && (
          <div>
            <div className="text-xs text-muted-foreground mb-1">Tool</div>
            <div className="text-sm font-mono bg-muted p-2 rounded">
              {toolStartEvent.payload?.tool}
              {toolEndEvent && (
                <span className="ml-2 text-muted-foreground">
                  • {toolEndEvent.payload?.duration_ms?.toFixed(0)}ms
                </span>
              )}
            </div>
          </div>
        )}

        {policyEvent && (
          <Card className="border-l-4 border-l-blue-500">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <Shield className="w-4 h-4" />
                Policy Check
              </CardTitle>
            </CardHeader>
            <CardContent className="text-xs space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Status</span>
                <span className={`font-medium ${policyEvent.event_type === 'policy.blocked' ? 'text-red-600' : 'text-green-600'}`}>
                  {policyEvent.event_type === 'policy.blocked' ? 'Blocked' : 'Allowed'}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Reason: </span>
                <span className="font-mono">{policyEvent.summary}</span>
              </div>
            </CardContent>
          </Card>
        )}

        {errorEvent && (
          <Card className="border-l-4 border-l-red-500">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <XCircle className="w-4 h-4 text-red-600" />
                Error
              </CardTitle>
            </CardHeader>
            <CardContent className="text-xs space-y-2">
              <div className="bg-red-50 text-red-700 p-2 rounded">{errorEvent.summary}</div>
              {errorEvent.payload?.details && (
                <div className="bg-muted p-2 rounded text-xs font-mono">{errorEvent.payload.details}</div>
              )}
            </CardContent>
          </Card>
        )}

        {usageEvent && (
          <Card className="border-l-4 border-l-indigo-500">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <TrendingUp className="w-4 h-4" />
                Resource Usage
              </CardTitle>
            </CardHeader>
            <CardContent className="text-xs space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Tokens</span>
                <span className="font-semibold font-mono">{usageEvent.payload?.tokens?.toLocaleString()}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Cost</span>
                <span className="font-semibold font-mono">${usageEvent.payload?.cost_usd?.toFixed(4)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Duration</span>
                <span className="font-semibold font-mono">
                  {usageEvent.payload?.duration_ms?.toFixed(0)}ms
                </span>
              </div>
            </CardContent>
          </Card>
        )}

        {(toolStartEvent || toolEndEvent) && (
          <div>
            <div className="text-xs text-muted-foreground mb-2">Execution Timeline</div>
            <div className="space-y-2">
              {toolStartEvent && (
                <div className="flex items-center gap-2 text-xs">
                  <div className="w-2 h-2 bg-cyan-500 rounded-full" />
                  <span>Started at {new Date(toolStartEvent.timestamp).toLocaleTimeString()}</span>
                </div>
              )}
              {toolEndEvent && (
                <div className="flex items-center gap-2 text-xs">
                  <div
                    className={`w-2 h-2 rounded-full ${toolEndEvent.event_type === 'tool.succeeded' ? 'bg-green-500' : 'bg-red-500'}`}
                  />
                  <span>
                    {toolEndEvent.event_type === 'tool.succeeded' ? 'Completed' : 'Failed'} at{' '}
                    {new Date(toolEndEvent.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
