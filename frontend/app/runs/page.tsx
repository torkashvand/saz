'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useRouter, useSearchParams } from 'next/navigation'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import Link from 'next/link'

const STATUS_COLORS: Record<string, string> = {
  running: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  suspended: 'bg-yellow-100 text-yellow-800',
  waiting: 'bg-purple-100 text-purple-800',
  created: 'bg-gray-100 text-gray-800',
}

export default function RunsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [page, setPage] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [flowIdFilter, setFlowIdFilter] = useState('')
  const limit = 20

  const { data: runs, isLoading } = useQuery({
    queryKey: ['runs', page, statusFilter, flowIdFilter],
    queryFn: () =>
      api.listRuns({
        limit,
        offset: page * limit,
        status: statusFilter || undefined,
        flow_id: flowIdFilter || undefined,
      }),
    // No polling - WebSocket events handle all updates
  })

  const totalPages = runs ? Math.ceil(runs.total / limit) : 0

  const handleStatusChange = (status: string) => {
    setStatusFilter(status)
    setPage(0)
  }

  const handleFlowIdChange = (flowId: string) => {
    setFlowIdFilter(flowId)
    setPage(0)
  }

  const getDuration = (created: string, completed?: string) => {
    const start = new Date(created).getTime()
    const end = completed ? new Date(completed).getTime() : Date.now()
    const seconds = Math.floor((end - start) / 1000)

    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  }

  return (
    <div className="container mx-auto py-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Runs</h1>
          <p className="text-gray-600 mt-1">
            Workflow execution history
          </p>
        </div>
        <Link href="/runs/new">
          <Button>+ New Run</Button>
        </Link>
      </div>

      {/* Filters */}
      <Card className="p-4 mb-6">
        <div className="flex gap-4 items-end">
          <div className="flex-1">
            <label className="text-sm font-medium mb-1 block">
              Filter by Status
            </label>
            <select
              className="w-full border rounded-md p-2"
              value={statusFilter}
              onChange={(e) => handleStatusChange(e.target.value)}
            >
              <option value="">All Statuses</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="suspended">Suspended</option>
              <option value="waiting">Waiting</option>
            </select>
          </div>
          <div className="flex-1">
            <label className="text-sm font-medium mb-1 block">
              Filter by Flow ID
            </label>
            <Input
              placeholder="Enter flow ID..."
              value={flowIdFilter}
              onChange={(e) => handleFlowIdChange(e.target.value)}
            />
          </div>
          <Button
            variant="outline"
            onClick={() => {
              setStatusFilter('')
              setFlowIdFilter('')
              setPage(0)
            }}
          >
            Clear Filters
          </Button>
        </div>
      </Card>

      {/* Total count */}
      {runs && (
        <div className="text-sm text-gray-600 mb-4">
          Showing {runs.items.length} of {runs.total} runs
        </div>
      )}

      {/* Runs List */}
      {isLoading ? (
        <div className="text-center py-8">Loading runs...</div>
      ) : runs && runs.items.length > 0 ? (
        <>
          <div className="grid gap-4">
            {runs.items.map((run) => (
              <Card
                key={run.id}
                className="p-6 hover:shadow-lg transition-shadow cursor-pointer"
                onClick={() => router.push(`/runs/${run.id}`)}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <span className="font-mono text-sm text-gray-600">
                        {run.id.slice(0, 8)}...
                      </span>
                      <span
                        className={`px-2 py-1 text-xs rounded-full ${
                          STATUS_COLORS[run.status] || 'bg-gray-100 text-gray-800'
                        }`}
                      >
                        {run.status}
                      </span>
                      {['running', 'created'].includes(run.status) && (
                        <span className="flex items-center gap-1 text-xs text-blue-600">
                          <span className="animate-pulse">●</span>
                          In Progress
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-gray-600 space-y-1">
                      <div>
                        <span className="font-medium">Flow ID:</span>{' '}
                        {run.flow_id.slice(0, 8)}...
                      </div>
                      <div>
                        <span className="font-medium">Started:</span>{' '}
                        {new Date(run.created_at).toLocaleString()}
                      </div>
                      {run.completed_at && (
                        <div>
                          <span className="font-medium">Completed:</span>{' '}
                          {new Date(run.completed_at).toLocaleString()}
                        </div>
                      )}
                      <div>
                        <span className="font-medium">Duration:</span>{' '}
                        {getDuration(run.created_at, run.completed_at)}
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation()
                        router.push(`/runs/${run.id}`)
                      }}
                    >
                      View Details
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-8 flex items-center justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
              >
                ← Previous
              </Button>
              <span className="text-sm text-gray-600">
                Page {page + 1} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                disabled={page >= totalPages - 1}
              >
                Next →
              </Button>
            </div>
          )}
        </>
      ) : (
        <Card className="p-12 text-center">
          <p className="text-gray-500 mb-4">
            {statusFilter || flowIdFilter
              ? 'No runs match your filters'
              : 'No runs yet'}
          </p>
          {!statusFilter && !flowIdFilter && (
            <Link href="/runs/new">
              <Button>Create Your First Run</Button>
            </Link>
          )}
        </Card>
      )}
    </div>
  )
}