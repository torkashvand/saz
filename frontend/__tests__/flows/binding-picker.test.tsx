import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { BindingPicker } from '@/components/flows/register/guided/binding-picker';
import {
  bindingToExpression,
  type BindingContext,
  type FriendlyBinding,
} from '@/lib/flows/bindings';

afterEach(() => cleanup());

const context: BindingContext = {
  formFields: [
    { name: 'reference_number', type: 'string', title: 'Reference number' },
    { name: 'project_name', type: 'string', title: 'Project name' },
  ],
  steps: [{ id: 'draft_narrative', name: 'Draft narrative' }],
};

function Harness({
  label,
  onChangeSpy,
}: {
  label: string;
  onChangeSpy: (b: FriendlyBinding) => void;
}) {
  const [binding, setBinding] = useState<FriendlyBinding | null>(null);
  return (
    <BindingPicker
      label={label}
      binding={binding}
      context={context}
      onChange={(b) => {
        setBinding(b);
        onChangeSpy(b);
      }}
    />
  );
}

describe('BindingPicker', () => {
  it('converts a form selection into a {{ $form.field }} expression behind the scenes', () => {
    let last: FriendlyBinding | null = null;
    render(<Harness label="Project name" onChangeSpy={(b) => (last = b)} />);

    fireEvent.change(screen.getByLabelText(/source for Project name/i), {
      target: { value: 'form' },
    });
    fireEvent.change(screen.getByLabelText(/form field for Project name/i), {
      target: { value: 'project_name' },
    });

    expect(bindingToExpression(last as unknown as FriendlyBinding)).toBe(
      '{{ $form.project_name }}',
    );
  });

  it('converts a previous-step selection into a {{ $step(...).field }} expression', () => {
    let last: FriendlyBinding | null = null;
    render(<Harness label="Objective" onChangeSpy={(b) => (last = b)} />);

    fireEvent.change(screen.getByLabelText(/source for Objective/i), {
      target: { value: 'previous_step' },
    });
    fireEvent.change(screen.getByLabelText(/step for Objective/i), {
      target: { value: 'draft_narrative' },
    });
    fireEvent.change(screen.getByLabelText(/output field for Objective/i), {
      target: { value: 'objective' },
    });

    expect(bindingToExpression(last as unknown as FriendlyBinding)).toBe(
      "{{ $step('draft_narrative').objective }}",
    );
  });

  it('converts a system selection into a $env expression with a fallback', () => {
    let last: FriendlyBinding | null = null;
    render(<Harness label="Region" onChangeSpy={(b) => (last = b)} />);

    fireEvent.change(screen.getByLabelText(/source for Region/i), {
      target: { value: 'system' },
    });
    fireEvent.change(screen.getByLabelText(/system value for Region/i), {
      target: { value: 'REGION' },
    });
    fireEvent.change(screen.getByLabelText(/fallback for Region/i), {
      target: { value: 'eu' },
    });

    expect(bindingToExpression(last as unknown as FriendlyBinding)).toBe(
      "{{ $env('REGION', 'eu') }}",
    );
  });

  it('renders a system binding as a chip without raw expression syntax', () => {
    const { container } = render(
      <BindingPicker
        label="Region"
        binding={{ sourceType: 'system', sourceField: 'REGION' }}
        context={context}
        onChange={() => {}}
      />,
    );
    expect(container.textContent).toMatch(/system/i);
    expect(container.textContent).not.toContain('{{');
  });

  it('does not display a raw template expression in the default UI', () => {
    const binding: FriendlyBinding = { sourceType: 'form', sourceField: 'reference_number' };
    const { container } = render(
      <BindingPicker label="Reference" binding={binding} context={context} onChange={() => {}} />,
    );
    expect(container.textContent).toContain('Reference number');
    expect(container.textContent).not.toContain('{{');
  });
});
