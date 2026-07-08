// Codec for an AI-op step's `params.data` map. The friendly editor represents
// it as binding rows (field -> template expression). Anything that is not a
// flat all-string `{ data: {...} }` map is reported unsupported so the editor
// can fall back to a raw JSON view without losing structure.

import { isPlainObject } from '../utils';

export interface InputDataReadResult {
  supported: boolean;
  values: Record<string, string>;
}

export function readInputData(params: Record<string, unknown> | undefined): InputDataReadResult {
  if (params === undefined) return { supported: true, values: {} };
  const keys = Object.keys(params);
  if (keys.length === 0) return { supported: true, values: {} };
  if (keys.some((k) => k !== 'data')) return { supported: false, values: {} };

  const data = params.data;
  if (data === undefined) return { supported: true, values: {} };
  if (!isPlainObject(data)) return { supported: false, values: {} };

  const values: Record<string, string> = {};
  for (const [k, v] of Object.entries(data)) {
    if (typeof v !== 'string') return { supported: false, values: {} };
    values[k] = v;
  }
  return { supported: true, values };
}

export function writeInputData(
  _params: Record<string, unknown> | undefined,
  values: Record<string, string>,
): Record<string, unknown> | undefined {
  if (Object.keys(values).length === 0) return undefined;
  return { data: values };
}
