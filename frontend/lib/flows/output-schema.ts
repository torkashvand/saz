// Friendly representation of the supported JSON-Schema subset used by AI-op
// `expect` fields, plus a strict codec. The reverse (schemaToFriendly) is
// all-or-nothing: any key outside the supported subset makes the whole schema
// "unsupported" so the editor can fall back to a raw view without ever
// rewriting or dropping fields it does not understand.

export type OutputScalarType = 'string' | 'number' | 'integer' | 'boolean';
export type OutputFieldType = OutputScalarType | 'array';

export interface FriendlyOutputField {
  name: string;
  type: OutputFieldType;
  /** Item type when `type === 'array'`. Scalar only. */
  itemType?: OutputScalarType;
  required: boolean;
  /** Allowed values; applies to a scalar field or to array item values. */
  enumValues?: string[];
  /** Numeric bounds; only meaningful for number/integer. */
  minimum?: number;
  maximum?: number;
  /** Array length bounds; only meaningful for `type === 'array'`. */
  minItems?: number;
  maxItems?: number;
  /** Optional human description; applies to any field. */
  description?: string;
}

export interface FriendlyOutputSchema {
  fields: FriendlyOutputField[];
  additionalProperties: boolean;
}

export interface SchemaParseResult {
  supported: boolean;
  schema: FriendlyOutputSchema;
}

const SCALARS: ReadonlySet<string> = new Set(['string', 'number', 'integer', 'boolean']);

export function emptyOutputSchema(): FriendlyOutputSchema {
  return { fields: [], additionalProperties: false };
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function coerceEnum(type: OutputFieldType | OutputScalarType, values: string[]): unknown[] {
  if (type === 'number' || type === 'integer') {
    return values.map((v) => Number(v)).filter((n) => !Number.isNaN(n));
  }
  return values;
}

/** Compile a friendly schema to the exact JSON-Schema shape the backend validates. */
export function friendlyToSchema(friendly: FriendlyOutputSchema): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];

  for (const f of friendly.fields) {
    if (!f.name) continue;
    let prop: Record<string, unknown>;
    if (f.type === 'array') {
      const itemType: OutputScalarType = f.itemType ?? 'string';
      const items: Record<string, unknown> = { type: itemType };
      if (f.enumValues && f.enumValues.length > 0) items.enum = coerceEnum(itemType, f.enumValues);
      prop = { type: 'array', items };
      if (typeof f.minItems === 'number') prop.minItems = f.minItems;
      if (typeof f.maxItems === 'number') prop.maxItems = f.maxItems;
    } else {
      prop = { type: f.type };
      if (f.enumValues && f.enumValues.length > 0) prop.enum = coerceEnum(f.type, f.enumValues);
      if (f.type === 'number' || f.type === 'integer') {
        if (typeof f.minimum === 'number') prop.minimum = f.minimum;
        if (typeof f.maximum === 'number') prop.maximum = f.maximum;
      }
    }
    if (f.description && f.description.trim()) prop.description = f.description;
    properties[f.name] = prop;
    if (f.required) required.push(f.name);
  }

  const out: Record<string, unknown> = {
    type: 'object',
    additionalProperties: friendly.additionalProperties,
    properties,
  };
  if (required.length > 0) out.required = required;
  return out;
}

const UNSUPPORTED: SchemaParseResult = { supported: false, schema: emptyOutputSchema() };

const ALLOWED_ROOT_KEYS = new Set(['type', 'properties', 'required', 'additionalProperties']);
const ALLOWED_SCALAR_KEYS = new Set(['type', 'enum', 'minimum', 'maximum', 'description']);
const ALLOWED_ARRAY_KEYS = new Set(['type', 'items', 'minItems', 'maxItems', 'description']);
const ALLOWED_ITEM_KEYS = new Set(['type', 'enum']);

function enumToStrings(raw: unknown): string[] | null {
  if (!Array.isArray(raw)) return null;
  return raw.map((v) => String(v));
}

