'use client'

import { useParams } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useRun, useAdvanceRun } from '@/lib/hooks'
import { useToast } from '@/components/ui/use-toast'
import { Loader2 } from 'lucide-react'

export default function RunDetailPage() {
  const params = useParams()
  const runId = params.id as string
  const { toast } = useToast()

  const { data: run, isLoading } = useRun(runId)
  const advanceMutation = useAdvanceRun(runId)

  const handleAdvance = async () => {
    console.log('Advance button clicked, runId:', runId)
    try {
      const result = await advanceMutation.mutateAsync({ event: 'continue' })
      console.log('Advance result:', result)
      toast({
        title: 'Run Advanced',
        description: `Status: ${result.status}`,
      })
    } catch (error: any) {
      console.error('Advance error:', error)
      toast({
        title: 'Failed to Advance',
        description: error.message || 'An error occurred',
        variant: 'destructive',
      })
    }
  }

  if (isLoading) {
    return (
      <div className="container mx-auto px-4 py-12 flex justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  if (!run) {
    return <div className="container mx-auto px-4 py-12">Run not found</div>
  }

  const canAdvance = ['suspended', 'waiting'].includes(run.status)

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-6">Run Details</h1>
      <p className="text-sm text-muted-foreground mb-4">Run ID: {runId}</p>

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Status: <span className="text-blue-600">{run.status}</span></CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {canAdvance ? (
              <Button
                onClick={handleAdvance}
                disabled={advanceMutation.isPending}
                className="w-full"
              >
                {advanceMutation.isPending ? 'Advancing...' : 'Advance Workflow'}
              </Button>
            ) : (
              <p className="text-sm text-muted-foreground">
                Workflow cannot be advanced from status: {run.status}
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>State</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-muted p-4 rounded overflow-auto">
              {JSON.stringify(run.state, null, 2)}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
