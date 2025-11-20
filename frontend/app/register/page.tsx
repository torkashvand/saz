'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useCompileFlow, useRegisterFlow, useFlowGraph } from '@/lib/hooks';
import { useToast } from '@/components/ui/use-toast';
import { JsonView } from '@/components/json-view';
import { WorkflowGraph } from '@/components/workflow-graph';
import type { AppError } from '@/lib/errors';
import type { RegisterFlowResponse, CompileFlowResponse } from '@/lib/types';

// Dynamically import Monaco editor to avoid SSR issues
const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false });

const EXAMPLE_YAML = `# Unified DSL Example: Support Ticket Triage
# Demonstrates Extract → Route → Generate → Store with AI operations
schema_version: 1

flow:
  name: support_ticket_triage
  version: "1.0"
  description: AI-powered support ticket processing with routing and auto-response

form:
  fields:
    - name: ticket_text
      type: string          # 'text' alias is normalized, but keep canonical
      required: true
      description: Support ticket content
    - name: customer_email
      type: string
      required: true
      description: Customer email address
      format: email

triggers:
  manual: true
  webhook:
    path: "/support-ticket"    # schema allows: event?, path?, signature_header?
    # method is not allowed by your schema

workflow:
  steps:
    # Step 1: Extract structured data from unstructured ticket
    - id: extract_ticket_data
      type: ai.extract
      instruction: "Extract the key information from this support ticket: issue category, priority level, product name, and customer sentiment."
      params:
        data:
          text: "{{ $form.ticket_text }}"
      schema:
        type: object
        properties:
          category:
            type: string
            enum: [technical, billing, feature_request, bug_report, general]
          priority:
            type: string
            enum: [low, medium, high, critical]
          product:
            type: string
          sentiment:
            type: string
            enum: [positive, neutral, negative, angry]
        required: [category, priority, sentiment]
      temperature: 0.1
      max_tokens: 512

    # Step 2: Route based on extracted priority and category
    - id: route_ticket
      type: ai.route
      instruction: "Determine the correct team to handle this ticket based on category and priority."
      params:
        data:
          category: "{{ $step('extract_ticket_data').category }}"
          priority: "{{ $step('extract_ticket_data').priority }}"
          sentiment: "{{ $step('extract_ticket_data').sentiment }}"
      branches_enum:
        - engineering_urgent
        - engineering_normal
        - billing_team
        - sales_team
        - support_tier1
      temperature: 0.1
      max_tokens: 256

    # Step 3: Score ticket complexity for SLA assignment
    - id: score_complexity
      type: ai.score
      instruction: |
        Score the ticket complexity from 0 to 1 using this rubric:
        0.0-0.3: Simple questions/FAQ/basic troubleshooting
        0.3-0.6: Moderate; needs docs lookup/basic debugging
        0.6-0.8: Complex; code review/system investigation
        0.8-1.0: Critical bug, security, or architectural problem
      params:
        data:
          ticket: "{{ $form.ticket_text }}"
          category: "{{ $step('extract_ticket_data').category }}"
      temperature: 0.1
      max_tokens: 256

    # Step 4: Generate auto-response based on routing
    - id: generate_response
      type: ai.generate
      instruction: "Write a professional acknowledgment email for the customer. Reference their issue, acknowledge their sentiment, and provide an expected response time based on priority and complexity."
      params:
        data:
          customer_email: "{{ $form.customer_email }}"
          ticket: "{{ $form.ticket_text }}"
          category: "{{ $step('extract_ticket_data').category }}"
          priority: "{{ $step('extract_ticket_data').priority }}"
          sentiment: "{{ $step('extract_ticket_data').sentiment }}"
          routed_to: "{{ $step('route_ticket').route }}"
          complexity_score: "{{ $step('score_complexity').score }}"
      word_cap: 200
      temperature: 0.4
      max_tokens: 1024

    # Step 5: Evaluate response for quality and tone (use ai.extract to return JSON)
    - id: evaluate_response
      type: ai.extract
      instruction: |
        Evaluate the email for: professional tone, issue acknowledgment,
        clear timeline, and minimal jargon. Return ONLY JSON with:
        { "meets_standards": boolean, "issues": [string], "summary": string }
      params:
        data:
          response_text: "{{ $step('generate_response') }}"
          customer_sentiment: "{{ $step('extract_ticket_data').sentiment }}"
      schema:
        type: object
        properties:
          meets_standards: { type: boolean }
          issues: { type: array, items: { type: string } }
          summary: { type: string }
        required: [meets_standards]

    # Step 6: Send response via HTTP (always; or gate with a condition step if needed)
    - id: send_response
      type: tool.call
      tool: http_request
      description: Send auto-response email to customer
      params:
        method: POST
        url: "https://api.example.com/emails/send"
        headers:
          Authorization: "Bearer {{ $secret('email_api_token') }}"
        body:
          to: "{{ $form.customer_email }}"
          subject: "Your support ticket has been received"
          body: "{{ $step('generate_response') }}"
          template: "support_acknowledgment"
      expect:
        type: object
        properties:
          message_id: { type: string }

    # Step 7: Store complete ticket data as artifact
    - id: store_ticket_artifact
      type: artifact.store
      params:
        name: "ticket_{{ $form.customer_email }}_{{ $env('TIMESTAMP') }}"
        content:
          original_ticket: "{{ $form.ticket_text }}"
          customer_email: "{{ $form.customer_email }}"
          extracted: "{{ $step('extract_ticket_data') }}"
          routing: "{{ $step('route_ticket') }}"
          complexity: "{{ $step('score_complexity') }}"
          response: "{{ $step('generate_response') }}"
          evaluation: "{{ $step('evaluate_response') }}"
          email_sent: "{{ $step('send_response').message_id }}"

policies:
  budget_usd: 0.50                 # compiler supports cost budget (not token/step/time)
  defaults:
    timeout_ms: 300000             # ~300s end-to-end ceiling
    continue_on_fail: false
  rate_limits:
    http_request:
      rpm: 30
  pii:
    allow: false

credentials:
  uses: [email_api_token]
`;

