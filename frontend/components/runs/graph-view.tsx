import { WorkflowGraph } from '@/components/workflows/workflow-graph';
import { Loader2 } from 'lucide-react';
import type { RunStep } from '@/lib/types';

interface RunGraphViewProps {
  runGraph: any; // Type from API
  steps: RunStep[];
  isLoading: boolean;
  onStepClick?: (stepId: string) => void;
}

/**
 * Graph visualization for workflow execution.
 * Delegates rendering to WorkflowGraph (which uses @xyflow/react).
 */
export function RunGraphView({ runGraph, steps, isLoading, onStepClick }: RunGraphViewProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (!runGraph) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-500">Graph data not available</p>
        <p className="text-xs text-slate-400 mt-2">
          This may be because the flow is still running or doesn&apos;t have a graph definition.
        </p>
      </div>
    );
  }

  return (
    <WorkflowGraph
      nodes={runGraph.nodes}
      edges={runGraph.edges}
      status={runGraph.status_by_step || {}}
    />
  );
}