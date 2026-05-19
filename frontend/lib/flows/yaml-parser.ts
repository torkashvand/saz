import jsYaml from 'js-yaml';
import type { FlowDraft, FlowFormField, WorkflowStepDraft } from './types';
import type { CompileFlowResponse } from '../types';
import { api } from '../api';

export interface ParsedError {
  message: string;
  section?: string;
}

export type FlowDraftParseResult =
  | { ok: true; draft: FlowDraft; warnings?: string[]; compileResponse: CompileFlowResponse }
  | { ok: false; errors: ParsedError[]; advanced?: boolean };

/**
 * Parse YAML string into FlowDraft by calling the backend compile endpoint
 * and mapping the response to our draft structure.
 */
export async function yamlToDraft(yaml: string): Promise<FlowDraftParseResult> {
  if (!yaml.trim()) {
    return {
      ok: false,
      errors: [{ message: 'YAML content is required' }],
    };
  }

  try {
    // Call backend validate/compile endpoint
    const compileResponse = await api.compileFlow({ yaml });

    // Parse the YAML to extract the raw structure
    const parsedYaml = parseYamlStructure(yaml);

    // Check if YAML uses advanced features we can't represent
    const advancedCheck = checkForAdvancedFeatures(parsedYaml);
    if (!advancedCheck.supported) {
      return {
        ok: false,
        advanced: true,
        errors: [
          {
            message: `Advanced DSL features detected: ${advancedCheck.reasons.join(', ')}. Guided Builder is disabled.`,
            section: 'advanced',
          },
        ],
      };
    }

    // Map CompileFlowResponse + parsed YAML to FlowDraft
    const draft = mapToDraft(compileResponse, parsedYaml);

    return {
      ok: true,
      draft,
      warnings: compileResponse.warnings,
      compileResponse,
    };
  } catch (error: any) {
    return {
      ok: false,
      errors: [
        {
          message: error.message || 'Failed to parse YAML',
          section: 'validation',
        },
      ],
    };
  }
}

interface ParsedYamlStructure {
  schema_version?: number;
  flow?: {
    name?: string;
    version?: string;
    description?: string;
    owners?: string[];
    labels?: string[];
  };
  workflow?: {
    planner_mode?: 'deterministic' | 'agentic';
    steps?: any[];
  };
  form?: {
    fields?: any[];
  };
  triggers?: {
    manual?: boolean;
    webhook?: any;
    schedule?: any;
  };
  policies?: {
    budget_usd?: number;
    pii?: any;
    defaults?: any;
    rate_limits?: any;
  };
  credentials?: {
    uses?: string[];
  };
}

/**
 * Parse YAML string into structured object using js-yaml.
 */
function parseYamlStructure(yaml: string): ParsedYamlStructure {
  const raw = jsYaml.load(yaml) as Record<string, any> | null;
  if (!raw || typeof raw !== 'object') {
    return {};
  }

  const result: ParsedYamlStructure = {};

  // schema_version (may be stored as schema_version or _schema_version)
  result.schema_version = raw.schema_version ?? raw._schema_version;

  // flow metadata
  if (raw.flow && typeof raw.flow === 'object') {
    result.flow = {
      name: raw.flow.name,
      version: raw.flow.version != null ? String(raw.flow.version) : undefined,
      description: raw.flow.description,
      owners: Array.isArray(raw.flow.owners) ? raw.flow.owners : undefined,
      labels: Array.isArray(raw.flow.labels) ? raw.flow.labels : undefined,
    };
  }

  // triggers
  if (raw.triggers && typeof raw.triggers === 'object') {
    result.triggers = {
      manual: raw.triggers.manual ?? undefined,
      webhook: raw.triggers.webhook ?? undefined,
      schedule: raw.triggers.schedule ?? undefined,
    };
  }

  // workflow
  if (raw.workflow && typeof raw.workflow === 'object') {
    const steps = Array.isArray(raw.workflow.steps) ? raw.workflow.steps.map(normalizeStep) : [];
    result.workflow = {
      planner_mode: raw.workflow.planner_mode,
      steps,
    };
  }

  // policies
  if (raw.policies && typeof raw.policies === 'object') {
    result.policies = {
      budget_usd: typeof raw.policies.budget_usd === 'number' ? raw.policies.budget_usd : undefined,
      pii: raw.policies.pii ?? undefined,
      defaults: raw.policies.defaults ?? undefined,
      rate_limits: raw.policies.rate_limits ?? undefined,
    };
  }

  // credentials
  if (raw.credentials && typeof raw.credentials === 'object') {
    result.credentials = {
      uses: Array.isArray(raw.credentials.uses) ? raw.credentials.uses : undefined,
    };
  }

  // form fields
  if (raw.form && typeof raw.form === 'object') {
    result.form = {
      fields: Array.isArray(raw.form.fields) ? raw.form.fields : [],
    };
  }

  return result;
}

/**
 * Normalize a raw YAML step object into WorkflowStepDraft.
 * Preserves all supported fields including params, schema, expect, branches_enum.
 */
