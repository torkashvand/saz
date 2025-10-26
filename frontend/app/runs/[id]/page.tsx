'use client'

import { useParams } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useRunDetails, useRunGraph } from '@/lib/hooks'
import { Loader2, CheckCircle2, XCircle, Clock, Play } from 'lucide-react'
import { WorkflowGraph } from '@/components/workflow-graph'
import { CollapsibleJson } from '@/components/json-view'
import type { Step, StepStatus } from '@/lib/types'

const STATUS_ICONS: Record<StepStatus, React.ReactNode> = {
  pending: <Clock className="h-5 w-5 text-slate-400" />,
  running: <Play className="h-5 w-5 text-blue-500 animate-pulse" />,
  success: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  failed: <XCircle className="h-5 w-5 text-red-500" />,
  suspended: <Clock className="h-5 w-5 text-amber-500" />,
}

const STATUS_COLORS: Record<StepStatus, string> = {
  pending: 'bg-slate-200',
  running: 'bg-blue-500',
  success: 'bg-green-500',
  failed: 'bg-red-500',
  suspended: 'bg-amber-500',
}

function formatDuration(ms?: number): string {
  if (!ms) return '-'
  if (ms < 1000) return `${ms}ms`
  const seconds = (ms / 1000).toFixed(2)
  return `${seconds}s`
}

function formatCost(cost?: number): string {
  if (!cost) return '-'
  return `$${cost.toFixed(4)}`
}

