import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type {
  RegisterFlowRequest,
  CompileFlowRequest,
  CreateRunRequest,
  ResumeRunRequest,
} from './types';

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

/**
 * Fetch the full YAML + metadata for a single template. Returns null
 * when ``templateId`` is null/empty so callers can pass a controlled
 * value without conditional hook usage.
 */
export function useTemplate(templateId: string | null) {
  return useQuery({
    queryKey: ['template', templateId],
    queryFn: () => api.getTemplate(templateId!),
    enabled: !!templateId,
    staleTime: 5 * 60 * 1000,
  });
}

// ========== Unified DSL Hooks ==========

export function useCompileFlow() {
  return useMutation({
    mutationFn: (data: CompileFlowRequest) => api.compileFlow(data),
  });
}

export function useRegisterFlow() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: RegisterFlowRequest) => api.registerFlow(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['flows'] });
    },
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
