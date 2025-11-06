'use client'

import { useParams, useRouter } from 'next/navigation'
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { useRunDetails, useRunGraph } from '@/lib/hooks'
import { api } from '@/lib/api'
import { useToast } from '@/components/ui/use-toast'
import { Loader2, CheckCircle2, XCircle, Clock, Play, RefreshCw, Rewind, AlertCircle } from 'lucide-react'
import { WorkflowGraph } from '@/components/workflow-graph'
import { CollapsibleJson } from '@/components/json-view'
import type { RunStep, StepStatus } from '@/lib/types'

const STATUS_ICONS: Record<StepStatus, React.ReactNode> = {
  pending: <Clock className="h-5 w-5 text-slate-400" />,
  queued: <Clock className="h-5 w-5 text-slate-400" />,
  running: <Play className="h-5 w-5 text-blue-500 animate-pulse" />,
  success: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  completed: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  failed: <XCircle className="h-5 w-5 text-red-500" />,
  suspended: <Clock className="h-5 w-5 text-amber-500" />,
}

const STATUS_COLORS: Record<StepStatus, string> = {
  pending: 'bg-slate-200',
  queued: 'bg-slate-200',
  running: 'bg-blue-500',
  success: 'bg-green-500',
  completed: 'bg-green-500',
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

function StepTimeline({ steps }: { steps: RunStep[] }) {
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
                </div>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  {step.duration_ms && <span>{formatDuration(step.duration_ms)}</span>}
                </div>
              </div>

              {/* Step output and error display */}
              <div className="p-3 space-y-2">
                {/* Output display */}
                {step.output && Object.keys(step.output).length > 0 && (
                  <div className="border-l-4 border-green-500 bg-green-50 p-3 rounded">
                    <p className="text-xs font-medium text-green-900 mb-2">Output</p>
                    <CollapsibleJson data={step.output} />
                  </div>
                )}

                {/* Error display */}
                {step.error && (
                  <div className="border-l-4 border-red-500 bg-red-50 p-3 rounded">
                    <p className="text-xs font-medium text-red-900 mb-1">Error</p>
                    <p className="text-xs text-red-700 whitespace-pre-wrap">
                      {typeof step.error === 'object' ? step.error.message : step.error}
                    </p>
                    {step.error?.type && (
                      <p className="text-xs text-red-600 mt-1">Type: {step.error.type}</p>
                    )}
                    {step.error?.traceback && (
                      <details className="mt-2">
                        <summary className="text-xs text-red-600 cursor-pointer hover:underline">
                          Show traceback
                        </summary>
                        <pre className="mt-2 text-xs text-red-800 bg-red-100 p-2 rounded overflow-x-auto font-mono">
                          {step.error.traceback}
                        </pre>
                      </details>
                    )}
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
  const router = useRouter()
  const runId = params.id as string
  const { toast } = useToast()
  const { data: run, isLoading: isLoadingRun } = useRunDetails(runId)
  const { data: runGraph, isLoading: isLoadingGraph } = useRunGraph(runId)

  // Retry mutation
  const retryMutation = useMutation({
    mutationFn: () => api.retryRun(runId),
    onSuccess: (data) => {
      toast({
        title: 'Run Retried',
        description: `New run created: ${data.new_run_id.slice(0, 8)}...`,
      })
      router.push(`/runs/${data.new_run_id}`)
    },
    onError: (error: any) => {
      toast({
        title: 'Retry Failed',
        description: error.message || 'Failed to retry run',
        variant: 'destructive',
      })
    },
  })

  // Replay mutation
  const [replayStep, setReplayStep] = useState<number | null>(null)
  const replayMutation = useMutation({
    mutationFn: (fromStep: number) => api.replayRun(runId, fromStep),
    onSuccess: (data) => {
      toast({
        title: 'Run Replayed',
        description: `New run created: ${data.new_run_id.slice(0, 8)}...`,
      })
      router.push(`/runs/${data.new_run_id}`)
      setReplayStep(null)
    },
    onError: (error: any) => {
      toast({
        title: 'Replay Failed',
        description: error.message || 'Failed to replay run',
        variant: 'destructive',
      })
      setReplayStep(null)
    },
  })

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
  const isFailed = run.status === 'failed'
  const isSuspended = run.status === 'suspended'

  // Determine status display
  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'failed': return 'Failed'
      case 'suspended': return 'Needs Review'
      case 'success': return 'Succeeded'
      case 'completed': return 'Completed'
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
      case 'completed': return 'bg-green-100 text-green-800 border-green-300'
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
          <div className="flex items-center gap-2">
            <div className={`px-3 py-1 rounded-full text-sm font-medium border ${getStatusColor(run.status)}`}>
              {getStatusLabel(run.status)}
            </div>
          </div>
        </div>
        <p className="text-sm text-muted-foreground font-mono">{runId}</p>

        {/* Error Panel */}
        {run.error && (
          <div className="mt-4 border-l-4 border-red-500 bg-red-50 p-4 rounded">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm font-medium text-red-900">Run Failed</p>
                <p className="text-sm text-red-700 mt-1">
                  {typeof run.error === 'object' ? run.error.message : run.error}
                </p>
                {run.error?.type && (
                  <p className="text-xs text-red-600 mt-1">Type: {run.error.type}</p>
                )}
                {run.error?.traceback && (
                  <details className="mt-2">
                    <summary className="text-xs text-red-600 cursor-pointer hover:underline">
                      Show traceback
                    </summary>
                    <pre className="mt-2 text-xs text-red-800 bg-red-100 p-2 rounded overflow-x-auto font-mono">
                      {run.error.traceback}
                    </pre>
                  </details>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="mt-4 flex gap-2">
          {isFailed && (
            <Button
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              size="sm"
            >
              <RefreshCw className="h-4 w-4 mr-2" />
              Retry from Failing Step
            </Button>
          )}
          {!isRunning && run.steps.length > 0 && (
            <Button
              variant="outline"
              onClick={() => {
                const step = prompt(`Enter step number to replay from (0-${run.steps.length - 1}):`)
                if (step !== null) {
                  const stepNum = parseInt(step, 10)
                  if (!isNaN(stepNum) && stepNum >= 0 && stepNum < run.steps.length) {
                    setReplayStep(stepNum)
                    replayMutation.mutate(stepNum)
                  } else {
                    toast({
                      title: 'Invalid Step',
                      description: `Please enter a number between 0 and ${run.steps.length - 1}`,
                      variant: 'destructive',
                    })
                  }
                }
              }}
              disabled={replayMutation.isPending}
              size="sm"
            >
              <Rewind className="h-4 w-4 mr-2" />
              Replay from Step...
            </Button>
          )}
        </div>
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
                : isRunning
                ? formatDuration(Date.now() - new Date(run.started_at || Date.now()).getTime())
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
            Artifacts {run.artifacts && run.artifacts.length > 0 && `(${run.artifacts.length})`}
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
                  status={runGraph.status_by_step || {}}
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
              {run.artifacts && run.artifacts.length > 0 ? (
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