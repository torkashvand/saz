'use client';

import { X, Activity, Shield, CheckCircle2, XCircle, TrendingUp } from 'lucide-react';
import type { TelemetryEvent } from '@/lib/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

interface TelemetryStepDrawerProps {
  stepId: string | null;
  events: TelemetryEvent[];
  onClose: () => void;
}

export function TelemetryStepDrawer({ stepId, events, onClose }: TelemetryStepDrawerProps) {
  if (!stepId) {
    return null;
  }

  // Filter events for this step
  const stepEvents = events.filter(
    (e) => 'step_id' in e && (e as any).step_id === stepId,
  );

  if (stepEvents.length === 0) {
    return null;
  }

  // Extract key events
  const groundedEvent = stepEvents.find((e) => e.type === 'trace.step.grounded') as any;
  const policyEvent = stepEvents.find((e) => e.type === 'trace.policy.check') as any;
  const toolStartEvent = stepEvents.find((e) => e.type === 'trace.tool.start') as any;
  const toolEndEvent = stepEvents.find((e) => e.type === 'trace.tool.end') as any;
  const critiqueEvent = stepEvents.find((e) => e.type === 'trace.critique') as any;
  const usageEvent = stepEvents.find((e) => e.type === 'trace.usage') as any;

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-background border-l shadow-2xl z-50 overflow-hidden flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <h3 className="font-semibold">Step Details</h3>
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {/* Step ID */}
        <div>
          <div className="text-xs text-muted-foreground mb-1">Step ID</div>
          <div className="text-sm font-mono bg-muted p-2 rounded">{stepId}</div>
        </div>

        {/* Intent */}
        {groundedEvent && (
          <div>
            <div className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
              <Activity className="w-3 h-3" />
              Intent
            </div>
            <div className="text-sm bg-muted p-2 rounded">{groundedEvent.intent}</div>
          </div>
        )}

        {/* Input Summary */}
        {groundedEvent && groundedEvent.input_summary && (
          <div>
            <div className="text-xs text-muted-foreground mb-1">Input Summary</div>
            <div className="text-xs font-mono bg-muted p-2 rounded break-words">
              {groundedEvent.input_summary}
            </div>
          </div>
        )}

        {/* Tool Info */}
        {toolStartEvent && (
          <div>
            <div className="text-xs text-muted-foreground mb-1">Tool</div>
            <div className="text-sm font-mono bg-muted p-2 rounded">
              {toolStartEvent.tool}
              {toolEndEvent && (
                <span className="ml-2 text-muted-foreground">
                  • {toolEndEvent.duration_ms.toFixed(0)}ms
                </span>
              )}
            </div>
          </div>
        )}

        {/* Policy Check */}
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
                <span
                  className={`font-medium ${policyEvent.allowed ? 'text-green-600' : 'text-red-600'}`}
                >
                  {policyEvent.allowed ? 'Allowed' : 'Blocked'}
                </span>
              </div>

              {policyEvent.reason && (
                <div>
                  <span className="text-muted-foreground">Reason: </span>
                  <span className="font-mono">{policyEvent.reason}</span>
                </div>
              )}

              {policyEvent.pii_stats && policyEvent.pii_stats.tokenized_count > 0 && (
                <div>
                  <span className="text-muted-foreground">PII Tokenized: </span>
                  <span className="font-semibold">{policyEvent.pii_stats.tokenized_count}</span>
                </div>
              )}

              {policyEvent.pii_stats && policyEvent.pii_stats.detokenized_paths.length > 0 && (
                <div>
                  <span className="text-muted-foreground">Detokenized Paths: </span>
                  <div className="font-mono text-xs mt-1 space-y-1">
                    {policyEvent.pii_stats.detokenized_paths.map((path: string) => (
                      <div key={path} className="bg-green-50 text-green-700 px-2 py-1 rounded">
                        {path}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {policyEvent.pii_stats && policyEvent.pii_stats.blocked_paths.length > 0 && (
                <div>
                  <span className="text-muted-foreground">Blocked Paths: </span>
                  <div className="font-mono text-xs mt-1 space-y-1">
                    {policyEvent.pii_stats.blocked_paths.map((path: string) => (
                      <div key={path} className="bg-red-50 text-red-700 px-2 py-1 rounded">
                        {path}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Critique */}
        {critiqueEvent && (
          <Card
            className={`border-l-4 ${
              critiqueEvent.verdict === 'PASS'
                ? 'border-l-green-500'
                : critiqueEvent.verdict === 'FAIL'
                  ? 'border-l-red-500'
                  : 'border-l-yellow-500'
            }`}
          >
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                {critiqueEvent.verdict === 'PASS' ? (
                  <CheckCircle2 className="w-4 h-4 text-green-600" />
                ) : (
                  <XCircle className="w-4 h-4 text-red-600" />
                )}
                Critique: {critiqueEvent.verdict}
              </CardTitle>
            </CardHeader>
            <CardContent className="text-xs space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Confidence</span>
                <span className="font-semibold">
                  {(critiqueEvent.confidence * 100).toFixed(0)}%
                </span>
              </div>

              {critiqueEvent.summary && (
                <div className="bg-muted p-2 rounded text-xs">{critiqueEvent.summary}</div>
              )}

              {critiqueEvent.issues.length > 0 && (
                <div>
                  <div className="text-muted-foreground mb-1">Issues:</div>
                  <div className="space-y-1">
                    {critiqueEvent.issues.map((issue: string, idx: number) => (
                      <div key={idx} className="bg-red-50 text-red-700 p-2 rounded text-xs">
                        {issue}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Usage */}
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
                <span className="font-semibold font-mono">{usageEvent.tokens.toLocaleString()}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Cost</span>
                <span className="font-semibold font-mono">${usageEvent.cost_usd.toFixed(4)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Duration</span>
                <span className="font-semibold font-mono">
                  {usageEvent.duration_ms.toFixed(0)}ms
                </span>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Tool Execution Timeline */}
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
                    className={`w-2 h-2 rounded-full ${toolEndEvent.status === 'success' ? 'bg-green-500' : 'bg-red-500'}`}
                  />
                  <span>
                    {toolEndEvent.status === 'success' ? 'Completed' : 'Failed'} at{' '}
                    {new Date(toolEndEvent.timestamp).toLocaleTimeString()}
                  </span>
                  {toolEndEvent.error_type && (
                    <span className="text-red-600">({toolEndEvent.error_type})</span>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
