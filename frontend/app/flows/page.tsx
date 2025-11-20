'use client';

import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ErrorState } from '@/components/error-state';
import { Search } from 'lucide-react';
import Link from 'next/link';

export default function FlowsPage() {
  const router = useRouter();
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState('');
  const [plannerFilter, setPlannerFilter] = useState<string>('all');
  const limit = 20;

  const { data: flows, isLoading, error, isError } = useQuery({
    queryKey: ['flows', page],
    queryFn: () => api.listFlows({ limit, offset: page * limit }),
    retry: false,
  });

  // Client-side filtering
  const filtered = useMemo(() => {
    if (!flows) return [];
    return flows.items.filter((f) => {
      const matchesSearch =
        f.name.toLowerCase().includes(search.toLowerCase()) ||
        (f.description?.toLowerCase().includes(search.toLowerCase()) ?? false);
      const matchesPlanner =
        plannerFilter === 'all' || (f as any).planner_mode === plannerFilter;
      return matchesSearch && matchesPlanner;
    });
  }, [flows, search, plannerFilter]);

  const totalPages = flows ? Math.ceil(flows.total / limit) : 0;

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold text-slate-900">Workflow Catalog</h1>
        <Link href="/register">
          <Button>+ Register Flow</Button>
        </Link>
      </div>

      {/* Filters */}
      <div className="flex gap-4 mb-6">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search flows..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <select
          value={plannerFilter}
          onChange={(e) => setPlannerFilter(e.target.value)}
          className="px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Modes</option>
          <option value="deterministic">Deterministic</option>
          <option value="agentic">Agentic</option>
        </select>
      </div>

      {isError ? (
        <ErrorState
          error={error}
          title="Failed to Load Flows"
          onRetry={() => window.location.reload()}
        />
      ) : isLoading ? (
        <div className="text-center py-8">Loading flows...</div>
      ) : filtered.length > 0 ? (
        <>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((flow) => (
              <Link
                key={flow.id}
                href={`/flows/${flow.id}`}
                className="block bg-white border border-slate-200 rounded-lg p-5 hover:shadow-md hover:border-blue-300 transition-all"
              >
                <div className="flex items-start justify-between mb-2">
                  <h3 className="font-semibold text-slate-900">{flow.name}</h3>
                  <PlannerBadge mode={(flow as any).planner_mode || 'deterministic'} />
                </div>
                {flow.version && <div className="text-xs text-slate-500 mb-2">v{flow.version}</div>}
                <p className="text-sm text-slate-600 mb-3 line-clamp-2">
                  {flow.description || 'No description'}
                </p>
                <div className="text-xs text-slate-500">
                  Created {new Date(flow.created_at).toLocaleDateString()}
                </div>
              </Link>
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
        <div className="text-center py-12 text-slate-500">
          {flows && flows.items.length > 0
            ? 'No flows found matching your filters.'
            : 'No flows registered yet.'}
        </div>
      )}
    </div>
  );
}

function PlannerBadge({ mode }: { mode: string }) {
  const colors =
    mode === 'agentic'
      ? 'bg-purple-100 text-purple-700 border-purple-300'
      : 'bg-green-100 text-green-700 border-green-300';

  return (
    <span className={`text-xs px-2 py-1 rounded border ${colors}`}>
      {mode}
    </span>
  );
}
