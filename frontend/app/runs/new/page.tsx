'use client';

import { useState, useMemo, useEffect, Suspense } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter, useSearchParams } from 'next/navigation';
import { api } from '@/lib/api';
import { useCreateRun } from '@/lib/hooks';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { ErrorBanner } from '@/components/ui/error-banner';
import { Search, PlayCircle, ArrowLeft } from 'lucide-react';
import { WorkflowCard } from '@/components/flows/workflow-card';
import { useErrorToast } from '@/lib/use-error-toast';
import Link from 'next/link';

function NewRunPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const flowIdParam = searchParams.get('flow');

  const { showError, showSuccess } = useErrorToast();
  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(flowIdParam);
  const [search, setSearch] = useState('');
  const [plannerFilter, setPlannerFilter] = useState<string>('all');
  const [formData, setFormData] = useState<Record<string, any>>({});
  const [submitting, setSubmitting] = useState(false);

  const {
    data: flows,
    isLoading: flowsLoading,
    error: flowsError,
  } = useQuery({
    queryKey: ['flows'],
    queryFn: () => api.listFlows({ limit: 100, offset: 0 }),
    retry: false,
  });

  const { data: selectedFlow, isLoading: flowLoading } = useQuery({
    queryKey: ['flow', selectedFlowId],
    queryFn: () => api.getFlow(selectedFlowId!),
    enabled: !!selectedFlowId,
  });

  useEffect(() => {
    // Keep the selected flow in sync with the URL in BOTH directions, so
    // browser Back from /runs/new?flow=X to /runs/new returns to the workflow
    // picker instead of leaving the launch form on screen.
    if (flowIdParam !== selectedFlowId) {
      setSelectedFlowId(flowIdParam);
      setFormData({});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowIdParam]);

  const filtered = useMemo(() => {
    if (!flows) return [];
    return flows.items.filter((f) => {
      const matchesSearch =
        f.name.toLowerCase().includes(search.toLowerCase()) ||
        (f.description?.toLowerCase().includes(search.toLowerCase()) ?? false);
      const matchesPlanner = plannerFilter === 'all' || (f as any).planner_mode === plannerFilter;
      return matchesSearch && matchesPlanner;
    });
  }, [flows, search, plannerFilter]);

  const handleLaunch = (flowId: string) => {
    setSelectedFlowId(flowId);
    setFormData({});
    router.push(`/runs/new?flow=${flowId}`, { scroll: false });
  };

  // useCreateRun invalidates ['runs'] on success so the runs list isn't stale
  // after launching from here.
  const createRunMutation = useCreateRun();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFlow) return;

    setSubmitting(true);
    try {
      const result = await createRunMutation.mutateAsync({
        flow_id: selectedFlow.id,
        payload: formData,
      });

      showSuccess(`Run ${result.id.slice(0, 8)}... created successfully`);
      router.push(`/runs/${result.id}`);
    } catch (error: any) {
      showError(error);
      setSubmitting(false);
    }
  };

  if (selectedFlowId && selectedFlow) {
    const formFields = selectedFlow.definition?.form?.fields || [];
    const credentials = selectedFlow.definition?.credentials || [];

    return (
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="mb-6">
          <button
            onClick={() => {
              setSelectedFlowId(null);
              setFormData({});
              router.push('/runs/new');
            }}
            className="inline-flex items-center text-sm text-slate-600 hover:text-slate-900 mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back to workflow selection
          </button>
          <h1 className="text-3xl font-bold text-slate-900">Launch Run</h1>
          <p className="text-slate-600 mt-1">{selectedFlow.name}</p>
        </div>

        <div className="grid grid-cols-3 gap-6">
          <div className="col-span-2">
            <Card>
              <CardHeader>
                <CardTitle>Run Configuration</CardTitle>
              </CardHeader>
              <CardContent>
                {formFields.length === 0 ? (
                  <div className="py-4">
                    <p className="text-sm text-slate-600 mb-4">
                      No input fields required for this workflow
                    </p>
                    <Button onClick={handleSubmit} disabled={submitting} className="w-full">
                      {submitting ? 'Launching Run...' : 'Launch Run'}
                    </Button>
                  </div>
                ) : (
                  <form onSubmit={handleSubmit} className="space-y-4">
                    {formFields.map((field: any) => {
                      const isRequired = field.required === true;
                      const fieldType =
                        field.type === 'number' || field.type === 'integer' ? 'number' : 'text';
                      const enumValues: string[] = Array.isArray(field.enum) ? field.enum : [];
                      const isTextarea =
                        field.widget === 'textarea' || field['x-widget'] === 'textarea';
                      // Numeric constraints (accept canonical + min/max aliases).
                      const numMin = field.minimum ?? field.min;
                      const numMax = field.maximum ?? field.max;
                      const numStep = field.type === 'integer' ? '1' : 'any';

                      // Booleans render as a single checkbox row (checkbox + name on
                      // one line, description once below) rather than the text-field
                      // layout — a header label + a separate "Enable" label read as
                      // two conflicting labels for one control. No required asterisk:
                      // a yes/no toggle is always answered, so "*" wrongly implies it
                      // must be checked. The payload carries a real boolean.
                      if (field.type === 'boolean') {
                        return (
                          <div key={field.name} className="space-y-1">
                            <label className="flex items-center gap-2 text-sm font-medium text-slate-700 cursor-pointer">
                              <input
                                id={field.name}
                                type="checkbox"
                                className="h-4 w-4 rounded border-input"
                                checked={formData[field.name] ?? false}
                                onChange={(e) =>
                                  setFormData({ ...formData, [field.name]: e.target.checked })
                                }
                              />
                              {field.name}
                            </label>
                            {field.description && (
                              <p className="text-xs text-slate-500 ml-6">{field.description}</p>
                            )}
                          </div>
                        );
                      }

                      return (
                        <div key={field.name} className="space-y-2">
                          <Label htmlFor={field.name}>
                            {field.name}
                            {isRequired && <span className="text-red-500 ml-1">*</span>}
                          </Label>
                          {field.description && (
                            <p className="text-xs text-slate-500">{field.description}</p>
                          )}
                          {enumValues.length > 0 ? (
                            // Enum fields render as a dropdown so the operator
                            // can only pick a valid value (rather than a free
                            // text box that lets them type an invalid one).
                            <select
                              id={field.name}
                              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                              value={formData[field.name] ?? ''}
                              onChange={(e) =>
                                setFormData({ ...formData, [field.name]: e.target.value })
                              }
                              required={isRequired}
                            >
                              <option value="" disabled={isRequired}>
                                {isRequired ? 'Select…' : '— none —'}
                              </option>
                              {enumValues.map((opt) => (
                                <option key={opt} value={opt}>
                                  {opt}
                                </option>
                              ))}
                            </select>
                          ) : isTextarea ? (
                            <Textarea
                              id={field.name}
                              rows={4}
                              value={formData[field.name] ?? ''}
                              onChange={(e) =>
                                setFormData({ ...formData, [field.name]: e.target.value })
                              }
                              required={isRequired}
                              placeholder={field.description}
                            />
                          ) : (
                            <Input
                              id={field.name}
                              type={fieldType}
                              min={fieldType === 'number' ? numMin : undefined}
                              max={fieldType === 'number' ? numMax : undefined}
                              step={fieldType === 'number' ? numStep : undefined}
                              value={formData[field.name] ?? ''}
                              onChange={(e) => {
                                // Clearing a numeric field yields '' → parseFloat
                                // is NaN, which serializes to null in the payload.
                                // Drop the key instead so the field reads as unset.
                                const raw = e.target.value;
                                const next = { ...formData };
                                if (fieldType === 'number') {
                                  if (raw === '') delete next[field.name];
                                  else next[field.name] = parseFloat(raw);
                                } else {
                                  next[field.name] = raw;
                                }
                                setFormData(next);
                              }}
                              required={isRequired}
                              placeholder={field.description}
                            />
                          )}
                        </div>
                      );
                    })}

                    <div className="pt-4">
                      <Button type="submit" disabled={submitting} className="w-full">
                        {submitting ? 'Launching Run...' : 'Launch Run'}
                      </Button>
                    </div>
                  </form>
                )}
              </CardContent>
            </Card>

            {credentials.length > 0 && (
              <Card className="mt-4 border-amber-200 bg-amber-50">
                <CardHeader>
                  <CardTitle className="text-amber-900 text-sm">Credentials Required</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-amber-700 mb-2">
                    This workflow requires the following credentials to be configured:
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {credentials.map((cred: string) => (
                      <span
                        key={cred}
                        className="text-xs bg-amber-100 text-amber-700 px-2 py-1 rounded font-mono"
                      >
                        {cred}
                      </span>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          <div className="col-span-1">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Workflow Info</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-600">Version:</span>
                  <span className="font-medium">{selectedFlow.version || '1.0'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">Planner Mode:</span>
                  <span className="font-medium">
                    {selectedFlow.definition?.planner_mode || 'deterministic'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">Steps:</span>
                  <span className="font-medium">
                    {selectedFlow.definition?.workflow?.steps?.length || 0}
                  </span>
                </div>
                {selectedFlow.description && (
                  <div className="pt-2 border-t">
                    <p className="text-slate-600 text-xs">{selectedFlow.description}</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-slate-900">Select Workflow</h1>
        <p className="text-slate-600 mt-1">Choose a workflow to launch a new run</p>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search workflows..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <select
          value={plannerFilter}
          onChange={(e) => setPlannerFilter(e.target.value)}
          className="px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Modes</option>
          <option value="deterministic">Deterministic</option>
          <option value="agentic">Agentic</option>
        </select>
      </div>

      {flowsError ? (
        <ErrorBanner
          error={flowsError}
          title="Failed to Load Workflows"
          onRetry={() => window.location.reload()}
        />
      ) : flowsLoading ? (
        <div className="text-center py-12">
          <p className="text-slate-600">Loading workflows...</p>
        </div>
      ) : filtered.length > 0 ? (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((flow) => (
            <WorkflowCard key={flow.id} flow={flow} showLaunch onLaunch={handleLaunch} />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-slate-600 mb-4">
              {flows && flows.items && flows.items.length > 0
                ? 'No workflows found matching your filters.'
                : 'No workflows registered yet.'}
            </p>
            {(!flows || flows.items.length === 0) && (
              <Link href="/flows/new">
                <Button>Register First Workflow</Button>
              </Link>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function NewRunPage() {
  return (
    <Suspense
      fallback={
        <div className="max-w-7xl mx-auto px-4 py-8">
          <div className="text-center py-12">
            <p className="text-slate-600">Loading...</p>
          </div>
        </div>
      }
    >
      <NewRunPageContent />
    </Suspense>
  );
}
