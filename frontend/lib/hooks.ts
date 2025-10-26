import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type {
  RegisterFormsRequest,
  CreateRunRequest,
  AdvanceRunRequest,
} from './types'

export function useRegisterForms() {
  return useMutation({
    mutationFn: (data: RegisterFormsRequest) => api.registerForms(data),
  })
}

export function useCreateRun() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateRunRequest) => api.createRun(data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['run', data.run_id] })
    },
  })
}

export function useRun(runId: string | null) {
  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      // Poll if running, suspended, or waiting
      return ['running', 'suspended', 'waiting'].includes(status || '')
        ? 2000
        : false
    },
  })
}

export function useAdvanceRun(runId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: AdvanceRunRequest) => api.advanceRun(runId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] })
    },
  })
}
