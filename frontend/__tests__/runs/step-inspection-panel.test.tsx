import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { describe, it, expect, afterEach } from 'vitest';

afterEach(cleanup);

import {
  StepInspectionPanel,
  isRecord,
  isAiStepEnvelope,
  isEmptyValue,
} from '@/components/common/json-view';
import { CompactStepCard } from '@/components/runs/step-card';
import type { DisplayStep } from '@/lib/runs/display-steps';
import type { RunStep } from '@/lib/types';

const AI_INPUT = {
  tool: 'ai.extract',
  arguments: {
    instruction: 'First paragraph of the prompt.\n\nSecond paragraph with detail.',
    data: {
      project_name: 'HR Information System',
      criticality: 'high',
      weight_qualitative_pct: 80,
    },
    expected_schema: { type: 'object' },
    temperature_override: 0.1,
    max_tokens_override: 1024,
  },
};

const AI_OUTPUT = {
  summary: 'Looks good',
  score: 7,
  recommended: true,
};

describe('type guards', () => {
  it('isRecord distinguishes plain objects', () => {
    expect(isRecord({})).toBe(true);
    expect(isRecord({ a: 1 })).toBe(true);
    expect(isRecord(null)).toBe(false);
    expect(isRecord([1, 2])).toBe(false);
    expect(isRecord('x')).toBe(false);
  });

  it('isAiStepEnvelope only matches ai.* envelopes', () => {
    expect(isAiStepEnvelope(AI_INPUT)).toBe(true);
    expect(isAiStepEnvelope({ tool: 'tool.call', arguments: {} })).toBe(false);
    expect(isAiStepEnvelope({ tool: 'ai.extract' })).toBe(false);
    expect(isAiStepEnvelope({ arguments: {} })).toBe(false);
    expect(isAiStepEnvelope('ai.extract')).toBe(false);
  });

  it('isEmptyValue treats blanks, empties and nullish as empty', () => {
    expect(isEmptyValue(null)).toBe(true);
    expect(isEmptyValue(undefined)).toBe(true);
    expect(isEmptyValue('')).toBe(true);
    expect(isEmptyValue('   ')).toBe(true);
    expect(isEmptyValue({})).toBe(true);
    expect(isEmptyValue([])).toBe(true);
    expect(isEmptyValue('text')).toBe(false);
    expect(isEmptyValue(0)).toBe(false);
    expect(isEmptyValue(false)).toBe(false);
    expect(isEmptyValue({ a: 1 })).toBe(false);
  });
});

describe('StepInspectionPanel — AI steps', () => {
  it('renders Prompt, Input data, and Output as separate sections', () => {
    render(<StepInspectionPanel input={AI_INPUT} output={AI_OUTPUT} />);

    expect(screen.getByText('Prompt')).toBeInTheDocument();
    expect(screen.getByText('Input data')).toBeInTheDocument();
    expect(screen.getByText('Output')).toBeInTheDocument();
    expect(screen.getByText(/AI step/)).toBeInTheDocument();
  });

  it('shows prompt text with real line breaks, not escaped \\n', () => {
    const { container } = render(<StepInspectionPanel input={AI_INPUT} output={AI_OUTPUT} />);

    // Prompt is collapsed by default — expand it.
    fireEvent.click(screen.getByText('Prompt'));

    expect(container.textContent).toContain('First paragraph of the prompt.\n\nSecond paragraph');
    expect(container.textContent).not.toContain('\\n');
  });

  it('hides static workflow config from the default view', () => {
    const { container } = render(<StepInspectionPanel input={AI_INPUT} output={AI_OUTPUT} />);
    // Expand every section so nothing is hidden merely by being collapsed.
    fireEvent.click(screen.getByText('Prompt'));

    expect(container.textContent).not.toContain('expected_schema');
    expect(container.textContent).not.toContain('temperature_override');
    expect(container.textContent).not.toContain('max_tokens_override');
    // The envelope `tool` key is internal plumbing and must not surface.
    expect(container.textContent).not.toContain('ai.extract');
  });

  it('renders runtime input data fields', () => {
    render(<StepInspectionPanel input={AI_INPUT} output={AI_OUTPUT} />);
    expect(screen.getByText('project_name')).toBeInTheDocument();
    expect(screen.getByText('HR Information System')).toBeInTheDocument();
  });

  it('omits the Prompt section when instruction is missing', () => {
    const input = { tool: 'ai.score', arguments: { data: { a: 1 } } };
    render(<StepInspectionPanel input={input} output={{ ok: true }} />);
    expect(screen.queryByText('Prompt')).not.toBeInTheDocument();
    expect(screen.getByText('Input data')).toBeInTheDocument();
  });

  it('omits the Input data section when arguments.data is missing', () => {
    const input = { tool: 'ai.generate', arguments: { instruction: 'Write something.' } };
    render(<StepInspectionPanel input={input} output={{ text: 'done' }} />);
    expect(screen.queryByText('Input data')).not.toBeInTheDocument();
    expect(screen.getByText('Prompt')).toBeInTheDocument();
  });

  it('renders scalar/string output from text AI ops as readable prose', () => {
    const input = { tool: 'ai.generate', arguments: { instruction: 'Write a memo.' } };
    const output = { output: 'Line one.\nLine two.' };
    const { container } = render(<StepInspectionPanel input={input} output={output} />);
    expect(screen.getByText('Output')).toBeInTheDocument();
    expect(container.textContent).toContain('Line one.\nLine two.');
    expect(container.textContent).not.toContain('\\n');
  });
});

