'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { FlowBuilder } from '@/components/flows/register/flow-builder';

export default function FlowEditPage({ params }: { params: { id: string } }) {
  const {
    data: flow,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['flow', params.id],
    queryFn: () => api.getFlow(params.id),
  });

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-600">Loading workflow...</div>
      </div>
    );
  }

  if (isError || !flow) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-600">Workflow not found</div>
      </div>
    );
  }

  return (
    <FlowBuilder initialYaml={flow.original_yaml || ''} flowId={params.id} isEditMode={true} />
  );
}
