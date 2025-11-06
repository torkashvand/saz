'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useRegisterFlow, useFlowGraph } from '@/lib/hooks';
import { useToast } from '@/components/ui/use-toast';
import { JsonView } from '@/components/json-view';
import { WorkflowGraph } from '@/components/workflow-graph';
import type { RegisterFlowResponse } from '@/lib/types';

// Dynamically import Monaco editor to avoid SSR issues
const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false });

const EXAMPLE_YAML = `flow:
  name: simple_support_ticket
  version: "1.0"
  description: AI-powered ticket triage with auto-response

form:
  fields:
    - name: ticket_text
      type: text
      required: true
      description: Support ticket content
    - name: customer_email
      type: text
      required: true
      description: Customer email address

workflow:
  steps:
    - id: extract_data
      type: ai.extract
      instruction: "Extract category, priority, and sentiment"
      params:
        data:
          text: "{{ $form.ticket_text }}"
      schema:
        type: object
        properties:
          category:
            type: string
            enum: [technical, billing, general]
          priority:
            type: string
            enum: [low, medium, high]
          sentiment:
            type: string
            enum: [positive, neutral, negative]

    - id: generate_response
      type: ai.generate
      instruction: "Write a professional acknowledgment email"
      params:
        data:
          ticket: "{{ $form.ticket_text }}"
          category: "{{ $step('extract_data').category }}"
      word_cap: 150
      temperature: 0.4

policies:
  budget:
    max_tokens: 5000
    max_cost_usd: 0.25`;

export default function RegisterPage() {
  const router = useRouter();
  const { toast } = useToast();
  const registerMutation = useRegisterFlow();

  const [yaml, setYaml] = useState('');
  const [registeredFlow, setRegisteredFlow] = useState<RegisterFlowResponse | null>(null);

  const { data: flowGraph } = useFlowGraph(registeredFlow?.id || null);

  useEffect(() => {
    const saved = localStorage.getItem('last_yaml');
    if (saved) setYaml(saved);

    const savedFlow = localStorage.getItem('last_registered_flow');
    if (savedFlow) {
      try {
        setRegisteredFlow(JSON.parse(savedFlow));
      } catch {}
    }
  }, []);

  const handleRegister = async () => {
    if (!yaml.trim()) {
      toast({
        title: 'Error',
        description: 'YAML content is required',
        variant: 'destructive',
      });
      return;
    }

    try {
      const result = await registerMutation.mutateAsync({ yaml });

      setRegisteredFlow(result);
      localStorage.setItem('last_yaml', yaml);
      localStorage.setItem('last_registered_flow', JSON.stringify(result));

      toast({
        title: 'Success',
        description: `Flow "${result.name}" registered successfully`,
      });
    } catch (error: any) {
      toast({
        title: 'Registration Failed',
        description: error.message || 'An error occurred',
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Register Workflow</h1>
          <p className="text-muted-foreground">Define your workflow in unified YAML DSL</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={handleRegister} disabled={registerMutation.isPending}>
            {registerMutation.isPending ? 'Registering...' : 'Register Flow'}
          </Button>
          {registeredFlow && (
            <Button variant="outline" onClick={() => router.push('/runs/new')}>
              Create Run →
            </Button>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Editor Panel */}
        <Card>
          <CardHeader>
            <CardTitle>Unified YAML DSL</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <Button size="sm" variant="outline" onClick={() => setYaml(EXAMPLE_YAML)}>
                Load Example
              </Button>
              <div className="border rounded overflow-hidden">
                <MonacoEditor
                  height="500px"
                  language="yaml"
                  value={yaml}
                  onChange={(value) => setYaml(value || '')}
                  theme="vs-dark"
                  options={{
                    minimap: { enabled: false },
                    fontSize: 12,
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                  }}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Preview Panel */}
        <Card>
          <CardHeader>
            <CardTitle>Preview</CardTitle>
          </CardHeader>
          <CardContent>
            {registeredFlow ? (
              <Tabs defaultValue="summary" className="w-full">
                <TabsList className="w-full">
                  <TabsTrigger value="summary" className="flex-1">
                    Summary
                  </TabsTrigger>
                  <TabsTrigger value="form" className="flex-1">
                    Form Schema
                  </TabsTrigger>
                  <TabsTrigger value="graph" className="flex-1">
                    Workflow Graph
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="summary" className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="border rounded p-3">
                      <div className="text-xs text-muted-foreground">Flow ID</div>
                      <div className="text-sm font-mono mt-1 truncate">{registeredFlow.id}</div>
                    </div>
                    <div className="border rounded p-3">
                      <div className="text-xs text-muted-foreground">Total Steps</div>
                      <div className="text-2xl font-bold mt-1">
                        {registeredFlow.workflow_summary.steps_count}
                      </div>
                    </div>
                    <div className="border rounded p-3">
                      <div className="text-xs text-muted-foreground">AI Steps</div>
                      <div className="text-2xl font-bold mt-1">
                        {registeredFlow.workflow_summary.ai_steps}
                      </div>
                    </div>
                    <div className="border rounded p-3">
                      <div className="text-xs text-muted-foreground">Credentials</div>
                      <div className="text-sm mt-1">
                        {registeredFlow.workflow_summary.credentials?.length || 'None'}
                      </div>
                    </div>
                  </div>
                  {registeredFlow.workflow_summary.credentials &&
                    registeredFlow.workflow_summary.credentials.length > 0 && (
                      <div className="border rounded p-3">
                        <div className="text-xs text-muted-foreground mb-2">
                          Required Credentials
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {registeredFlow.workflow_summary.credentials.map((cred) => (
                            <span
                              key={cred}
                              className="text-xs bg-orange-100 text-orange-700 px-2 py-1 rounded"
                            >
                              {cred}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                </TabsContent>

                <TabsContent value="form">
                  <JsonView data={registeredFlow.form_schema} />
                </TabsContent>

                <TabsContent value="graph">
                  {flowGraph ? (
                    <WorkflowGraph nodes={flowGraph.nodes} edges={flowGraph.edges} />
                  ) : (
                    <div className="flex items-center justify-center py-12">
                      <p className="text-sm text-muted-foreground">Loading graph...</p>
                    </div>
                  )}
                </TabsContent>
              </Tabs>
            ) : (
              <p className="text-center py-12 text-muted-foreground">
                Register a workflow to see preview
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
