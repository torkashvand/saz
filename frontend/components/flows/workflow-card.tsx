'use client';

import { Button } from '@/components/ui/button';
import { Edit, PlayCircle } from 'lucide-react';
import Link from 'next/link';
import type { FlowListItem } from '@/lib/types';

interface WorkflowCardProps {
  flow: FlowListItem;
  showEdit?: boolean;
  showLaunch?: boolean;
  onLaunch?: (flowId: string) => void;
}

export function WorkflowCard({ flow, showEdit, showLaunch, onLaunch }: WorkflowCardProps) {
  const plannerMode = (flow as any).planner_mode || 'deterministic';

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5 hover:shadow-md hover:border-blue-300 transition-all group relative">
      <div className="flex items-start justify-between mb-2">
        <h3 className="font-semibold text-slate-900 text-lg">{flow.name}</h3>
        <PlannerBadge mode={plannerMode} />
      </div>

      {flow.version && <div className="text-xs text-slate-500 mb-2">v{flow.version}</div>}

      <p className="text-sm text-slate-600 mb-3 line-clamp-2">
        {flow.description || 'No description'}
      </p>

      <div className="text-xs text-slate-500 mb-3">
        Created {new Date(flow.created_at).toLocaleDateString()}
      </div>

      <div className="flex items-center gap-2">
        {showLaunch && (
          <Button
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onLaunch?.(flow.id);
            }}
            className="flex items-center gap-1.5"
          >
            <PlayCircle className="h-4 w-4" />
            Launch
          </Button>
        )}
        {showEdit && (
          <Link href={`/flows/${flow.id}/edit`}>
            <Button
              variant="outline"
              size="sm"
              onClick={(e) => e.stopPropagation()}
              className="flex items-center gap-1.5"
            >
              <Edit className="h-4 w-4" />
              Edit
            </Button>
          </Link>
        )}
      </div>
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
