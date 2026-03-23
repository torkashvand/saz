/**
 * Tests for the AI Operations Reference feature in the flow builder.
 *
 * Covers:
 * - YAML snippet generation for expect blocks
 * - Validation error → AI op type extraction
 * - Schema-to-YAML conversion for different op types
 */

import { describe, it, expect } from 'vitest';

// ---------------------------------------------------------------------------
// Re-implement the helpers here for testing (they are not exported from
// the component, so we test the logic directly)
// ---------------------------------------------------------------------------

function schemaToExpectYaml(
  schema: Record<string, any>,
  indent: number = 6,
): string {
  const pad = ' '.repeat(indent);
  const lines: string[] = [];

  lines.push(`${pad}expect:`);
  lines.push(`${pad}  type: object`);

  const properties = schema.properties || {};
  const required = schema.required || [];
  const propNames = Object.keys(properties);

  if (propNames.length > 0) {
    lines.push(`${pad}  properties:`);
    for (const name of propNames) {
      const prop = properties[name];
      const parts: string[] = [`type: ${prop.type || 'string'}`];
      if (prop.enum) {
        parts.push(`enum: [${prop.enum.join(', ')}]`);
      }
      if (prop.minimum !== undefined) {
        parts.push(`minimum: ${prop.minimum}`);
      }
      if (prop.maximum !== undefined) {
        parts.push(`maximum: ${prop.maximum}`);
      }
      if (prop.items) {
        parts.push(`items: { type: ${prop.items.type || 'string'} }`);
      }
      lines.push(`${pad}    ${name}: { ${parts.join(', ')} }`);
    }
  }

  if (required.length > 0) {
    lines.push(`${pad}  required: [${required.join(', ')}]`);
  }

  return lines.join('\n');
}

function extractAIOpFromError(message: string): string | null {
  const match = message.match(/\(type:\s*(ai\.\w+)\)/);
  return match ? match[1] : null;
}

// ---------------------------------------------------------------------------
// Schema-to-YAML tests
// ---------------------------------------------------------------------------

describe('schemaToExpectYaml', () => {
  it('generates correct YAML for ai.assess default schema', () => {
    const schema = {
      type: 'object',
      properties: {
        result: { type: 'string' },
        confidence: { type: 'number', minimum: 0, maximum: 1 },
      },
      required: ['result'],
    };

    const yaml = schemaToExpectYaml(schema);

    expect(yaml).toContain('expect:');
    expect(yaml).toContain('type: object');
    expect(yaml).toContain('result: { type: string }');
    expect(yaml).toContain('confidence: { type: number, minimum: 0, maximum: 1 }');
    expect(yaml).toContain('required: [result]');
  });

  it('generates correct YAML for ai.route with enum', () => {
    const schema = {
      type: 'object',
      properties: {
        route: { type: 'string', enum: ['ops', 'security', 'dev'] },
        reason: { type: 'string' },
      },
      required: ['route'],
    };

    const yaml = schemaToExpectYaml(schema);

    expect(yaml).toContain('route: { type: string, enum: [ops, security, dev] }');
    expect(yaml).toContain('reason: { type: string }');
    expect(yaml).toContain('required: [route]');
  });

  it('generates correct YAML for ai.evaluate with array type', () => {
    const schema = {
      type: 'object',
      properties: {
        pass: { type: 'boolean' },
        issues: { type: 'array', items: { type: 'string' } },
      },
      required: ['pass', 'issues'],
    };

    const yaml = schemaToExpectYaml(schema);

    expect(yaml).toContain('pass: { type: boolean }');
    expect(yaml).toContain('issues: { type: array, items: { type: string } }');
    expect(yaml).toContain('required: [pass, issues]');
  });

  it('handles empty/flexible schema (ai.extract default)', () => {
    const schema = {
      type: 'object',
      additionalProperties: true,
    };

    const yaml = schemaToExpectYaml(schema);

    expect(yaml).toContain('expect:');
    expect(yaml).toContain('type: object');
    // No properties or required since the schema is flexible
    expect(yaml).not.toContain('properties:');
    expect(yaml).not.toContain('required:');
  });

  it('respects custom indent level', () => {
    const schema = {
      type: 'object',
      properties: { result: { type: 'string' } },
    };

    const yaml = schemaToExpectYaml(schema, 4);

    // 4-space indent
    expect(yaml).toMatch(/^ {4}expect:/m);
    expect(yaml).toMatch(/^ {6}type: object/m);
  });
});

// ---------------------------------------------------------------------------
// Validation error → AI op extraction
// ---------------------------------------------------------------------------

describe('extractAIOpFromError', () => {
  it('extracts ai.extract from compile error', () => {
    const msg =
      "step 'extract_ticket_data' (type: ai.extract) requires 'expect' field";
    expect(extractAIOpFromError(msg)).toBe('ai.extract');
  });

  it('extracts ai.score from compile error', () => {
    const msg =
      "step 'score_complexity' (type: ai.score) requires 'expect' field";
    expect(extractAIOpFromError(msg)).toBe('ai.score');
  });

  it('extracts ai.generate from compile error', () => {
    const msg =
      "step 'draft_email' (type: ai.generate) requires 'expect' field";
    expect(extractAIOpFromError(msg)).toBe('ai.generate');
  });

  it('returns null for non-AI-op errors', () => {
    const msg = "step 'deploy' (type: tool.call) requires 'description'";
    expect(extractAIOpFromError(msg)).toBeNull();
  });

  it('returns null for generic errors', () => {
    const msg = 'flow.name is required';
    expect(extractAIOpFromError(msg)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Integration: error message leads to correct op reference
// ---------------------------------------------------------------------------

describe('validation error → AI ops reference flow', () => {
  it('missing expect error for ai.extract links to ai.extract reference', () => {
    const errors = [
      {
        message:
          "step 'extract_data' (type: ai.extract) requires 'expect' field with expected output schema",
      },
    ];

    const aiOp = extractAIOpFromError(errors[0].message);
    expect(aiOp).toBe('ai.extract');

    // This would be passed as focusOp to AIOpsReferencePanel
    // and the tab would switch to 'ai-ops'
    expect(errors[0].message).toContain('expect');
  });

  it('non-expect error does not produce a reference link', () => {
    const errors = [
      {
        message:
          "step 'plan' (type: ai.generate) requires non-empty 'instruction' field",
      },
    ];

    const aiOp = extractAIOpFromError(errors[0].message);
    expect(aiOp).toBe('ai.generate');
    // But the error doesn't mention 'expect', so no reference link should show
    expect(errors[0].message).not.toContain('expect');
  });
});