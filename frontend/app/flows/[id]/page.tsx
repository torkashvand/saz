'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { JsonView } from '@/components/json-view';
import { ErrorState } from '@/components/error-state';
import Link from 'next/link';

export default function FlowDetailPage({ params }: { params: { id: string } }) {
  const router = useRouter();

  const { data: flow, isLoading, error, isError } = useQuery({
    queryKey: ['flow', params.id],
    queryFn: () => api.getFlow(params.id),
  });

  if (isLoading) {
    return <div className="container mx-auto py-8 text-center">Loading flow...</div>;
  }

  if (isError) {
    return (
      <div className="container mx-auto py-8">
        <ErrorState
          error={error}
          title="Failed to Load Flow"
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  if (!flow) {
    return (
      <div className="container mx-auto py-8 text-center">
        <p className="text-gray-500 mb-4">Flow not found</p>
        <Link href="/flows">
          <Button>Back to Flows</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 text-sm text-gray-600 mb-2">
          <Link href="/flows" className="hover:underline">
            Flows
          </Link>
          <span>/</span>
          <span>{flow.name}</span>
        </div>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold">{flow.name}</h1>
              {flow.version && (
                <span className="px-3 py-1 text-sm rounded-full bg-purple-100 text-purple-800">
                  v{flow.version}
                </span>
              )}
            </div>
            {flow.description && <p className="text-gray-600 mt-2">{flow.description}</p>}
          </div>
          <div className="flex gap-2">
            <Button
              onClick={() => {
                localStorage.setItem('lastFlowId', flow.id);
                router.push('/runs/new');
              }}
            >
              Create Run
            </Button>
          </div>
        </div>
      </div>

      {/* Metadata */}
      <div className="grid grid-cols-2 gap-4 mb-8">
        <Card className="p-4">
          <div className="text-sm text-gray-600">Created</div>
          <div className="text-lg font-semibold mt-1">
            {new Date(flow.created_at).toLocaleString()}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-sm text-gray-600">Last Updated</div>
          <div className="text-lg font-semibold mt-1">
            {new Date(flow.updated_at).toLocaleString()}
          </div>
        </Card>
      </div>

      {/* Definition */}
      <Card className="p-6 mb-6">
        <h2 className="text-xl font-semibold mb-4">Workflow Steps</h2>
        {flow.definition.workflow_spec?.steps && (
          <div className="space-y-2">
            {flow.definition.workflow_spec.steps.map((step: any, idx: number) => (
              <div key={idx} className="p-3 bg-gray-50 rounded border border-gray-200">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-mono text-gray-500">{idx + 1}.</span>
                  <span className="font-semibold">{step.id || step.name}</span>
                  <span className="px-2 py-0.5 text-xs rounded bg-blue-100 text-blue-800">
                    {step.type}
                  </span>
                </div>
                {step.instruction && (
                  <p className="text-sm text-gray-600 mt-1 ml-6">{step.instruction}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Form Schema */}
      {flow.definition.form_schema && (
        <Card className="p-6 mb-6">
          <h2 className="text-xl font-semibold mb-4">Form Schema</h2>
          <JsonView data={flow.definition.form_schema} />
        </Card>
      )}

      {/* Policies */}
      {flow.definition.policies && (
        <Card className="p-6 mb-6">
          <h2 className="text-xl font-semibold mb-4">Policies</h2>
          <JsonView data={flow.definition.policies} />
        </Card>
      )}

      {/* Triggers */}
      {flow.triggers && (
        <Card className="p-6 mb-6">
          <h2 className="text-xl font-semibold mb-4">Triggers</h2>
          <JsonView data={flow.triggers} />
        </Card>
      )}

      {/* Full Definition (Collapsed by default) */}
      <Card className="p-6">
        <details>
          <summary className="text-xl font-semibold cursor-pointer">Full Definition (JSON)</summary>
          <div className="mt-4">
            <JsonView data={flow.definition} />
          </div>
        </details>
      </Card>
    </div>
  );
}
