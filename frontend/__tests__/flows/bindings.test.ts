import { describe, it, expect } from 'vitest';
import {
  bindingToExpression,
  expressionToBinding,
  renderBindingLabel,
  validateBinding,
  type BindingContext,
  type FriendlyBinding,
} from '@/lib/flows/bindings';

const context: BindingContext = {
  formFields: [
    { name: 'reference_number', type: 'string', title: 'Reference number' },
    { name: 'weight_qualitative_pct', type: 'number', title: 'Qualitative weight (%)' },
  ],
  steps: [
    { id: 'draft_narrative', name: 'Draft narrative' },
    { id: 'supplier_feedback', name: 'Supplier feedback' },
  ],
};

describe('bindingToExpression', () => {
  it('compiles a form binding to a $form expression', () => {
    const binding: FriendlyBinding = { sourceType: 'form', sourceField: 'reference_number' };
    expect(bindingToExpression(binding)).toBe('{{ $form.reference_number }}');
  });

  it('compiles a previous-step binding with a field to a $step expression', () => {
    const binding: FriendlyBinding = {
      sourceType: 'previous_step',
      sourceStepId: 'draft_narrative',
      sourceField: 'objective',
    };
    expect(bindingToExpression(binding)).toBe("{{ $step('draft_narrative').objective }}");
  });

  it('compiles a previous-step binding without a field to a whole-output $step expression', () => {
    const binding: FriendlyBinding = {
      sourceType: 'previous_step',
      sourceStepId: 'supplier_feedback',
      sourceField: '',
    };
    expect(bindingToExpression(binding)).toBe("{{ $step('supplier_feedback') }}");
  });

  it('compiles a constant binding to its raw value', () => {
    const binding: FriendlyBinding = { sourceType: 'constant', sourceField: '0.1 DRAFT' };
    expect(bindingToExpression(binding)).toBe('0.1 DRAFT');
  });

  it('appends a formatter suffix after a form expression', () => {
    const binding: FriendlyBinding = {
      sourceType: 'form',
      sourceField: 'weight_qualitative_pct',
      formatter: '%',
    };
    expect(bindingToExpression(binding)).toBe('{{ $form.weight_qualitative_pct }}%');
  });
});

describe('expressionToBinding', () => {
  it('parses a $form expression into a form binding', () => {
    expect(expressionToBinding('{{ $form.reference_number }}')).toEqual({
      sourceType: 'form',
      sourceField: 'reference_number',
    });
  });

  it('parses a $step expression with a field into a previous-step binding', () => {
    expect(expressionToBinding("{{ $step('draft_narrative').objective }}")).toEqual({
      sourceType: 'previous_step',
      sourceStepId: 'draft_narrative',
      sourceField: 'objective',
    });
  });

  it('parses a whole-output $step expression into a previous-step binding with no field', () => {
    expect(expressionToBinding("{{ $step('supplier_feedback') }}")).toEqual({
      sourceType: 'previous_step',
      sourceStepId: 'supplier_feedback',
      sourceField: '',
    });
  });

  it('parses a plain string into a constant binding', () => {
    expect(expressionToBinding('0.1 DRAFT')).toEqual({
      sourceType: 'constant',
      sourceField: '0.1 DRAFT',
    });
  });

  it('parses a formatter suffix on a form expression', () => {
    expect(expressionToBinding('{{ $form.weight_qualitative_pct }}%')).toEqual({
      sourceType: 'form',
      sourceField: 'weight_qualitative_pct',
      formatter: '%',
    });
  });

  it('round-trips an in-progress form binding with no field chosen yet', () => {
    const expr = bindingToExpression({ sourceType: 'form', sourceField: '' });
    expect(expressionToBinding(expr)).toEqual({ sourceType: 'form', sourceField: '' });
  });

  it('round-trips every value of the real docx_render mapping', () => {
    const values = [
      '{{ $form.project_name }}',
      "{{ $step('draft_narrative').background }}",
      '0.1 DRAFT',
      '{{ $form.weight_qualitative_pct }}%',
      "{{ $step('supplier_feedback') }}",
    ];
    for (const value of values) {
      const binding = expressionToBinding(value);
      expect(binding).not.toBeNull();
      expect(bindingToExpression(binding as FriendlyBinding)).toBe(value);
    }
  });
});