function StepTimeline({ steps }: { steps: Step[] }) {
  return (
    <div className="space-y-3">
      {steps.map((step, idx) => (
        <div key={step.id} className="relative">
          {/* Vertical line connecting steps */}
          {idx < steps.length - 1 && (
            <div className="absolute left-[10px] top-[32px] w-[2px] h-[calc(100%+12px)] bg-slate-200" />
          )}

          <div className="flex items-start gap-3">
            {/* Status indicator */}
            <div className="relative z-10 flex-shrink-0">
              {STATUS_ICONS[step.status]}
            </div>

            {/* Step content */}
            <div className="flex-1 border rounded-lg overflow-hidden">
              <div className="bg-muted px-3 py-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{step.id}</span>
                  <span className="text-xs text-muted-foreground">({step.type})</span>
                </div>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  {step.duration_ms && <span>{formatDuration(step.duration_ms)}</span>}
                  {step.tokens && <span>{step.tokens} tokens</span>}
                  {step.cost_usd && <span>{formatCost(step.cost_usd)}</span>}
                </div>
              </div>

              {/* Expandable input/output */}
              <div className="p-3 space-y-2">
                {step.input && <CollapsibleJson label="Input" data={step.input} />}
                {step.output && <CollapsibleJson label="Output" data={step.output} defaultOpen />}

                {/* Show failure reason if step failed */}
                {step.failure && (
                  <div className="border-l-4 border-red-500 bg-red-50 p-3 rounded space-y-2">
                    <div>
                      <p className="text-xs font-medium text-red-900 mb-1">Failure Reason</p>
                      <p className="text-xs text-red-700">{step.failure.message}</p>
                    </div>

                    {step.failure.issues && step.failure.issues.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-red-900 mb-1">Issues</p>
                        <ul className="list-disc list-inside text-xs text-red-700 space-y-1">
                          {step.failure.issues.map((issue, i) => (
                            <li key={i}>{issue}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {step.failure.raw_critique && (
                      <CollapsibleJson label="Critique Details" data={step.failure.raw_critique} />
                    )}
                  </div>
                )}

                {/* Legacy error field */}
                {step.error && !step.failure && (
                  <div className="border-l-4 border-red-500 bg-red-50 p-3 rounded">
                    <p className="text-xs font-medium text-red-900 mb-1">Error</p>
                    <p className="text-xs text-red-700">{step.error}</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function RunDetailPage() {
  const params = useParams()
  const runId = params.id as string

  const { data: run, isLoading: isLoadingRun } = useRunDetails(runId)
  const { data: runGraph, isLoading: isLoadingGraph } = useRunGraph(runId)

  if (isLoadingRun) {
    return (
      <div className="container mx-auto px-4 py-12 flex justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  if (!run) {
    return (
      <div className="container mx-auto px-4 py-12">
        <Card>
          <CardHeader>
            <CardTitle>Run Not Found</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">The run with ID {runId} could not be found.</p>
          </CardContent>
        </Card>
      </div>
    )
  }

  const isRunning = run.status === 'running' || run.status === 'pending'

  // Determine status display
  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'failed': return 'Failed'
      case 'suspended': return 'Needs Review'
      case 'success': return 'Succeeded'
      case 'running': return 'Running'
      case 'pending': return 'Pending'
      default: return status
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'failed': return 'bg-red-100 text-red-800 border-red-300'
      case 'suspended': return 'bg-amber-100 text-amber-800 border-amber-300'
      case 'success': return 'bg-green-100 text-green-800 border-green-300'
      case 'running': return 'bg-blue-100 text-blue-800 border-blue-300'
      case 'pending': return 'bg-slate-100 text-slate-800 border-slate-300'
      default: return 'bg-slate-100 text-slate-800 border-slate-300'
    }
  }

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-3xl font-bold">Run Details</h1>
          <div className={`px-3 py-1 rounded-full text-sm font-medium border ${getStatusColor(run.status)}`}>
            {getStatusLabel(run.status)}
          </div>
        </div>
        <p className="text-sm text-muted-foreground font-mono">{runId}</p>

        {run.failure_reason && (
          <div className="mt-2 p-3 bg-red-50 border-l-4 border-red-500 rounded">
            <p className="text-sm font-medium text-red-900">Run Failed</p>
            <p className="text-sm text-red-700 mt-1">{run.failure_reason}</p>
            {run.failing_step_id && (
              <p className="text-xs text-red-600 mt-1">Failed at step: {run.failing_step_id}</p>
            )}
          </div>
        )}

        {isRunning && (
          <p className="text-xs text-blue-600 mt-1 flex items-center gap-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            Polling for updates every 2 seconds...
          </p>
        )}
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-muted-foreground">Steps</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{run.steps.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-muted-foreground">Total Tokens</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{run.totals.tokens.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-muted-foreground">Total Cost</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{formatCost(run.totals.cost_usd)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs text-muted-foreground">Duration</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-lg font-bold">
              {run.started_at && run.completed_at
                ? formatDuration(
                    new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()
                  )
                : '-'}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="timeline" className="w-full">
        <TabsList className="w-full">
          <TabsTrigger value="timeline" className="flex-1">Timeline</TabsTrigger>
          <TabsTrigger value="graph" className="flex-1">Graph</TabsTrigger>
          <TabsTrigger value="artifacts" className="flex-1">
            Artifacts {run.artifacts.length > 0 && `(${run.artifacts.length})`}
          </TabsTrigger>
          <TabsTrigger value="cost" className="flex-1">Cost Breakdown</TabsTrigger>
        </TabsList>

        <TabsContent value="timeline" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Step Timeline</CardTitle>
            </CardHeader>
            <CardContent>
              <StepTimeline steps={run.steps} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="graph" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Workflow Graph</CardTitle>
            </CardHeader>
            <CardContent>
              {isLoadingGraph ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin" />
                </div>
              ) : runGraph ? (
                <WorkflowGraph
                  nodes={runGraph.nodes}
                  edges={runGraph.edges}
                  status={runGraph.status}
                />
              ) : (
                <p className="text-center py-12 text-muted-foreground">
                  Graph data not available
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="artifacts" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Artifacts</CardTitle>
            </CardHeader>
            <CardContent>
              {run.artifacts.length > 0 ? (
                <div className="space-y-2">
                  {run.artifacts.map((artifactId) => (
                    <div key={artifactId} className="border rounded p-3 font-mono text-sm">
                      {artifactId}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-center py-12 text-muted-foreground">
                  No artifacts generated
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="cost" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Cost Breakdown</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="flex justify-between items-center pb-4 border-b">
                  <span className="text-lg font-medium">Total</span>
                  <span className="text-2xl font-bold">
                    {formatCost(run.totals.cost_usd)}
                  </span>
                </div>

                <div className="space-y-2">
                  {run.steps
                    .filter((s) => s.cost_usd && s.cost_usd > 0)
                    .map((step) => (
                      <div key={step.id} className="flex justify-between items-center text-sm">
                        <span className="text-muted-foreground">
                          {step.id} <span className="text-xs">({step.type})</span>
                        </span>
                        <div className="flex items-center gap-4">
                          <span className="text-xs text-muted-foreground">
                            {step.tokens} tokens
                          </span>
                          <span className="font-mono">{formatCost(step.cost_usd)}</span>
                        </div>
                      </div>
                    ))}
                </div>

                {run.steps.filter((s) => s.cost_usd && s.cost_usd > 0).length === 0 && (
                  <p className="text-center py-6 text-muted-foreground text-sm">
                    No AI operations with cost tracking
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
