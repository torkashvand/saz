import { describe, it, expect } from 'vitest';
import { readInputData, writeInputData } from '@/lib/flows/ai-input-data';

describe('readInputData', () => {
  it('reads a flat string map under data', () => {
    expect(
      readInputData({ data: { env: '{{ $form.target_environment }}', host: '{{ $form.host }}' } }),
    ).toEqual({
      supported: true,
      values: { env: '{{ $form.target_environment }}', host: '{{ $form.host }}' },
    });
  });

  it('treats undefined params as supported and empty', () => {
    expect(readInputData(undefined)).toEqual({ supported: true, values: {} });
  });

  it('is unsupported when data holds a non-string value', () => {
    expect(readInputData({ data: { nested: { a: 1 } } }).supported).toBe(false);
  });

  it('is unsupported when params has keys other than data', () => {
    expect(readInputData({ data: {}, candidates: [] }).supported).toBe(false);
  });
});

describe('writeInputData', () => {
  it('writes values back under data, preserving nothing else (AI params are data-only)', () => {
    expect(writeInputData(undefined, { x: '{{ $form.x }}' })).toEqual({
      data: { x: '{{ $form.x }}' },
    });
  });

  it('returns undefined when the map is empty', () => {
    expect(writeInputData({ data: { x: '1' } }, {})).toBeUndefined();
  });
});