describe('system bindings + fallback', () => {
  it('compiles a system (env) binding to a $env expression', () => {
    expect(bindingToExpression({ sourceType: 'system', sourceField: 'REGION' })).toBe(
      "{{ $env('REGION') }}",
    );
  });

  it('compiles a system binding with a fallback default', () => {
    expect(
      bindingToExpression({ sourceType: 'system', sourceField: 'REGION', fallback: 'eu' }),
    ).toBe("{{ $env('REGION', 'eu') }}");
  });

  it('round-trips a system binding with a fallback', () => {
    const expr = "{{ $env('REGION', 'eu') }}";
    expect(expressionToBinding(expr)).toEqual({
      sourceType: 'system',
      sourceField: 'REGION',
      fallback: 'eu',
    });
    expect(bindingToExpression(expressionToBinding(expr) as FriendlyBinding)).toBe(expr);
  });

  it('renders a system binding as a readable chip without raw syntax', () => {
    const label = renderBindingLabel({ sourceType: 'system', sourceField: 'REGION' }, context);
    expect(label).toMatch(/system/i);
    expect(label).toContain('REGION');
    expect(label).not.toContain('{{');
  });
});

describe('renderBindingLabel', () => {
  it('uses the form field title for a form binding', () => {
    const label = renderBindingLabel(
      { sourceType: 'form', sourceField: 'reference_number' },
      context,
    );
    expect(label).toContain('Reference number');
  });

  it('uses the step name and field for a previous-step binding', () => {
    const label = renderBindingLabel(
      { sourceType: 'previous_step', sourceStepId: 'draft_narrative', sourceField: 'objective' },
      context,
    );
    expect(label).toContain('Draft narrative');
    expect(label).toContain('objective');
  });

  it('shows the raw value for a constant binding', () => {
    const label = renderBindingLabel({ sourceType: 'constant', sourceField: '0.1 DRAFT' }, context);
    expect(label).toContain('0.1 DRAFT');
  });
});

describe('validateBinding', () => {
  it('accepts a form binding pointing at an existing field', () => {
    const result = validateBinding(
      { sourceType: 'form', sourceField: 'reference_number' },
      context,
    );
    expect(result.valid).toBe(true);
  });

  it('rejects a form binding pointing at a missing field with a business message', () => {
    const result = validateBinding({ sourceType: 'form', sourceField: 'gone' }, context);
    expect(result.valid).toBe(false);
    expect(result.message).toMatch(/no longer exists/i);
  });

  it('rejects a previous-step binding pointing at a missing step', () => {
    const result = validateBinding(
      { sourceType: 'previous_step', sourceStepId: 'nope', sourceField: 'x' },
      context,
    );
    expect(result.valid).toBe(false);
  });

  it('rejects a required binding with no value chosen', () => {
    const result = validateBinding(
      { sourceType: 'constant', sourceField: '', required: true },
      context,
    );
    expect(result.valid).toBe(false);
  });
});

describe('quote safety in compiled expressions', () => {
  // The template grammar has no escape for quotes inside '...' args: a
  // fallback like "it's" used to emit {{ $env('X', 'it's') }} — broken for
  // both the backend and our reverse regexes.
  it('strips single quotes from $env fallbacks so the expression round-trips', () => {
    const expr = bindingToExpression({
      sourceType: 'system',
      sourceField: 'GREETING',
      fallback: "it's fine",
    });
    expect(expr).toBe("{{ $env('GREETING', 'its fine') }}");
    const back = expressionToBinding(expr);
    expect(back).toMatchObject({
      sourceType: 'system',
      sourceField: 'GREETING',
      fallback: 'its fine',
    });
  });

  it('treats a composite expression as a constant, not a lossy single-source binding', () => {
    // Splitting this into a previous_step binding would bury the second
    // template in the "formatter" and mislabel where the value comes from.
    const composite = "{{ $step('a').b }} and {{ $form.c }}";
    expect(expressionToBinding(composite)).toEqual({
      sourceType: 'constant',
      sourceField: composite,
    });
  });

  it('strips single quotes from step ids in $step refs', () => {
    const expr = bindingToExpression({
      sourceType: 'previous_step',
      sourceStepId: "we'ird",
      sourceField: 'total',
    });
    expect(expr).toBe("{{ $step('weird').total }}");
    expect(expressionToBinding(expr)).toMatchObject({
      sourceType: 'previous_step',
      sourceStepId: 'weird',
    });
  });
});
