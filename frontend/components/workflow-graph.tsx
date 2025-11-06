'use client'

import { useCallback } from 'react'
import {
  ReactFlow,
  Node,
  Edge,
  Controls,
  Background,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { GraphNode, GraphEdge, StepStatus } from '@/lib/types'

interface WorkflowGraphProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  status?: Record<string, StepStatus>
}

const STATUS_COLORS: Record<StepStatus, string> = {
  pending: '#94a3b8', // slate-400
  queued: '#94a3b8', // slate-400
  running: '#3b82f6', // blue-500
  success: '#22c55e', // green-500
  completed: '#22c55e', // green-500
  failed: '#ef4444', // red-500
  suspended: '#f59e0b', // amber-500
}

const NODE_TYPES: Record<string, { color: string; bg: string }> = {
  'ai.extract': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.generate': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.route': { color: '#f59e0b', bg: '#fef3c7' },
  'ai.score': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.evaluate': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.plan': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.normalize': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.match': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.compare': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.translate': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.summarize': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.fix_json': { color: '#8b5cf6', bg: '#f3e8ff' },
  'ai.assess': { color: '#8b5cf6', bg: '#f3e8ff' },
  'tool.call': { color: '#06b6d4', bg: '#cffafe' },
  'artifact.store': { color: '#10b981', bg: '#d1fae5' },
  'artifact.retrieve': { color: '#10b981', bg: '#d1fae5' },
}

export function WorkflowGraph({ nodes: graphNodes, edges: graphEdges, status }: WorkflowGraphProps) {
  // Convert graph nodes to React Flow nodes
  const convertedNodes: Node[] = graphNodes.map((node, idx) => {
    const nodeType = NODE_TYPES[node.type] || { color: '#64748b', bg: '#f1f5f9' }
    const nodeStatus = status?.[node.id]
    const statusColor = nodeStatus ? STATUS_COLORS[nodeStatus] : undefined

    // Stronger styling for failed/suspended nodes
    const isFailed = nodeStatus === 'failed'
    const isSuspended = nodeStatus === 'suspended'
    const borderWidth = isFailed || isSuspended ? '3px' : '2px'

    return {
      id: node.id,
      type: 'default',
      position: { x: 250, y: idx * 100 },
      data: { label: node.label },
      style: {
        background: statusColor || nodeType.bg,
        border: `${borderWidth} solid ${statusColor || nodeType.color}`,
        borderRadius: '8px',
        padding: '10px',
        fontSize: '12px',
        fontWeight: isFailed || isSuspended ? 600 : 500,
        color: statusColor ? '#fff' : nodeType.color,
        boxShadow: isFailed ? '0 0 0 2px rgba(239, 68, 68, 0.3)' : undefined,
      },
    }
  })

  // Convert graph edges to React Flow edges
  const convertedEdges: Edge[] = graphEdges.map((edge, idx) => ({
    id: `${edge.from}-${edge.to}-${idx}`,
    source: edge.from,
    target: edge.to,
    label: edge.label,
    type: 'smoothstep',
    animated: status?.[edge.from] === 'running',
    markerEnd: {
      type: MarkerType.ArrowClosed,
    },
    style: {
      stroke: edge.label ? '#f59e0b' : '#94a3b8',
      strokeWidth: 2,
    },
    labelStyle: {
      fontSize: 10,
      fill: '#f59e0b',
      fontWeight: 600,
    },
  }))

  const [nodes, , onNodesChange] = useNodesState(convertedNodes)
  const [edges, , onEdgesChange] = useEdgesState(convertedEdges)

  return (
    <div className="w-full h-[500px] border rounded-lg">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        minZoom={0.5}
        maxZoom={1.5}
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  )
}
