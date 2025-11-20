'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { ErrorState } from '@/components/error-state';
import { Shield, Code, Network, PlayCircle } from 'lucide-react';
import Link from 'next/link';

export default function FlowDetailPage({ params }: { params: { id: string } }) {
  const router = useRouter();

  const { data: flow, isLoading, error, isError } = useQuery({
    queryKey: ['flow', params.id],
    queryFn: () => api.getFlow(params.id),
  });

  const { data: graph } = useQuery({
    queryKey: ['flow-graph', params.id],
    queryFn: () => api.getFlowGraph(params.id),
    enabled: !!flow,
  });

  if (isLoading) {
    return <div className="p-8">Loading flow...</div>;
  }

  if (isError) {
    return (
      <div className="p-8">
        <ErrorState error={error} title="Failed to Load Flow" onRetry={() => window.location.reload()} />
      </div>
    );
  }

  if (!flow) {
    return <div className="p-8">Flow not found</div>;
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-slate-500 mb-2">
          <Link href="/flows" className="hover:text-blue-600">
            Flows
          </Link>
          <span>/</span>
          <span>{flow.name}</span>
        </div>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-3xl font-bold text-slate-900">{flow.name}</h1>
            {flow.version && <p className="text-slate-600 mt-1">Version {flow.version}</p>}
            {flow.description && <p className="text-slate-600 mt-2">{flow.description}</p>}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview" className="w-full">
        <TabsList>
          <TabsTrigger value="overview">
            <Shield className="w-4 h-4 mr-2" /> Overview
          </TabsTrigger>
          <TabsTrigger value="definition">
            <Code className="w-4 h-4 mr-2" /> Definition
          </TabsTrigger>
          <TabsTrigger value="graph">
            <Network className="w-4 h-4 mr-2" /> Graph
          </TabsTrigger>
          <TabsTrigger value="launch">
            <PlayCircle className="w-4 h-4 mr-2" /> Launch
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab flow={flow} />
        </TabsContent>

        <TabsContent value="definition">
          <DefinitionTab definition={flow.definition} />
        </TabsContent>

        <TabsContent value="graph">
          <GraphTab graph={graph} />
        </TabsContent>

        <TabsContent value="launch">
          <LaunchTab
            flowId={params.id}
            formSchema={flow.definition?.form_schema}
            router={router}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function OverviewTab({ flow }: { flow: any }) {
  return (
    <div className="space-y-6 py-4">
      {/* Metadata */}
      <div className="bg-white border rounded-lg p-6">
        <h3 className="font-semibold mb-4">Configuration</h3>
        <dl className="grid grid-cols-2 gap-4">
          <div>
            <dt className="text-sm text-slate-500">Planner Mode</dt>
            <dd className="mt-1 font-medium">{flow.planner_mode || 'deterministic'}</dd>
          </div>
          <div>
            <dt className="text-sm text-slate-500">Steps</dt>
            <dd className="mt-1 font-medium">{flow.step_count || 0}</dd>
          </div>
          <div>
            <dt className="text-sm text-slate-500">Created</dt>
            <dd className="mt-1">{new Date(flow.created_at).toLocaleString()}</dd>
          </div>
        </dl>
      </div>

      {/* Policies */}
      {flow.policies && (
        <div className="bg-white border rounded-lg p-6">
          <h3 className="font-semibold mb-4">Policies & Limits</h3>
          <dl className="grid grid-cols-3 gap-4">
            <div>
              <dt className="text-sm text-slate-500">Max Steps</dt>
              <dd className="mt-1 font-medium">{flow.policies.max_steps || 'N/A'}</dd>
            </div>
            <div>
              <dt className="text-sm text-slate-500">Max Cost (USD)</dt>
              <dd className="mt-1 font-medium">
                ${flow.policies.max_cost_usd?.toFixed(2) || '0.00'}
              </dd>
            </div>
            <div>
              <dt className="text-sm text-slate-500">Max Tokens</dt>
              <dd className="mt-1 font-medium">
                {flow.policies.max_tokens?.toLocaleString() || 'N/A'}
              </dd>
            </div>
          </dl>
        </div>
      )}

      {/* Credentials */}
      {flow.definition?.credentials && flow.definition?.credentials.length > 0 && (
        <div className="bg-white border rounded-lg p-6">
          <h3 className="font-semibold mb-4">Required Credentials</h3>
          <ul className="space-y-2">
            {flow.definition.credentials.map((cred: string) => (
              <li key={cred} className="text-sm text-slate-700 flex items-center gap-2">
                <span className="w-2 h-2 bg-blue-500 rounded-full"></span>
                {cred}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function DefinitionTab({ definition }: { definition: any }) {
  return (
    <div className="py-4">
      <div className="bg-slate-900 rounded-lg p-6 overflow-x-auto">
        <pre className="text-slate-100 text-sm">{JSON.stringify(definition, null, 2)}</pre>
      </div>
    </div>
  );
}

function GraphTab({ graph }: { graph: any }) {
  if (!graph || !graph.nodes || graph.nodes.length === 0) {
    return <div className="py-8 text-center text-slate-500">No graph data available</div>;
  }

  return (
    <div className="py-4">
      <div className="bg-white border rounded-lg p-6">
        <h3 className="font-semibold mb-4">Workflow Steps</h3>
        <div className="space-y-3">
          {graph.nodes.map((node: any, idx: number) => (
            <div key={node.id} className="flex items-start gap-3">
              <div className="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-700 rounded-full flex items-center justify-center text-sm font-medium">
                {idx + 1}
              </div>
              <div className="flex-1">
                <div className="font-medium text-slate-900">{node.label}</div>
                <div className="text-sm text-slate-500">{node.type}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function LaunchTab({
  flowId,
  formSchema,
  router,
}: {
  flowId: string;
  formSchema: any;
  router: any;
}) {
  const [payload, setPayload] = useState<Record<string, any>>({});
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const result = await api.createRun({ flow_id: flowId, payload });
      router.push(`/runs/${result.id}`);
    } catch (err) {
      alert('Failed to create run: ' + (err as Error).message);
      setSubmitting(false);
    }
  };

  if (!formSchema || Object.keys(formSchema).length === 0) {
    return (
      <div className="py-4">
        <div className="bg-white border rounded-lg p-6">
          <p className="text-slate-600 mb-4">This flow has no input form. Launch with empty payload?</p>
          <button
            onClick={() => handleSubmit({ preventDefault: () => {} } as any)}
            disabled={submitting}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {submitting ? 'Launching...' : 'Launch Run'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="py-4">
      <form onSubmit={handleSubmit} className="bg-white border rounded-lg p-6 space-y-4">
        <h3 className="font-semibold mb-4">Run Configuration</h3>
        {Object.entries(formSchema).map(([key, field]: [string, any]) => (
          <div key={key}>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              {field.label || key}
            </label>
            {field.description && (
              <p className="text-xs text-slate-500 mb-2">{field.description}</p>
            )}
            <input
              type={field.type === 'integer' ? 'number' : 'text'}
              required={field.required}
              value={payload[key] || ''}
              onChange={(e) => setPayload({ ...payload, [key]: e.target.value })}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        ))}
        <button
          type="submit"
          disabled={submitting}
          className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
        >
          {submitting ? 'Launching...' : 'Launch Run'}
        </button>
      </form>
    </div>
  );
}