function normalizeStep(rawStep: any): WorkflowStepDraft {
  if (!rawStep || typeof rawStep !== 'object') {
    return { id: 'unknown', name: 'unknown', type: 'ai.extract' };
  }

  return {
    id: rawStep.id ?? 'unknown',
    name: rawStep.name || rawStep.id || 'unknown',
    type: rawStep.type || 'ai.extract',
    description: rawStep.description,
    instruction: rawStep.instruction,
    temperature: typeof rawStep.temperature === 'number' ? rawStep.temperature : undefined,
    max_tokens: typeof rawStep.max_tokens === 'number' ? rawStep.max_tokens : undefined,
    tool: rawStep.tool,
    word_cap: typeof rawStep.word_cap === 'number' ? rawStep.word_cap : undefined,
    params: rawStep.params && typeof rawStep.params === 'object' ? rawStep.params : undefined,
    schema: rawStep.schema ?? undefined,
    expect: rawStep.expect ?? undefined,
    branches_enum: Array.isArray(rawStep.branches_enum) ? rawStep.branches_enum : undefined,
  };
}

/**
 * Check for DSL features that the Guided Builder cannot represent.
 * Returns unsupported if any are found, so the UI can disable guided mode.
 */
function checkForAdvancedFeatures(parsed: ParsedYamlStructure): {
  supported: boolean;
  reasons: string[];
} {
  const reasons: string[] = [];

  if (!parsed.workflow?.steps) {
    return { supported: true, reasons };
  }

  for (const step of parsed.workflow.steps) {
    // group.parallel and group.map have nested sub-steps the builder can't represent
    if (step.type === 'group.parallel') {
      reasons.push(`step "${step.id}" uses group.parallel`);
    }
    if (step.type === 'group.map') {
      reasons.push(`step "${step.id}" uses group.map`);
    }
    // condition steps require expression editing not supported in guided mode
    if (step.type === 'condition') {
      reasons.push(`step "${step.id}" uses condition`);
    }
  }

  return {
    supported: reasons.length === 0,
    reasons,
  };
}

function mapToDraft(
  compileResponse: CompileFlowResponse,
  parsedYaml: ParsedYamlStructure,
): FlowDraft {
  // Extract form fields from compile response (backend is source of truth for validation)
  const formFields: FlowFormField[] = [];
  if (compileResponse.form_schema?.properties) {
    const props = compileResponse.form_schema.properties;
    const required = compileResponse.form_schema.required || [];

    for (const [name, schema] of Object.entries(props)) {
      const fieldSchema = schema as any;
      formFields.push({
        name,
        type: mapJsonSchemaType(fieldSchema.type),
        required: required.includes(name),
        description: fieldSchema.description || fieldSchema.title,
        format: fieldSchema.format,
        help_text: fieldSchema.help_text,
      });
    }
  }

  // Map workflow steps from parsed YAML (already normalized)
  const workflowSteps: WorkflowStepDraft[] = parsedYaml.workflow?.steps || [];

  // Extract PII policy from parsed YAML (js-yaml gives native types, not strings)
  let piiPolicy: 'disallow' | 'tokenize' | 'allow_with_warning' = 'disallow';
  if (parsedYaml.policies?.pii) {
    const pii = parsedYaml.policies.pii;
    const allow = pii.allow === true;
    const tokenize = pii.tokenize_model_inputs === true;
    if (allow) piiPolicy = 'allow_with_warning';
    else if (tokenize) piiPolicy = 'tokenize';
  }

  const draft: FlowDraft = {
    schema_version: parsedYaml.schema_version || 1,
    name: parsedYaml.flow?.name || compileResponse.flow_name,
    version: parsedYaml.flow?.version || compileResponse.flow_version || '1.0',
    description: parsedYaml.flow?.description || compileResponse.flow_description || '',
    owners: parsedYaml.flow?.owners,
    labels: parsedYaml.flow?.labels,
    planner_mode: parsedYaml.workflow?.planner_mode || 'deterministic',

    form_fields: formFields,

    triggers: {
      manual: parsedYaml.triggers?.manual ?? true,
      webhook: parsedYaml.triggers?.webhook
        ? {
            enabled: true,
            path: parsedYaml.triggers.webhook.path,
            event: parsedYaml.triggers.webhook.event,
          }
        : undefined,
      schedule: parsedYaml.triggers?.schedule
        ? {
            enabled: true,
            cron: parsedYaml.triggers.schedule.cron,
            timezone: parsedYaml.triggers.schedule.timezone,
          }
        : undefined,
    },

    policies: {
      budget_usd: parsedYaml.policies?.budget_usd,
      pii_policy: piiPolicy,
      timeout_ms:
        typeof parsedYaml.policies?.defaults?.timeout_ms === 'number'
          ? parsedYaml.policies.defaults.timeout_ms
          : undefined,
      continue_on_fail: parsedYaml.policies?.defaults?.continue_on_fail === true,
      rate_limits: parsedYaml.policies?.rate_limits,
    },

    credentials: parsedYaml.credentials?.uses || compileResponse.workflow_summary.credentials || [],

    workflow_steps: workflowSteps,
  };

  return draft;
}

function mapJsonSchemaType(jsonType: string): FlowFormField['type'] {
  switch (jsonType) {
    case 'string':
      return 'string';
    case 'number':
    case 'integer':
      return 'number';
    case 'boolean':
      return 'boolean';
    case 'array':
      return 'array';
    case 'object':
      return 'object';
    default:
      return 'string';
  }
}