export default function RegisterPage() {
  const router = useRouter();
  const { toast } = useToast();
  const compileMutation = useCompileFlow();
  const registerMutation = useRegisterFlow();

  const [yaml, setYaml] = useState('');
  const [compiledFlow, setCompiledFlow] = useState<CompileFlowResponse | null>(null);
  const [registeredFlow, setRegisteredFlow] = useState<RegisterFlowResponse | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [registrationError, setRegistrationError] = useState<Error | AppError | null>(null);

  const { data: flowGraph } = useFlowGraph(registeredFlow?.id || null);

  useEffect(() => {
    const saved = localStorage.getItem('last_yaml');
    if (saved) setYaml(saved);
  }, []);

  const handleValidate = async () => {
    if (!yaml.trim()) {
      const errorMsg = 'YAML content is required';
      setValidationError(errorMsg);
      toast({
        title: 'Error',
        description: errorMsg,
        variant: 'destructive',
      });
      return;
    }

    // Clear previous errors
    setValidationError(null);

    try {
      const result = await compileMutation.mutateAsync({ yaml });
      setCompiledFlow(result);

      if (result.warnings && result.warnings.length > 0) {
        toast({
          title: 'Validation Warnings',
          description: result.warnings.join(', '),
          variant: 'default',
        });
      } else {
        toast({
          title: 'Validation Successful',
          description: `Flow "${result.flow_name}" is valid`,
        });
      }
    } catch (error: any) {
      console.error('Validation error:', error);
      const errorMsg = error.message || 'Invalid YAML syntax or structure';
      setValidationError(errorMsg);
      toast({
        title: 'Validation Failed',
        description: errorMsg,
        variant: 'destructive',
      });
      setCompiledFlow(null);
    }
  };

  const handleRegister = async () => {
    if (!yaml.trim()) {
      toast({
        title: 'Error',
        description: 'YAML content is required',
        variant: 'destructive',
      });
      return;
    }

    // Clear previous registration error
    setRegistrationError(null);

    try {
      const result = await registerMutation.mutateAsync({ yaml });

      setRegisteredFlow(result);
      setCompiledFlow(null); // Clear compiled preview after registration
      localStorage.setItem('last_yaml', yaml);
      // Store only the flow ID, not the entire response (prevents schema issues)
      localStorage.setItem('last_flow_id', result.id);

      toast({
        title: 'Success',
        description: `Flow "${result.name}" registered successfully`,
      });
    } catch (error: any) {
      // Store error for persistent display
      setRegistrationError(error);

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
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => setYaml(EXAMPLE_YAML)}>
                  Load Example
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={handleValidate}
                  disabled={compileMutation.isPending}
                >
                  {compileMutation.isPending ? 'Validating...' : 'Validate YAML'}
                </Button>
              </div>
              <div className="border rounded overflow-hidden">
                <MonacoEditor
                  height="500px"
                  language="yaml"
                  value={yaml}
                  onChange={(value) => {
                    setYaml(value || '');
                    // Clear errors when user edits
                    if (validationError) setValidationError(null);
                    if (registrationError) setRegistrationError(null);
                  }}
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
            {validationError && (
              <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
                <div className="flex items-start gap-3">
                  <div className="text-red-600 text-xl">✕</div>
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-red-800 mb-1">
                      Validation Failed
                    </div>
                    <div className="text-xs text-red-700 font-mono whitespace-pre-wrap break-words">
                      {validationError}
                    </div>
                  </div>
                </div>
              </div>
            )}
            {registrationError && (
              <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
                <div className="flex items-start gap-3">
                  <div className="text-red-600 text-xl">⚠️</div>
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-red-800 mb-1">
                      Registration Failed
                    </div>
                    <div className="text-xs text-red-700 mb-2">
                      {registrationError && typeof registrationError === 'object' && 'kind' in registrationError
                        ? (registrationError as AppError).message
                        : registrationError instanceof Error
                        ? registrationError.message
                        : 'An error occurred while registering the flow'}
                    </div>
                    {registrationError && typeof registrationError === 'object' && 'kind' in registrationError && (registrationError as AppError).validationErrors && (
                      <div className="text-xs text-red-600 font-mono mb-2">
                        {(registrationError as AppError).validationErrors!.map((d: any) => d.message).join(', ')}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
            {(registeredFlow || compiledFlow) ? (
              <Tabs defaultValue="summary" className="w-full">
                <TabsList className="w-full">
                  <TabsTrigger value="summary" className="flex-1">
                    Summary
                  </TabsTrigger>
                  <TabsTrigger value="form" className="flex-1">
                    Form Schema
                  </TabsTrigger>
                  {registeredFlow && (
                    <TabsTrigger value="graph" className="flex-1">
                      Workflow Graph
                    </TabsTrigger>
                  )}
                </TabsList>

                <TabsContent value="summary" className="space-y-3">
                  {registeredFlow && (
                    <div className="mb-3 p-3 bg-green-50 border border-green-200 rounded">
                      <div className="text-xs font-medium text-green-800">✓ Flow Registered</div>
                      <div className="text-xs text-green-600 mt-1 font-mono truncate">
                        {registeredFlow.id}
                      </div>
                    </div>
                  )}
                  {compiledFlow && !registeredFlow && (
                    <div className="mb-3 p-3 bg-blue-50 border border-blue-200 rounded">
                      <div className="text-xs font-medium text-blue-800">
                        ✓ Validation Successful
                      </div>
                      <div className="text-xs text-blue-600 mt-1">
                        Ready to register: {compiledFlow.flow_name}
                      </div>
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-3">
                    {!compiledFlow && registeredFlow && (
                      <div className="border rounded p-3">
                        <div className="text-xs text-muted-foreground">Flow ID</div>
                        <div className="text-sm font-mono mt-1 truncate">{registeredFlow.id}</div>
                      </div>
                    )}
                    <div className="border rounded p-3">
                      <div className="text-xs text-muted-foreground">Total Steps</div>
                      <div className="text-2xl font-bold mt-1">
                        {(registeredFlow || compiledFlow)?.workflow_summary?.steps_count ?? 0}
                      </div>
                    </div>
                    <div className="border rounded p-3">
                      <div className="text-xs text-muted-foreground">AI Steps</div>
                      <div className="text-2xl font-bold mt-1">
                        {(registeredFlow || compiledFlow)?.workflow_summary?.ai_steps ?? 0}
                      </div>
                    </div>
                    <div className="border rounded p-3">
                      <div className="text-xs text-muted-foreground">Credentials</div>
                      <div className="text-sm mt-1">
                        {(registeredFlow || compiledFlow)?.workflow_summary?.credentials?.length ||
                          'None'}
                      </div>
                    </div>
                  </div>
                  {(() => {
                    const flow = registeredFlow || compiledFlow;
                    const credentials = flow?.workflow_summary?.credentials;
                    return credentials && credentials.length > 0 && (
                      <div className="border rounded p-3">
                        <div className="text-xs text-muted-foreground mb-2">
                          Required Credentials
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {credentials.map(
                            (cred) => (
                              <span
                                key={cred}
                                className="text-xs bg-orange-100 text-orange-700 px-2 py-1 rounded"
                              >
                                {cred}
                              </span>
                            ),
                          )}
                        </div>
                      </div>
                    );
                  })()}
                </TabsContent>

                <TabsContent value="form">
                  <JsonView data={(registeredFlow || compiledFlow)!.form_schema} />
                </TabsContent>

                {registeredFlow && (
                  <TabsContent value="graph">
                    {flowGraph ? (
                      <WorkflowGraph nodes={flowGraph.nodes} edges={flowGraph.edges} />
                    ) : (
                      <div className="flex items-center justify-center py-12">
                        <p className="text-sm text-muted-foreground">Loading graph...</p>
                      </div>
                    )}
                  </TabsContent>
                )}
              </Tabs>
            ) : (
              <p className="text-center py-12 text-muted-foreground">
                Validate or register a workflow to see preview
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
