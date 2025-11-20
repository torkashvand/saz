'use client';

import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/error-state';
import { RefreshCw } from 'lucide-react';
import Link from 'next/link';
import type { RunListItem, FlowListItem } from '@/lib/types';

export default function RunsPage() {
  const router = useRouter();
  const [page, setPage] = useState(0);
  const [flowFilter, setFlowFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const limit = 20;

  const { data: runs, isLoading, error, isError, refetch } = useQuery({
    queryKey: ['runs', page, flowFilter, statusFilter],
    queryFn: () => api.listRuns({
      limit,
      offset: page * limit,
      flow_id: flowFilter !== 'all' ? flowFilter : undefined,
      status: statusFilter !== 'all' ? statusFilter : undefined,
    }),
  });

  const { data: flows } = useQuery({
    queryKey: ['flows-for-filter'],
    queryFn: () => api.listFlows({ limit: 100, offset: 0 }),
  });

  const totalPages = runs ? Math.ceil(runs.total / limit) : 0;

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold text-slate-900">Workflow Runs</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => refetch()}>
            <RefreshCw className="w-4 h-4 mr-2" /> Refresh
          </Button>
          <Link href="/runs/new">
            <Button>+ New Run</Button>
          </Link>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-4 mb-6">
        <select
          value={flowFilter}
          onChange={(e) => {
            setFlowFilter(e.target.value);
            setPage(0);
          }}
          className="px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Flows</option>
          {flows?.items.map((f: FlowListItem) => (
            <option key={f.id} value={f.id}>{f.name}</option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(0);
          }}
          className="px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Statuses</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="waiting_approval">Waiting Approval</option>
        </select>
      </div>

      {/* Table */}
      {isError ? (
        <ErrorState error={error} title="Failed to Load Runs" onRetry={() => refetch()} />
      ) : isLoading ? (
        <div className="text-center py-8">Loading runs...</div>
      ) : runs && runs.items.length > 0 ? (
        <>
          <div className="bg-white border rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-slate-50 border-b">
                <tr>
                  <th className="text-left px-6 py-3 text-sm font-medium text-slate-700">Flow</th>
                  <th className="text-left px-6 py-3 text-sm font-medium text-slate-700">Run ID</th>
                  <th className="text-left px-6 py-3 text-sm font-medium text-slate-700">Status</th>
                  <th className="text-left px-6 py-3 text-sm font-medium text-slate-700">Created</th>
                  <th className="text-right px-6 py-3 text-sm font-medium text-slate-700">Cost</th>
                  <th className="text-right px-6 py-3 text-sm font-medium text-slate-700">Tokens</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {runs.items.map((run: RunListItem) => (
                  <tr key={run.id} className="hover:bg-slate-50 cursor-pointer" onClick={() => router.push(`/runs/${run.id}`)}>
                    <td className="px-6 py-4">
                      <Link href={`/runs/${run.id}`} className="font-medium text-blue-600 hover:underline" onClick={(e) => e.stopPropagation()}>
                        {run.flow_name}
                      </Link>
                    </td>
                    <td className="px-6 py-4 text-sm text-slate-600 font-mono">
                      {run.id.slice(0, 8)}...
                    </td>
                    <td className="px-6 py-4">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-6 py-4 text-sm text-slate-600">
                      {new Date(run.created_at).toLocaleString()}
                    </td>
                    <td className="px-6 py-4 text-sm text-slate-600 text-right">
                      ${run.total_cost_usd.toFixed(4)}
                    </td>
                    <td className="px-6 py-4 text-sm text-slate-600 text-right">
                      {run.total_tokens.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
              <span className="text-sm text-slate-600">
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
        <div className="text-center py-12 text-slate-500">
          {flowFilter !== 'all' || statusFilter !== 'all' ? 'No runs found matching your filters.' : 'No runs yet.'}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: 'bg-blue-100 text-blue-700 border-blue-300',
    completed: 'bg-green-100 text-green-700 border-green-300',
    failed: 'bg-red-100 text-red-700 border-red-300',
    waiting_approval: 'bg-yellow-100 text-yellow-700 border-yellow-300',
  };

  return (
    <span className={`inline-block px-2 py-1 text-xs rounded border ${colors[status] || 'bg-slate-100 text-slate-700 border-slate-300'}`}>
      {status.replace('_', ' ')}
    </span>
  );
}
