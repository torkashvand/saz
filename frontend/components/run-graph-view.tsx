import { Card } from './ui/card';
import { WorkflowGraph } from './workflow-graph';
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
 *
 * Architecture note: This component is designed to be easily swapped out
 * with a more sophisticated graph library (react-flow, dagre, etc.) without
 * affecting the rest of the page.
 *
 * Future enhancements:
 * - Interactive nodes (click to focus step in timeline)
 * - Color-code by status (green=success, red=failed, blue=running)
 * - Show duration on each node
 * - Highlight critical path
 * - Support branching/conditional flows
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
          This may be because the flow is still running or doesn't have a graph definition.
        </p>
      </div>
    );
  }

  // Current implementation uses WorkflowGraph
  // TODO: Replace with interactive graph library that supports:
  // - Click handlers on nodes (onStepClick)
  // - Dynamic node styling based on step status
  // - Layout algorithms for complex workflows
  return (
    <WorkflowGraph
      nodes={runGraph.nodes}
      edges={runGraph.edges}
      status={runGraph.status_by_step || {}}
    />
  );
}

/**
 * Example of how to integrate a more advanced graph library:
 *
 * import ReactFlow, { Node, Edge } from 'react-flow-renderer';
 *
 * const nodes: Node[] = steps.map((step, idx) => ({
 *   id: step.id,
 *   data: {
 *     label: `Step ${step.number}: ${step.name}`,
 *     status: step.status,
 *     duration: step.duration_ms,
 *   },
 *   position: { x: 0, y: idx * 100 }, // Or use dagre for auto-layout
 *   type: 'stepNode', // Custom node component
 * }));
 *
 * const edges: Edge[] = runGraph.edges.map(e => ({
 *   id: `${e.from}-${e.to}`,
 *   source: e.from,
 *   target: e.to,
 * }));
 *
 * return (
 *   <ReactFlow
 *     nodes={nodes}
 *     edges={edges}
 *     onNodeClick={(event, node) => onStepClick?.(node.id)}
 *   />
 * );
 */
