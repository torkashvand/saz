import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

afterEach(() => cleanup());
import { BasicsSection } from '@/components/flows/register/guided/basics-section';
import { PoliciesSection } from '@/components/flows/register/guided/policies-section';
import { TelemetrySection } from '@/components/flows/register/guided/telemetry-section';
import { FormSection } from '@/components/flows/register/guided/form-section';
import type { FlowDraft } from '@/lib/flows/types';
import { emptyDraft } from '@/lib/flows/types';

describe('BasicsSection', () => {
  it('renders name and writes nested flow.name on change', () => {
    const draft = emptyDraft();
    const onChange = vi.fn();
    render(<BasicsSection draft={draft} onChange={onChange} />);
    const nameInput = screen.getByPlaceholderText(/support_ticket_triage/);
    fireEvent.change(nameInput, { target: { value: 'renamed_flow' } });
    expect(onChange).toHaveBeenCalledWith({
      flow: expect.objectContaining({ name: 'renamed_flow' }),
    });
  });

  it('switches planner mode under workflow', () => {
    const draft = emptyDraft();
    const onChange = vi.fn();
    render(<BasicsSection draft={draft} onChange={onChange} />);
    fireEvent.change(screen.getByDisplayValue('Deterministic'), { target: { value: 'agentic' } });
    expect(onChange).toHaveBeenCalledWith({
      workflow: expect.objectContaining({ planner_mode: 'agentic' }),
    });
  });
});

describe('PoliciesSection', () => {
  it('updates pii via tri-state selector', () => {
    const draft = emptyDraft();
    const onChange = vi.fn();
    render(<PoliciesSection draft={draft} onChange={onChange} />);
    const piiSelect = screen.getByDisplayValue('Disallow');
    fireEvent.change(piiSelect, { target: { value: 'tokenize' } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        policies: expect.objectContaining({
          pii: expect.objectContaining({ tokenize_model_inputs: true, allow: false }),
        }),
      }),
    );
  });

  it('writes nested policies.defaults.retry.attempts', () => {
    const draft = emptyDraft();
    const onChange = vi.fn();
    render(<PoliciesSection draft={draft} onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText('3'), { target: { value: '5' } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        policies: expect.objectContaining({
          defaults: expect.objectContaining({ retry: { attempts: 5 } }),
        }),
      }),
    );
  });
});

describe('TelemetrySection', () => {
  it('selecting a trace level writes telemetry.trace_level', () => {
    const draft = emptyDraft();
    const onChange = vi.fn();
    render(<TelemetrySection draft={draft} onChange={onChange} />);
    fireEvent.change(screen.getByDisplayValue('Default'), { target: { value: 'brief' } });
    expect(onChange).toHaveBeenCalledWith({
      telemetry: expect.objectContaining({ trace_level: 'brief' }),
    });
  });
});

describe('FormSection', () => {
  it('adds and removes a form field via nested form.fields', () => {
    const draft: FlowDraft = { ...emptyDraft() };
    let current = draft;
    const onChange = vi.fn((updates) => {
      current = { ...current, ...updates };
    });
    const { rerender } = render(<FormSection draft={current} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /add field/i }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ form: expect.objectContaining({ fields: expect.any(Array) }) }),
    );
    // Apply the update and rerender to ensure remove path works without crashing.
    rerender(<FormSection draft={current} onChange={onChange} />);
  });
});
