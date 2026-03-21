import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type { RegisterFlowRequest, CompileFlowRequest, CreateRunRequest, ResumeRunRequest } from './types';

// ========== Unified DSL Hooks ==========

export function useCompileFlow() {
  return useMutation({
    mutationFn: (data: CompileFlowRequest) => api.compileFlow(data),
  });
}

export function useRegisterFlow() {
  return useMutation({
    mutationFn: (data: RegisterFlowRequest) => api.registerFlow(data),
  });
}

export function useFlowDetail(flowId: string | null) {
  return useQuery({
    queryKey: ['flow-detail', flowId],
    queryFn: () => api.getFlow(flowId!),
    enabled: !!flowId,
  });
}

export function useFlowGraph(flowId: string | null) {
  return useQuery({
    queryKey: ['flow-graph', flowId],
    queryFn: () => api.getFlowGraph(flowId!),
    enabled: !!flowId,
  });
}

export function useRunGraph(runId: string | null) {
  return useQuery({
    queryKey: ['runGraph', runId],
    queryFn: () => api.getRunGraph(runId!),
    enabled: !!runId,
    // No polling - WebSocket events handle all updates
  });
}

export function useRunDetails(runId: string | null) {
  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.getRunDetails(runId!),
    enabled: !!runId,
    // No polling - WebSocket events handle all updates
  });
}

export function useCreateRun() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateRunRequest) => api.createRun(data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['run', data.id] });
      queryClient.invalidateQueries({ queryKey: ['runGraph', data.id] });
      queryClient.invalidateQueries({ queryKey: ['runs'] });
    },
  });
}

export function useResumeRun(runId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ResumeRunRequest) => api.resumeRun(runId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
      queryClient.invalidateQueries({ queryKey: ['runGraph', runId] });
      queryClient.invalidateQueries({ queryKey: ['runs'] });
    },
  });
}