/**
 * Best-effort reverse of friendlyToSchema. Returns `supported: false` (and an
 * empty schema) the moment anything outside the v1 subset appears, so callers
 * keep the raw JSON untouched instead of risking a lossy rewrite.
 */
export function schemaToFriendly(expect: unknown): SchemaParseResult {
  if (expect === null || expect === undefined) {
    return { supported: true, schema: emptyOutputSchema() };
  }
  if (!isPlainObject(expect)) return UNSUPPORTED;
  if (expect.type !== 'object') return UNSUPPORTED;
  for (const k of Object.keys(expect)) if (!ALLOWED_ROOT_KEYS.has(k)) return UNSUPPORTED;

  const additionalProperties = expect.additionalProperties;
  if (additionalProperties !== undefined && typeof additionalProperties !== 'boolean') {
    return UNSUPPORTED;
  }

  const requiredRaw = expect.required;
  if (requiredRaw !== undefined && !Array.isArray(requiredRaw)) return UNSUPPORTED;
  const requiredSet = new Set<string>(
    Array.isArray(requiredRaw) ? requiredRaw.map((r) => String(r)) : [],
  );

  const properties = expect.properties;
  if (properties !== undefined && !isPlainObject(properties)) return UNSUPPORTED;

  const fields: FriendlyOutputField[] = [];
  for (const [name, rawProp] of Object.entries(properties ?? {})) {
    if (!isPlainObject(rawProp)) return UNSUPPORTED;
    const type = rawProp.type;

    if (type === 'array') {
      for (const k of Object.keys(rawProp)) if (!ALLOWED_ARRAY_KEYS.has(k)) return UNSUPPORTED;
      const items = rawProp.items;
      if (!isPlainObject(items)) return UNSUPPORTED;
      for (const k of Object.keys(items)) if (!ALLOWED_ITEM_KEYS.has(k)) return UNSUPPORTED;
      if (typeof items.type !== 'string' || !SCALARS.has(items.type)) return UNSUPPORTED;
      const field: FriendlyOutputField = {
        name,
        type: 'array',
        itemType: items.type as OutputScalarType,
        required: requiredSet.has(name),
      };
      if (items.enum !== undefined) {
        const e = enumToStrings(items.enum);
        if (e === null) return UNSUPPORTED;
        field.enumValues = e;
      }
      if (rawProp.minItems !== undefined) {
        if (typeof rawProp.minItems !== 'number') return UNSUPPORTED;
        field.minItems = rawProp.minItems;
      }
      if (rawProp.maxItems !== undefined) {
        if (typeof rawProp.maxItems !== 'number') return UNSUPPORTED;
        field.maxItems = rawProp.maxItems;
      }
      if (rawProp.description !== undefined) {
        if (typeof rawProp.description !== 'string') return UNSUPPORTED;
        field.description = rawProp.description;
      }
      fields.push(field);
      continue;
    }

    if (typeof type !== 'string' || !SCALARS.has(type)) return UNSUPPORTED;
    for (const k of Object.keys(rawProp)) if (!ALLOWED_SCALAR_KEYS.has(k)) return UNSUPPORTED;
    const field: FriendlyOutputField = {
      name,
      type: type as OutputScalarType,
      required: requiredSet.has(name),
    };
    if (rawProp.enum !== undefined) {
      const e = enumToStrings(rawProp.enum);
      if (e === null) return UNSUPPORTED;
      field.enumValues = e;
    }
    if (rawProp.minimum !== undefined) {
      if (typeof rawProp.minimum !== 'number') return UNSUPPORTED;
      field.minimum = rawProp.minimum;
    }
    if (rawProp.maximum !== undefined) {
      if (typeof rawProp.maximum !== 'number') return UNSUPPORTED;
      field.maximum = rawProp.maximum;
    }
    if (rawProp.description !== undefined) {
      if (typeof rawProp.description !== 'string') return UNSUPPORTED;
      field.description = rawProp.description;
    }
    fields.push(field);
  }

  return {
    supported: true,
    schema: { fields, additionalProperties: additionalProperties ?? false },
  };
}
