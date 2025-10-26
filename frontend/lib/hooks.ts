import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type {
  RegisterFlowRequest,
  CreateRunRequest,
} from './types'

// ========== Unified DSL Hooks ==========

export function useRegisterFlow() {
  return useMutation({
    mutationFn: (data: RegisterFlowRequest) => api.registerFlow(data),
  })
}

export function useFlowGraph(flowId: string | null) {
  return useQuery({
    queryKey: ['flow-graph', flowId],
    queryFn: () => api.getFlowGraph(flowId!),
    enabled: !!flowId,
  })
}

export function useRunGraph(runId: string | null) {
  return useQuery({
    queryKey: ['run-graph', runId],
    queryFn: () => api.getRunGraph(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      const statuses = Object.values(query.state.data?.status || {})
      // Poll if any step is running or pending
      return statuses.includes('running') || statuses.includes('pending')
        ? 2000
        : false
    },
  })
}

export function useRunDetails(runId: string | null) {
  return useQuery({
    queryKey: ['run-details', runId],
    queryFn: () => api.getRunDetails(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      // Poll if running or pending
      return status === 'running' || status === 'pending'
        ? 2000
        : false
    },
  })
}

export function useCreateRun() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateRunRequest) => api.createRun(data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['run-details', data.run_id] })
      queryClient.invalidateQueries({ queryKey: ['run-graph', data.run_id] })
    },
  })
}
