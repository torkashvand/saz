'use client';

import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/ui/error-banner';
import { Search } from 'lucide-react';
import { WorkflowCard } from '@/components/flows/workflow-card';
import { useAuth } from '@/lib/auth';
import Link from 'next/link';

export default function FlowsPage() {
  const router = useRouter();
  const { canWrite } = useAuth();
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState('');
  const [plannerFilter, setPlannerFilter] = useState<string>('all');
  const limit = 20;

  // Search/planner filters are client-side, so pagination must run over the
  // FILTERED set — paging the server per 20 rows while filtering locally made
  // searches miss matches on other pages and produced incoherent page counts.
  // The catalog is small; fetch it in one go and slice locally.
  const {
    data: flows,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['flows', 'catalog'],
    queryFn: () => api.listFlows({ limit: 500, offset: 0 }),
    retry: false,
  });

  const filtered = useMemo(() => {
    if (!flows) return [];
    return flows.items.filter((f) => {
      const matchesSearch =
        f.name.toLowerCase().includes(search.toLowerCase()) ||
        (f.description?.toLowerCase().includes(search.toLowerCase()) ?? false);
      const matchesPlanner = plannerFilter === 'all' || f.planner_mode === plannerFilter;
      return matchesSearch && matchesPlanner;
    });
  }, [flows, search, plannerFilter]);

  const totalPages = Math.ceil(filtered.length / limit);
  const currentPage = Math.min(page, Math.max(0, totalPages - 1));
  const pageItems = filtered.slice(currentPage * limit, (currentPage + 1) * limit);

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold text-slate-900">Workflow Catalog</h1>
        {canWrite && (
          <Link href="/flows/new">
            <Button>+ Register Flow</Button>
          </Link>
        )}
      </div>

      <div className="flex gap-4 mb-6">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search workflows..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <select
          value={plannerFilter}
          onChange={(e) => {
            setPlannerFilter(e.target.value);
            setPage(0);
          }}
          className="px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Modes</option>
          <option value="deterministic">Deterministic</option>
          <option value="agentic">Agentic</option>
        </select>
      </div>

      {error ? (
        <ErrorBanner
          error={error}
          title="Failed to Load Flows"
          onRetry={() => window.location.reload()}
        />
      ) : isLoading ? (
        <div className="text-center py-8">Loading workflows...</div>
      ) : filtered.length > 0 ? (
        <>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {pageItems.map((flow) => (
              <WorkflowCard
                key={flow.id}
                flow={flow}
                showEdit={canWrite}
                showLaunch={canWrite}
                onLaunch={(flowId) => router.push(`/runs/new?flow=${flowId}`)}
              />
            ))}
          </div>

          {totalPages > 1 && (
            <div className="mt-8 flex items-center justify-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(Math.max(0, currentPage - 1))}
                disabled={currentPage === 0}
              >
                ← Previous
              </Button>
              <span className="text-sm text-gray-600">
                Page {currentPage + 1} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(Math.min(totalPages - 1, currentPage + 1))}
                disabled={currentPage >= totalPages - 1}
              >
                Next →
              </Button>
            </div>
          )}
        </>
      ) : (
        <div className="text-center py-12 text-slate-500">
          {flows && flows.items && flows.items.length > 0
            ? 'No workflows found matching your filters.'
            : 'No workflows registered yet.'}
        </div>
      )}
    </div>
  );
}
