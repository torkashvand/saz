'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import Link from 'next/link'

export default function FlowsPage() {
  const router = useRouter()
  const [page, setPage] = useState(0)
  const limit = 20

  const { data: flows, isLoading } = useQuery({
    queryKey: ['flows', page],
    queryFn: () => api.listFlows({ limit, offset: page * limit }),
  })

  const totalPages = flows ? Math.ceil(flows.total / limit) : 0

  return (
    <div className="container mx-auto py-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Flows</h1>
          <p className="text-gray-600 mt-1">
            Registered workflow definitions
          </p>
        </div>
        <Link href="/register">
          <Button>+ Register Flow</Button>
        </Link>
      </div>

      {isLoading ? (
        <div className="text-center py-8">Loading flows...</div>
      ) : flows && flows.items.length > 0 ? (
        <>
          <div className="grid gap-4">
            {flows.items.map((flow) => (
              <Card key={flow.id} className="p-6 hover:shadow-lg transition-shadow">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <h3 className="text-lg font-semibold">{flow.name}</h3>
                      {flow.version && (
                        <span className="px-2 py-1 text-xs rounded-full bg-purple-100 text-purple-800">
                          v{flow.version}
                        </span>
                      )}
                    </div>
                    {flow.description && (
                      <p className="text-gray-600 mt-1">{flow.description}</p>
                    )}
                    <div className="flex gap-4 mt-2 text-sm text-gray-500">
                      <span>
                        Created: {new Date(flow.created_at).toLocaleDateString()}
                      </span>
                      <span>ID: {flow.id.slice(0, 8)}...</span>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => router.push(`/flows/${flow.id}`)}
                    >
                      View Details
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => {
                        localStorage.setItem('lastFlowId', flow.id)
                        router.push('/runs/new')
                      }}
                    >
                      Create Run
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
          <p className="text-gray-500 mb-4">No flows registered yet</p>
          <Link href="/register">
            <Button>Register Your First Flow</Button>
          </Link>
        </Card>
      )}
    </div>
  )
}