describe('StepInspectionPanel — non-AI steps', () => {
  it('renders clean Input and Output sections', () => {
    render(
      <StepInspectionPanel
        input={{ url: 'https://example.com', method: 'POST' }}
        output={{ status: 200 }}
      />,
    );
    expect(screen.getByText('Input')).toBeInTheDocument();
    expect(screen.getByText('Output')).toBeInTheDocument();
    expect(screen.getByText(/Step data/)).toBeInTheDocument();
    expect(screen.queryByText('Prompt')).not.toBeInTheDocument();
  });

  it('does not treat a non-ai tool envelope as an AI step', () => {
    const input = { tool: 'tool.call', arguments: { instruction: 'noop' } };
    const { container } = render(<StepInspectionPanel input={input} output={{ ok: true }} />);
    expect(screen.queryByText('Prompt')).not.toBeInTheDocument();
    expect(screen.getByText('Input')).toBeInTheDocument();
    // Generic rendering shows the raw structure, including `tool`.
    expect(container.textContent).toContain('tool.call');
  });

  it('renders when input is not an object without crashing', () => {
    const { container } = render(
      <StepInspectionPanel input={'a plain string'} output={{ ok: true }} />,
    );
    expect(screen.getByText('Input')).toBeInTheDocument();
    expect(container.textContent).toContain('a plain string');
  });

  it('renders a string output without crashing', () => {
    const { container } = render(<StepInspectionPanel input={{ a: 1 }} output={'just text'} />);
    expect(screen.getByText('Output')).toBeInTheDocument();
    expect(container.textContent).toContain('just text');
  });
});

describe('StepInspectionPanel — empty handling', () => {
  it('renders nothing when both input and output are empty', () => {
    const { container } = render(<StepInspectionPanel input={{}} output={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when input and output are nullish', () => {
    const { container } = render(<StepInspectionPanel input={undefined} output={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('omits the empty section but keeps the populated one', () => {
    render(<StepInspectionPanel input={{ a: 1 }} output={{}} />);
    expect(screen.getByText('Input')).toBeInTheDocument();
    expect(screen.queryByText('Output')).not.toBeInTheDocument();
  });
});

function executedStep(overrides: Partial<RunStep>): DisplayStep {
  const step: RunStep = {
    id: 'step-1',
    number: 0,
    name: 'extract_data',
    attempt: 1,
    step_type: 'ai.extract',
    status: 'completed',
    retry_count: 0,
    ...overrides,
  };
  return { kind: 'executed', index: 0, step };
}

describe('CompactStepCard integration', () => {
  it('renders the inspection panel inside the expanded card', () => {
    const { container } = render(
      <CompactStepCard displayStep={executedStep({ input: AI_INPUT, output: AI_OUTPUT })} />,
    );

    // Collapsed by default — panel content not shown yet.
    expect(screen.queryByText('Prompt')).not.toBeInTheDocument();

    // Expand the card.
    fireEvent.click(screen.getByText(/extract_data/));

    expect(screen.getByText('Prompt')).toBeInTheDocument();
    expect(screen.getByText('Input data')).toBeInTheDocument();
    expect(screen.getByText('Output')).toBeInTheDocument();
    expect(container.textContent).not.toContain('temperature_override');
    expect(container.textContent).not.toContain('expected_schema');
  });

  it('expanding a section does not collapse the card', () => {
    render(<CompactStepCard displayStep={executedStep({ input: AI_INPUT, output: AI_OUTPUT })} />);
    fireEvent.click(screen.getByText(/extract_data/));

    fireEvent.click(screen.getByText('Prompt'));
    // Card is still expanded — sections remain visible.
    expect(screen.getByText('Input data')).toBeInTheDocument();
  });
});
