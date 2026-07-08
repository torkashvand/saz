import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type { RegisterFlowRequest, CreateRunRequest, ResumeRunRequest } from './types';

// ========== AI Operations Reference ==========

export function useAIOps() {
  return useQuery({
    queryKey: ['ai-ops'],
    queryFn: () => api.listAIOps(),
    staleTime: 5 * 60 * 1000, // 5 min — AI ops don't change at runtime
  });
}

// ========== Templates ==========

/**
 * List built-in flow templates. Pass recommendedOnly to filter to the
 * curated wedge demos. Cached for 5 min — templates ship with the
 * backend and only change on deploy.
 */
export function useTemplates(options?: { recommendedOnly?: boolean }) {
  const recommendedOnly = !!options?.recommendedOnly;
  return useQuery({
    queryKey: ['templates', { recommendedOnly }],
    queryFn: () => api.listTemplates({ recommendedOnly }),
    staleTime: 5 * 60 * 1000,
  });
}

// ========== Unified DSL Hooks ==========

export function useRegisterFlow() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: RegisterFlowRequest) => api.registerFlow(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['flows'] });
    },
  });
}

export function useUpdateFlow(flowId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: RegisterFlowRequest) => api.updateFlow(flowId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['flows'] });
      queryClient.invalidateQueries({ queryKey: ['flow-detail', flowId] });
      queryClient.invalidateQueries({ queryKey: ['flow', flowId] });
    },
  });
}

export function useDslMetadata() {
  return useQuery({
    queryKey: ['dsl-metadata'],
    queryFn: () => api.getDslMetadata(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useRunDetails(runId: string | null, refetchInterval: number | false = false) {
  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.getRunDetails(runId!),
    enabled: !!runId,
    // WebSocket events drive updates in the normal case. The caller passes a
    // refetchInterval as a fallback when the live stream is disconnected, so a
    // frozen socket can't leave the run page permanently stale.
    refetchInterval,
  });
}

export function useCreateRun() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateRunRequest) => api.createRun(data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['run', data.id] });
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
      queryClient.invalidateQueries({ queryKey: ['runs'] });
    },
  });
}
