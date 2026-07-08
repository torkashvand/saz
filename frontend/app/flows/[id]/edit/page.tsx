'use client';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { FlowBuilder } from '@/components/flows/register/flow-builder';

export default function FlowEditPage({ params }: { params: { id: string } }) {
  const [initialYaml, setInitialYaml] = useState<string | null>(null);

  const { data: flow, isLoading } = useQuery({
    queryKey: ['flow', params.id],
    queryFn: () => api.getFlow(params.id),
  });

  useEffect(() => {
    if (flow && !initialYaml) {
      setInitialYaml(flow.original_yaml || '');
    }
  }, [flow, initialYaml]);

  if (isLoading || !initialYaml) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-600">Loading workflow...</div>
      </div>
    );
  }

  if (!flow) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-slate-600">Workflow not found</div>
      </div>
    );
  }

  return <FlowBuilder initialYaml={initialYaml} flowId={params.id} isEditMode={true} />;
}
