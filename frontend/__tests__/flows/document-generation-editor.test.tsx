import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react';
import { useState } from 'react';
import { DocumentGenerationEditor } from '@/components/flows/register/guided/business-step-editors/document-generation-editor';
import { draftToUnifiedYaml } from '@/lib/flows/yaml-generator';
import { GENERIC_STEP_METADATA } from '@/lib/flows/business-step-metadata';
import { setActiveDomainPack } from '@/lib/flows/domain-packs/registry';
import { emptyDraft, type FlowDraft, type WorkflowStepDraft } from '@/lib/flows/types';

afterEach(() => {
  cleanup();
  // The registry is module-global; restore the default (generic) pack.
  setActiveDomainPack('generic');
});

function Harness({ initial }: { initial?: Partial<WorkflowStepDraft> }) {
  const [step, setStep] = useState<WorkflowStepDraft>({
    id: 'render_draft',
    type: 'tool.call',
    tool: 'docx_render',
    params: { require_all: false, values: {} },
    ...initial,
  });
  const draft: FlowDraft = {
    ...emptyDraft(),
    form: {
      fields: [
        { name: 'project_name', type: 'string', title: 'Project name' },
        { name: 'reference_number', type: 'string', title: 'Reference number' },
      ],
    },
    workflow: { planner_mode: 'deterministic', steps: [step] },
  };
  return (
    <div>
      <DocumentGenerationEditor
        step={step}
        draft={draft}
        priorStepIds={[]}
        onChange={(u) => setStep((s) => ({ ...s, ...u }))}
      />
      <pre data-testid="yaml">{draftToUnifiedYaml(draft)}</pre>
    </div>
  );
}

describe('DocumentGenerationEditor', () => {
  it('renders business-friendly sections and no raw JSON by default', () => {
    render(<Harness />);
    expect(screen.getByText(/document purpose/i)).toBeInTheDocument();
    expect(screen.getByText(/field mappings/i)).toBeInTheDocument();
    // No raw params JSON editor exposed by default.
    expect(screen.queryByLabelText(/render_draft-params/i)).not.toBeInTheDocument();
  });

  it('hides advanced technical settings until expanded', () => {
    render(<Harness />);
    expect(screen.queryByLabelText(/render_draft-params/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /advanced/i }));
    expect(screen.getByLabelText(/render_draft-params/i)).toBeInTheDocument();
  });

  it('maps a form field through the binding picker and compiles to valid YAML params', () => {
    render(<Harness />);

    fireEvent.click(screen.getByRole('button', { name: /add field mapping/i }));
    // Key renames commit on blur (per-keystroke renames could collide with an
    // existing key mid-typing and silently drop a mapping).
    fireEvent.change(screen.getByLabelText(/field name for mapping 1/i), {
      target: { value: 'title_system_name' },
    });
    fireEvent.blur(screen.getByLabelText(/field name for mapping 1/i));
    fireEvent.change(screen.getByLabelText(/source for mapping 1/i), {
      target: { value: 'form' },
    });
    fireEvent.change(screen.getByLabelText(/form field for mapping 1/i), {
      target: { value: 'project_name' },
    });

    const yaml = screen.getByTestId('yaml').textContent ?? '';
    expect(yaml).toContain('title_system_name: "{{ $form.project_name }}"');
  });

  it('switches the document purpose between draft and final (require_all)', () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/document purpose/i), { target: { value: 'final' } });
    const yaml = screen.getByTestId('yaml').textContent ?? '';
    expect(yaml).toContain('require_all: true');
  });
});

describe('DocumentGenerationEditor — driven by business-step metadata', () => {
  it('renders the purpose options from metadata, not hardcoded text', () => {
    render(<Harness />);
    const select = screen.getByLabelText(/document purpose/i);
    const metaOptions =
      GENERIC_STEP_METADATA.document_generation.groups?.[0].fields.find(
        (f) => f.path === 'params.require_all',
      )?.options ?? [];
    expect(metaOptions.length).toBeGreaterThan(0);
    for (const opt of metaOptions) {
      expect(within(select).getByText(opt.label)).toBeInTheDocument();
    }
  });

  it('uses the active domain pack to label the template field', () => {
    // Default (generic) pack uses the plain metadata label.
    const { unmount } = render(<Harness />);
    expect(screen.getByLabelText('Template')).toBeInTheDocument();
    expect(screen.queryByLabelText('RFQ/RFP template')).not.toBeInTheDocument();
    unmount();

    // Procurement pack overrides params.template → "RFQ/RFP template".
    setActiveDomainPack('procurement');
    render(<Harness />);
    expect(screen.getByLabelText('RFQ/RFP template')).toBeInTheDocument();
  });
});

describe('DocumentGenerationEditor — configuration preview', () => {
  function preview() {
    return screen.getByRole('region', { name: /configuration preview/i });
  }

  it('flags mappings that still need a value', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /add field mapping/i }));
    expect(within(preview()).getByText(/needs a value/i)).toBeInTheDocument();
  });

  it('updates the preview once a binding is added', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /add field mapping/i }));
    fireEvent.change(screen.getByLabelText(/source for mapping 1/i), { target: { value: 'form' } });
    fireEvent.change(screen.getByLabelText(/form field for mapping 1/i), {
      target: { value: 'project_name' },
    });
    const dl = within(preview());
    expect(dl.getByText('Fields mapped')).toBeInTheDocument();
    expect(dl.getByText(/all mapped fields have a value/i)).toBeInTheDocument();
  });

  it('never exposes raw template/JSON syntax in the preview', () => {
    render(
      <Harness
        initial={{
          params: {
            require_all: false,
            output_name: 'rfq_{{ $form.reference_number }}',
            values: {},
          },
        }}
      />,
    );
    const text = preview().textContent ?? '';
    expect(text).not.toContain('{{');
    expect(text.toLowerCase()).not.toContain('json');
  });
});
