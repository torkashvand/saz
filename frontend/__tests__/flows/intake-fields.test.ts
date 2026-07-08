import { describe, it, expect } from 'vitest';
import jsYaml from 'js-yaml';
import {
  FRIENDLY_FIELD_TYPES,
  ISO_DATE_PATTERN,
  applyFriendlyFieldType,
  deriveFieldKey,
  keyTracksLabel,
  toFriendlyFieldType,
  type FriendlyFieldType,
} from '@/lib/flows/intake-fields';
import { draftToUnifiedYaml } from '@/lib/flows/yaml-generator';
import { emptyDraft, type FlowDraft, type FlowFormField } from '@/lib/flows/types';

function field(o: Partial<FlowFormField>): FlowFormField {
  return { name: 'f', type: 'string', ...o };
}

describe('toFriendlyFieldType', () => {
  it('classifies each backend shape into a friendly type', () => {
    expect(toFriendlyFieldType(field({ type: 'string' }))).toBe('short_text');
    expect(toFriendlyFieldType(field({ type: 'text', widget: 'textarea' }))).toBe('long_text');
    expect(toFriendlyFieldType(field({ type: 'string', widget: 'textarea' }))).toBe('long_text');
    expect(toFriendlyFieldType(field({ type: 'number' }))).toBe('number');
    expect(toFriendlyFieldType(field({ type: 'integer' }))).toBe('number');
    expect(toFriendlyFieldType(field({ type: 'boolean' }))).toBe('yes_no');
    expect(toFriendlyFieldType(field({ type: 'string', enum: ['a', 'b'] }))).toBe('choice');
    expect(toFriendlyFieldType(field({ type: 'string', pattern: ISO_DATE_PATTERN }))).toBe('date');
  });
});

describe('applyFriendlyFieldType', () => {
  const types: FriendlyFieldType[] = FRIENDLY_FIELD_TYPES.map((t) => t.value);

  it('round-trips every friendly type through apply → classify', () => {
    for (const t of types) {
      const applied = applyFriendlyFieldType(field({ name: 'x', title: 'X' }), t);
      expect(toFriendlyFieldType(applied)).toBe(t);
    }
  });

  it('preserves author-set constraints the target type can express', () => {
    // Regression: toggling long_text ↔ short_text used to discard format /
    // minLength / maxLength (while deliberately preserving pattern).
    const email = field({ format: 'email', minLength: 5, maxLength: 100 });
    const asLong = applyFriendlyFieldType(email, 'long_text');
    expect(asLong.format).toBe('email');
    expect(asLong.minLength).toBe(5);
    expect(asLong.maxLength).toBe(100);
    const backToShort = applyFriendlyFieldType(asLong, 'short_text');
    expect(backToShort.format).toBe('email');
    expect(backToShort.minLength).toBe(5);

    const bounded = field({ type: 'number', minimum: 0, maximum: 10 });
    const reapplied = applyFriendlyFieldType(bounded, 'number');
    expect(reapplied.minimum).toBe(0);
    expect(reapplied.maximum).toBe(10);
  });

  it('preserves identity fields when switching type', () => {
    const start = field({ name: 'budget', title: 'Budget', required: true, description: 'EUR' });
    const next = applyFriendlyFieldType(start, 'number');
    expect(next.name).toBe('budget');
    expect(next.title).toBe('Budget');
    expect(next.required).toBe(true);
    expect(next.description).toBe('EUR');
  });

  it('clears stale markers when leaving long-text / date / choice', () => {
    const long = applyFriendlyFieldType(field({ widget: 'textarea' }), 'short_text');
    expect(long.widget).toBeUndefined();

    const date = applyFriendlyFieldType(field({ pattern: ISO_DATE_PATTERN }), 'short_text');
    expect(date.pattern).toBeUndefined();

    const choice = applyFriendlyFieldType(field({ enum: ['a'] }), 'number');
    expect(choice.enum).toBeUndefined();
  });

  it('maps "date" to a pattern-constrained string, never a backend date format', () => {
    const date = applyFriendlyFieldType(field({}), 'date');
    expect(date.type).toBe('string');
    expect(date.pattern).toBe(ISO_DATE_PATTERN);
    expect(date.format).toBeUndefined();
  });
});

describe('deriveFieldKey / keyTracksLabel', () => {
  it('slugifies a label into a template-safe key', () => {
    expect(deriveFieldKey('Estimated value (EUR)')).toBe('estimated_value_eur');
    expect(deriveFieldKey('  Reference  Number  ')).toBe('reference_number');
  });

  it('treats auto-generated and label-derived keys as tracking', () => {
    expect(keyTracksLabel(field({ name: 'field_1' }))).toBe(true);
    expect(keyTracksLabel(field({ name: 'project_name', title: 'Project name' }))).toBe(true);
    expect(keyTracksLabel(field({ name: 'custom_key', title: 'Project name' }))).toBe(false);
  });
});

describe('friendly intake fields generate valid YAML', () => {
  it('serialises long-text (widget) and choice (enum) and round-trips them', () => {
    const draft: FlowDraft = {
      ...emptyDraft(),
      form: {
        fields: [
          applyFriendlyFieldType(field({ name: 'scope', title: 'Scope' }), 'long_text'),
          applyFriendlyFieldType(
            field({ name: 'criticality', title: 'Criticality', enum: ['low', 'high'] }),
            'choice',
          ),
          applyFriendlyFieldType(field({ name: 'issued', title: 'Issued' }), 'date'),
        ],
      },
    };
    const yaml = draftToUnifiedYaml(draft);
    const reparsed = jsYaml.load(yaml) as any;
    const [scope, crit, issued] = reparsed.form.fields;
    expect(scope.widget).toBe('textarea');
    expect(crit.enum).toEqual(['low', 'high']);
    expect(issued.pattern).toBe(ISO_DATE_PATTERN);
    expect(issued.format).toBeUndefined();
  });
});
