'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useCreateRun, useFlowDetail } from '@/lib/hooks';
import { useErrorToast } from '@/lib/use-error-toast';
import { ErrorBanner } from '@/components/ui/error-banner';

export default function NewRunPage() {
  const router = useRouter();
  const { showError, showSuccess } = useErrorToast();
  const createRunMutation = useCreateRun();

  const [flowId, setFlowId] = useState<string | null>(null);
  const [formData, setFormData] = useState<Record<string, any>>({});

  // Fetch flow from API using stored ID
  const { data: flow, isLoading, error } = useFlowDetail(flowId);

  useEffect(() => {
    // Get flow ID from localStorage (not full object)
    const savedFlowId = localStorage.getItem('last_flow_id');
    if (savedFlowId) {
      setFlowId(savedFlowId);
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!flow) return;

    try {
      const result = await createRunMutation.mutateAsync({
        flow_id: flow.id,
        payload: formData,
      });

      showSuccess(`Run ${result.id.slice(0, 8)}... created successfully`);
      router.push(`/runs/${result.id}`);
    } catch (error: any) {
      showError(error);
    }
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="container mx-auto px-4 py-12">
        <Card className="max-w-lg mx-auto">
          <CardContent className="py-12">
            <p className="text-center text-muted-foreground">Loading workflow...</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Error loading flow
  if (error) {
    return (
      <div className="container mx-auto px-4 py-12">
        <ErrorBanner
          error={error}
          title="Failed to Load Workflow"
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  // No flow ID or flow not found
  if (!flowId || !flow) {
    return (
      <div className="container mx-auto px-4 py-12">
        <Card className="max-w-lg mx-auto">
          <CardHeader>
            <CardTitle>No Workflow Selected</CardTitle>
            <CardDescription>You need to register a workflow before creating a run</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => router.push('/register')} className="w-full">
              Go to Register Workflow
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Parse form fields from flow definition
  const formFields = flow.definition?.form?.fields || [];
  const workflowSteps = flow.definition?.workflow?.steps || [];
  const credentials = flow.definition?.credentials || [];

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="max-w-2xl mx-auto">
        <div className="mb-6">
          <h1 className="text-3xl font-bold">Create New Run</h1>
          <p className="text-muted-foreground mt-1">
            Fill in the form to execute {flow.name}
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Workflow Input</CardTitle>
            <CardDescription>
              {workflowSteps.length} steps • {flow.name}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {formFields.length === 0 ? (
              <div className="py-4">
                <p className="text-sm text-muted-foreground mb-4">
                  No input fields required for this workflow
                </p>
                <Button onClick={handleSubmit} disabled={createRunMutation.isPending} className="w-full">
                  {createRunMutation.isPending ? 'Creating Run...' : 'Create Run'}
                </Button>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                {formFields.map((field: any) => {
                  const isRequired = field.required === true;
                  const fieldType =
                    field.type === 'number' || field.type === 'integer' ? 'number' : 'text';

                  return (
                    <div key={field.name} className="space-y-2">
                      <Label htmlFor={field.name}>
                        {field.name}
                        {isRequired && <span className="text-red-500 ml-1">*</span>}
                      </Label>
                      {field.description && (
                        <p className="text-xs text-muted-foreground">{field.description}</p>
                      )}
                      <Input
                        id={field.name}
                        type={fieldType}
                        value={formData[field.name] || ''}
                        onChange={(e) => {
                          const value =
                            fieldType === 'number' ? parseFloat(e.target.value) : e.target.value;
                          setFormData({ ...formData, [field.name]: value });
                        }}
                        required={isRequired}
                        placeholder={field.description}
                      />
                    </div>
                  );
                })}

                <div className="pt-4">
                  <Button type="submit" disabled={createRunMutation.isPending} className="w-full">
                    {createRunMutation.isPending ? 'Creating Run...' : 'Create Run'}
                  </Button>
                </div>
              </form>
            )}
          </CardContent>
        </Card>

        {credentials.length > 0 && (
          <Card className="mt-4 border-orange-200 bg-orange-50">
            <CardHeader>
              <CardTitle className="text-orange-900 text-sm">Credentials Required</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-orange-700 mb-2">
                This workflow requires the following credentials to be configured:
              </p>
              <div className="flex flex-wrap gap-1">
                {credentials.map((cred: string) => (
                  <span
                    key={cred}
                    className="text-xs bg-orange-100 text-orange-700 px-2 py-1 rounded font-mono"
                  >
                    {cred}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}