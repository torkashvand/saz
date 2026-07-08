/**
 * Regression: the PII control was a tri-state that collapsed
 * {allow: true, tokenize_model_inputs: true} into 'allow_with_warning', so
 * re-selecting the shown option wrote tokenize_model_inputs: false — silently
 * DISABLING tokenization. All four backend states must round-trip exactly.
 */

import { describe, expect, it } from 'vitest';
import { PII_POLICIES, piiPolicyFromBackend, piiPolicyToBackend } from '@/lib/flows/types';

describe('PII policy mapping', () => {
  it('round-trips every option exactly', () => {
    for (const { value } of PII_POLICIES) {
      expect(piiPolicyFromBackend(piiPolicyToBackend(value))).toBe(value);
    }
  });

  it('maps allow+tokenize to its own option instead of silently dropping tokenization', () => {
    const value = piiPolicyFromBackend({ allow: true, tokenize_model_inputs: true });
    expect(piiPolicyToBackend(value)).toEqual({ allow: true, tokenize_model_inputs: true });
  });

  it('matches the backend defaults when pii is absent (allow=false, tokenize=true)', () => {
    expect(piiPolicyFromBackend(undefined)).toBe('tokenize');
    expect(piiPolicyFromBackend({})).toBe('tokenize');
  });
});
