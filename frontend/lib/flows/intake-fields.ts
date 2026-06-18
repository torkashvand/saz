// Friendly intake-field model for the generic Business Builder.
//
// Business users pick a plain-language field type (short text, long text,
// number, date, yes/no, choice). Each maps onto the existing FlowFormField
// shape so the generated YAML stays valid against the backend DSL — which
// only knows the primitive types string/text/number/integer/boolean plus
// optional enum/pattern/widget. Nothing here introduces a new backend field
// type: "date" is a string constrained by an ISO-date pattern (the backend
// accepts pattern but not a `date` format), and "long text" is a string with
// the `widget: textarea` rendering hint.

import type { FlowFormField } from './types';

export type FriendlyFieldType =
  | 'short_text'
  | 'long_text'
  | 'number'
  | 'date'
  | 'yes_no'
  | 'choice';

export const FRIENDLY_FIELD_TYPES: ReadonlyArray<{ value: FriendlyFieldType; label: string }> = [
  { value: 'short_text', label: 'Short text' },
  { value: 'long_text', label: 'Long text' },
  { value: 'number', label: 'Number' },
  { value: 'date', label: 'Date' },
  { value: 'yes_no', label: 'Yes / no' },
  { value: 'choice', label: 'Choice' },
];

/** ISO-8601 date constraint used to represent a "date" field as a string. */
export const ISO_DATE_PATTERN = '^\\d{4}-\\d{2}-\\d{2}$';

/** Classify an existing field into one of the friendly types. */
export function toFriendlyFieldType(field: FlowFormField): FriendlyFieldType {
  if (field.type === 'boolean') return 'yes_no';
  // Presence of the enum key (even an empty list being configured) means choice.
  if (Array.isArray(field.enum)) return 'choice';
  if (field.type === 'number' || field.type === 'integer') return 'number';
  if (field.widget === 'textarea') return 'long_text';
  if ((field.type === 'string' || field.type === 'text') && field.pattern === ISO_DATE_PATTERN) {
    return 'date';
  }
  return 'short_text';
}

/**
 * Apply a friendly type to a field, clearing markers managed by other friendly
 * types so switching types never leaves stale constraints behind. Identity
 * fields (name/title/required/description) are preserved.
 */
export function applyFriendlyFieldType(
  field: FlowFormField,
  type: FriendlyFieldType,
): FlowFormField {
  const base: FlowFormField = {
    name: field.name,
    type: 'string',
    required: field.required,
    description: field.description,
    title: field.title,
    default: field.type === 'boolean' && type !== 'yes_no' ? undefined : field.default,
    // Drop our managed date pattern; preserve any author-set pattern otherwise.
    pattern: field.pattern === ISO_DATE_PATTERN ? undefined : field.pattern,
  };

  switch (type) {
    case 'short_text':
      return base;
    case 'long_text':
      return { ...base, widget: 'textarea' };
    case 'number':
      return { ...base, type: 'number' };
    case 'date':
      return { ...base, pattern: ISO_DATE_PATTERN };
    case 'yes_no':
      return {
        ...base,
        type: 'boolean',
        default: typeof field.default === 'boolean' ? field.default : undefined,
      };
    case 'choice':
      return { ...base, enum: field.enum && field.enum.length > 0 ? [...field.enum] : [] };
  }
}

/** Auto-generate a stable, template-safe key from a human label. */
export function deriveFieldKey(label: string): string {
  return label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

/**
 * Whether a field's key still tracks its label automatically. Once a user types
 * a custom key it stops matching the derived label and auto-sync stops.
 */
export function keyTracksLabel(field: FlowFormField): boolean {
  if (!field.name) return true;
  if (/^field_\d+$/.test(field.name)) return true;
  return field.name === deriveFieldKey(field.title ?? '');
}
