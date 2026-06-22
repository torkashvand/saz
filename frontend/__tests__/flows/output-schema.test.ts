import { describe, it, expect } from 'vitest';
import {
  emptyOutputSchema,
  friendlyToSchema,
  schemaToFriendly,
  type FriendlyOutputSchema,
} from '@/lib/flows/output-schema';

describe('friendlyToSchema', () => {
  it('compiles scalars, enum, bounds, array-of-scalar, description, minItems, required and additionalProperties', () => {
    const friendly: FriendlyOutputSchema = {
      additionalProperties: false,
      fields: [
        {
          name: 'change_intent',
          type: 'string',
          required: true,
          description: 'One-sentence restatement',
        },
        {
          name: 'risk_level',
          type: 'string',
          required: true,
          enumValues: ['low', 'medium', 'high', 'critical'],
        },
        { name: 'score', type: 'integer', required: false, minimum: 0, maximum: 100 },
        { name: 'approved', type: 'boolean', required: false },
        { name: 'pre_checks', type: 'array', itemType: 'string', required: true, minItems: 1 },
      ],
    };
    expect(friendlyToSchema(friendly)).toEqual({
      type: 'object',
      additionalProperties: false,
      properties: {
        change_intent: { type: 'string', description: 'One-sentence restatement' },
        risk_level: { type: 'string', enum: ['low', 'medium', 'high', 'critical'] },
        score: { type: 'integer', minimum: 0, maximum: 100 },
        approved: { type: 'boolean' },
        pre_checks: { type: 'array', items: { type: 'string' }, minItems: 1 },
      },
      required: ['change_intent', 'risk_level', 'pre_checks'],
    });
  });

  it('omits required when empty and coerces numeric enum values', () => {
    const out = friendlyToSchema({
      additionalProperties: true,
      fields: [{ name: 'n', type: 'number', required: false, enumValues: ['1', '2.5'] }],
    });
    expect(out).toEqual({
      type: 'object',
      additionalProperties: true,
      properties: { n: { type: 'number', enum: [1, 2.5] } },
    });
  });
});

describe('schemaToFriendly', () => {
  it('round-trips a supported schema with description, bounds, enum and minItems', () => {
    const expect_ = {
      type: 'object',
      additionalProperties: false,
      properties: {
        change_intent: { type: 'string', description: 'One-sentence restatement' },
        risk_level: { type: 'string', enum: ['low', 'high'] },
        score: { type: 'integer', minimum: 0, maximum: 100 },
        pre_checks: { type: 'array', items: { type: 'string' }, minItems: 1 },
      },
      required: ['risk_level'],
    };
    const parsed = schemaToFriendly(expect_);
    expect(parsed.supported).toBe(true);
    expect(friendlyToSchema(parsed.schema)).toEqual(expect_);
  });

  it('marks an unknown per-property key (format) as unsupported (no rewrite)', () => {
    const parsed = schemaToFriendly({
      type: 'object',
      additionalProperties: false,
      properties: { x: { type: 'string', format: 'email' } },
    });
    expect(parsed.supported).toBe(false);
  });

  it('marks an unknown item-level key as unsupported', () => {
    const parsed = schemaToFriendly({
      type: 'object',
      properties: { items: { type: 'array', items: { type: 'string', minLength: 1 } } },
    });
    expect(parsed.supported).toBe(false);
  });

  it('marks nested object properties as unsupported', () => {
    const parsed = schemaToFriendly({
      type: 'object',
      properties: { nested: { type: 'object', properties: { a: { type: 'string' } } } },
    });
    expect(parsed.supported).toBe(false);
  });

  it('treats null/undefined as a supported empty schema', () => {
    expect(schemaToFriendly(undefined)).toEqual({ supported: true, schema: emptyOutputSchema() });
    expect(schemaToFriendly(null)).toEqual({ supported: true, schema: emptyOutputSchema() });
  });

  it('marks a non-object root type as unsupported', () => {
    expect(schemaToFriendly({ type: 'string' }).supported).toBe(false);
  });
});
