// Flow Draft Types for Guided Builder

export interface FlowFormField {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'array' | 'object';
  required: boolean;
  description?: string;
  help_text?: string;
  format?: string;
  default?: any;
}

export interface FlowTriggers {
  manual: boolean;
  webhook?: {
    enabled: boolean;
    path?: string;
    event?: string;
  };
  schedule?: {
    enabled: boolean;
    cron?: string;
    timezone?: string;
  };
}

export interface FlowPolicies {
  budget_usd?: number;
  pii_policy?: 'disallow' | 'tokenize' | 'allow_with_warning';
  timeout_ms?: number;
  continue_on_fail?: boolean;
  rate_limits?: {
    http_request?: { rpm?: number };
  };
}

export interface WorkflowStepDraft {
  id: string;
  name: string;
  type:
    | 'ai.extract'
    | 'ai.route'
    | 'ai.score'
    | 'ai.generate'
    | 'tool.call'
    | 'artifact.store'
    | 'webhook.wait'
    | 'human.approval'
    | 'branching';
  description?: string;
  instruction?: string;
  params?: Record<string, any>;
  schema?: any;
  temperature?: number;
  max_tokens?: number;
  tool?: string;
  expect?: any;
  branches_enum?: string[];
  word_cap?: number;
}

export interface FlowDraft {
  // Basics
  name: string;
  version: string;
  description: string;
  owners?: string[];
  labels?: string[];
  planner_mode?: 'deterministic' | 'agentic';
  schema_version: number;

  // Form
  form_fields: FlowFormField[];

  // Triggers
  triggers: FlowTriggers;

  // Policies
  policies: FlowPolicies;

  // Credentials
  credentials: string[];

  // Workflow Steps
  workflow_steps: WorkflowStepDraft[];
}

export interface ValidationError {
  section?: string;
  message: string;
  line?: number;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
  warnings?: string[];
  validated_at?: Date;
  flow_name?: string;
  workflow_summary?: {
    steps_count: number;
    ai_steps: number;
    credentials: string[];
  };
  form_schema?: any;
}

export type FlowBuilderMode = 'guided' | 'yaml';

export const STEP_TYPES = [
  { value: 'ai.extract', label: 'AI Extract', category: 'AI' },
  { value: 'ai.route', label: 'AI Route', category: 'AI' },
  { value: 'ai.score', label: 'AI Score', category: 'AI' },
  { value: 'ai.generate', label: 'AI Generate', category: 'AI' },
  { value: 'tool.call', label: 'Tool Call', category: 'Integration' },
  { value: 'artifact.store', label: 'Store Artifact', category: 'Data' },
  { value: 'webhook.wait', label: 'Webhook Wait', category: 'Integration' },
  { value: 'human.approval', label: 'Human Approval', category: 'Control' },
  { value: 'branching', label: 'Branching Logic', category: 'Control' },
] as const;

export const FIELD_TYPES = [
  { value: 'string', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
  { value: 'array', label: 'Array' },
  { value: 'object', label: 'Object' },
] as const;

export const PII_POLICIES = [
  { value: 'disallow', label: 'Disallow' },
  { value: 'tokenize', label: 'Tokenize' },
  { value: 'allow_with_warning', label: 'Allow with Warning' },
] as const;
