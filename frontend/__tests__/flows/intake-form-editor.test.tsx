import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react';
import { useState } from 'react';
import jsYaml from 'js-yaml';
import { FormSection } from '@/components/flows/register/guided/form-section';
import { draftToUnifiedYaml } from '@/lib/flows/yaml-generator';
import { setActiveDomainPack } from '@/lib/flows/domain-packs/registry';
import { emptyDraft, type FlowDraft } from '@/lib/flows/types';

afterEach(() => {
  cleanup();
  setActiveDomainPack('generic');
});

function Harness({ initial }: { initial?: FlowDraft }) {
  const [draft, setDraft] = useState<FlowDraft>(
    initial ??
      emptyDraft({
        form: { fields: [{ name: 'project_name', type: 'string', title: 'Project name' }] },
      }),
  );
  return (
    <div>
      <FormSection draft={draft} onChange={(u) => setDraft((d) => ({ ...d, ...u }))} />
      <pre data-testid="yaml">{draftToUnifiedYaml(draft)}</pre>
    </div>
  );
}

describe('Intake form editor — business mode', () => {
  it('shows a neutral "Form Fields" heading and friendly controls, not raw JSON', () => {
    render(<Harness />);
    // Default pack is generic — no domain wording on a fresh flow.
    expect(screen.getByRole('heading', { name: /form fields/i })).toBeInTheDocument();
    expect(screen.queryByText(/collect rfq\/rfp request information/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Field label')).toBeInTheDocument();
    expect(screen.getByLabelText('Field type')).toBeInTheDocument();
    // No JSON-schema words like "minLength"/"pattern" leak into business mode.
    expect(screen.queryByText(/minLength|pattern/i)).not.toBeInTheDocument();
  });

  it('relabels the section from the intake metadata when a domain pack is active', () => {
    setActiveDomainPack('procurement');
    render(<Harness />);
    expect(
      screen.getByRole('heading', { name: /collect rfq\/rfp request information/i }),
    ).toBeInTheDocument();
  });

  it('adds a field', () => {
    render(<Harness />);
    expect(screen.getAllByLabelText('Field label')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: /add field/i }));
    expect(screen.getAllByLabelText('Field label')).toHaveLength(2);
  });

  it('scrolls a newly added field into view', () => {
    const spy = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /add field/i }));
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });

  it('removes a field', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /remove field/i }));
    expect(screen.queryByLabelText('Field label')).not.toBeInTheDocument();
  });

  it('auto-derives the field key from the label until the key is customised', () => {
    render(<Harness />);
    const labels = screen.getAllByLabelText('Field label');
    fireEvent.change(labels[0], { target: { value: 'Estimated value (EUR)' } });
    expect((screen.getByLabelText('Field key') as HTMLInputElement).value).toBe(
      'estimated_value_eur',
    );
  });

  it('long text compiles to a textarea widget in YAML', () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText('Field type'), { target: { value: 'long_text' } });
    expect(screen.getByTestId('yaml').textContent).toContain('widget: textarea');
  });

  it('choice reveals a choices input that compiles to enum', () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText('Field type'), { target: { value: 'choice' } });
    fireEvent.change(screen.getByLabelText('Choices'), { target: { value: 'low, medium, high' } });
    const reparsed = jsYaml.load(screen.getByTestId('yaml').textContent ?? '') as any;
    expect(reparsed.form.fields[0].enum).toEqual(['low', 'medium', 'high']);
  });

  it('switches to the expert editor and exposes the raw Type/constraints', () => {
    render(<Harness />);
    expect(screen.queryByText('Constraints')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('switch', { name: /expert mode/i }));
    // Expert row shows the technical "Name" label and the Constraints disclosure.
    expect(screen.getByText('Constraints')).toBeInTheDocument();
    expect(screen.queryByLabelText('Field label')).not.toBeInTheDocument();
  });
});

describe('Intake form editor — accessibility', () => {
  it('gives every field control an accessible name and a labelled remove button', () => {
    render(<Harness />);
    const row = screen.getByLabelText('Field label').closest('div.border') as HTMLElement;
    const scoped = within(row);
    expect(scoped.getByLabelText('Field label')).toBeInTheDocument();
    expect(scoped.getByLabelText('Field key')).toBeInTheDocument();
    expect(scoped.getByLabelText('Field type')).toBeInTheDocument();
    expect(scoped.getByLabelText('Help text')).toBeInTheDocument();
    expect(scoped.getByRole('button', { name: /remove field project name/i })).toBeInTheDocument();
  });

  it('add and remove are operated through accessible buttons', () => {
    render(<Harness />);
    const add = screen.getByRole('button', { name: /add field/i });
    fireEvent.click(add);
    const removes = screen.getAllByRole('button', { name: /remove field/i });
    expect(removes).toHaveLength(2);
    fireEvent.click(removes[1]);
    expect(screen.getAllByRole('button', { name: /remove field/i })).toHaveLength(1);
  });
});
