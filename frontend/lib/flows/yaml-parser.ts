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
    // We need to extract fields that aren't in CompileFlowResponse
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
 * Simple YAML parser using native libraries or regex for basic structure extraction
 * This is NOT a full YAML parser - just extracts key-value pairs we need
 */
function parseYamlStructure(yaml: string): ParsedYamlStructure {
  const lines = yaml.split('\n');
  const result: ParsedYamlStructure = {};

  // Very basic parsing - extract top-level sections
  // For production, you'd use a YAML library, but avoiding dependencies here

  // Extract schema_version
  const schemaMatch = yaml.match(/schema_version:\s*(\d+)/);
  if (schemaMatch) {
    result.schema_version = parseInt(schemaMatch[1]);
  }

  // Extract flow metadata
  const flowSection = extractSection(yaml, 'flow:');
  if (flowSection) {
    result.flow = {
      name: extractValue(flowSection, 'name') || undefined,
      version: extractValue(flowSection, 'version')?.replace(/"/g, '') || undefined,
      description: extractValue(flowSection, 'description')?.replace(/"/g, '') || undefined,
      owners: extractList(flowSection, 'owners'),
      labels: extractList(flowSection, 'labels'),
    };
  }

  // Extract triggers
  const triggersSection = extractSection(yaml, 'triggers:');
  if (triggersSection) {
    result.triggers = {
      manual: extractValue(triggersSection, 'manual') === 'true',
      webhook: extractObject(triggersSection, 'webhook'),
      schedule: extractObject(triggersSection, 'schedule'),
    };
  }

  // Extract workflow metadata
  const workflowSection = extractSection(yaml, 'workflow:');
  if (workflowSection) {
    result.workflow = {
      planner_mode: extractValue(workflowSection, 'planner_mode') as any,
      steps: [], // We'll extract from backend response
    };
  }

  // Extract policies
  const policiesSection = extractSection(yaml, 'policies:');
  if (policiesSection) {
    result.policies = {
      budget_usd: parseFloat(extractValue(policiesSection, 'budget_usd') || '0') || undefined,
      pii: extractObject(policiesSection, 'pii'),
      defaults: extractObject(policiesSection, 'defaults'),
      rate_limits: extractObject(policiesSection, 'rate_limits'),
    };
  }

  // Extract credentials
  const credentialsSection = extractSection(yaml, 'credentials:');
  if (credentialsSection) {
    result.credentials = {
      uses: extractList(credentialsSection, 'uses'),
    };
  }

  // Extract form fields
  const formSection = extractSection(yaml, 'form:');
  if (formSection) {
    result.form = {
      fields: extractFormFields(formSection),
    };
  }

  // Extract workflow steps
  if (workflowSection) {
    result.workflow = {
      ...result.workflow,
      steps: extractWorkflowSteps(workflowSection),
    };
  }

  return result;
}

function extractSection(yaml: string, sectionName: string): string | null {
  const lines = yaml.split('\n');
  const startIdx = lines.findIndex(l => l.trim() === sectionName);
  if (startIdx === -1) return null;

  const indent = lines[startIdx].search(/\S/);
  let endIdx = startIdx + 1;

  while (endIdx < lines.length) {
    const line = lines[endIdx];
    if (line.trim() === '') {
      endIdx++;
      continue;
    }
    const lineIndent = line.search(/\S/);
    if (lineIndent <= indent && line.trim() !== '') break;
    endIdx++;
  }

  return lines.slice(startIdx + 1, endIdx).join('\n');
}

function extractValue(section: string, key: string): string | null {
  const match = section.match(new RegExp(`${key}:\\s*(.+)`));
  return match ? match[1].trim() : null;
}

function extractList(section: string, key: string): string[] {
  const lines = section.split('\n');
  const keyIdx = lines.findIndex(l => l.includes(`${key}:`));
  if (keyIdx === -1) return [];

  const items: string[] = [];
  for (let i = keyIdx + 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.startsWith('-')) {
      items.push(line.substring(1).trim());
    } else if (line && !line.startsWith('#')) {
      break;
    }
  }

  return items;
}

function extractObject(section: string, key: string): any {
  const subSection = extractSection(section, `${key}:`);
  if (!subSection) return null;

  const obj: any = {};
  const lines = subSection.split('\n');

  for (const line of lines) {
    const match = line.match(/(\w+):\s*(.+)/);
    if (match) {
      const [, k, v] = match;
      obj[k] = v.replace(/"/g, '').trim();
    }
  }

  return Object.keys(obj).length > 0 ? obj : null;
}

function extractFormFields(formSection: string): any[] {
  // This is complex - for now return empty, we'll use the backend response
  return [];
}

function extractWorkflowSteps(workflowSection: string): WorkflowStepDraft[] {
  const steps: WorkflowStepDraft[] = [];
  const stepsSection = extractSection(workflowSection, 'steps:');
  if (!stepsSection) return steps;

  // Parse each step (starts with "- id:")
  const lines = stepsSection.split('\n');
  let currentStep: any = null;
  let currentKey = '';
  let collectingMultiline = false;
  let multilineContent: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // New step starts
    if (trimmed.startsWith('- id:')) {
      if (currentStep) {
        steps.push(normalizeStep(currentStep));
      }
      currentStep = { id: trimmed.substring(5).trim() };
      collectingMultiline = false;
      continue;
    }

    if (!currentStep) continue;

    // Handle multiline (|)
    if (trimmed.includes('|') && trimmed.endsWith(':')) {
      currentKey = trimmed.substring(0, trimmed.indexOf(':')).trim();
      collectingMultiline = true;
      multilineContent = [];
      continue;
    }

    if (collectingMultiline) {
      if (line.match(/^\s{6,}/)) {
        // Part of multiline content
        multilineContent.push(line.trim());
      } else {
        // End of multiline
        currentStep[currentKey] = multilineContent.join('\n');
        collectingMultiline = false;

        // Process this line normally
        const match = trimmed.match(/^(\w+):\s*(.+)/);
        if (match) {
          currentStep[match[1]] = match[2].replace(/"/g, '').trim();
        }
      }
      continue;
    }

    // Regular key-value
    const match = trimmed.match(/^(\w+):\s*(.+)/);
    if (match) {
      currentStep[match[1]] = match[2].replace(/"/g, '').trim();
    }
  }

  if (currentStep) {
    steps.push(normalizeStep(currentStep));
  }

  return steps;
}

function normalizeStep(rawStep: any): WorkflowStepDraft {
  return {
    id: rawStep.id,
    name: rawStep.name || rawStep.id,
    type: rawStep.type || 'ai.extract',
    description: rawStep.description,
    instruction: rawStep.instruction,
    temperature: rawStep.temperature ? parseFloat(rawStep.temperature) : undefined,
    max_tokens: rawStep.max_tokens ? parseInt(rawStep.max_tokens) : undefined,
    tool: rawStep.tool,
    word_cap: rawStep.word_cap ? parseInt(rawStep.word_cap) : undefined,
    // Note: params, schema, expect, branches_enum are complex nested structures
    // For simplicity, we skip them in this basic parser
    // User can edit YAML directly for complex configurations
  };
}

function checkForAdvancedFeatures(parsed: ParsedYamlStructure): { supported: boolean; reasons: string[] } {
  const reasons: string[] = [];

  // Check for advanced features that Guided Builder doesn't support
  // For now, we support most common features, so this is lenient

  // Add checks here as needed, e.g.:
  // - Complex conditional logic
  // - Custom retry policies per step
  // - Advanced templating

  return {
    supported: reasons.length === 0,
    reasons,
  };
}

function mapToDraft(compileResponse: CompileFlowResponse, parsedYaml: ParsedYamlStructure): FlowDraft {
  // Extract form fields from compile response
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

  // Map workflow steps from parsed YAML
  const workflowSteps: WorkflowStepDraft[] = parsedYaml.workflow?.steps || [];

  // Extract PII policy
  let piiPolicy: 'disallow' | 'tokenize' | 'allow_with_warning' = 'disallow';
  if (parsedYaml.policies?.pii) {
    const allow = parsedYaml.policies.pii.allow === 'true';
    const tokenize = parsedYaml.policies.pii.tokenize === 'true';
    if (tokenize) piiPolicy = 'tokenize';
    else if (allow) piiPolicy = 'allow_with_warning';
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
      timeout_ms: parsedYaml.policies?.defaults?.timeout_ms
        ? parseInt(parsedYaml.policies.defaults.timeout_ms)
        : undefined,
      continue_on_fail: parsedYaml.policies?.defaults?.continue_on_fail === 'true',
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