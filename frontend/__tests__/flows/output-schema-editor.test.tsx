import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { OutputSchemaEditor } from '@/components/flows/register/guided/step-editors/ai-fields/output-schema-editor';

afterEach(cleanup);

function Harness({ initial }: { initial?: unknown }) {
  const [value, setValue] = useState<unknown>(initial);
  return (
    <div>
      <OutputSchemaEditor value={value} stepId="s1" onChange={setValue} />
      <pre data-testid="json">{JSON.stringify(value)}</pre>
    </div>
  );
}

describe('OutputSchemaEditor', () => {
  it('builds a schema from GUI input without showing raw JSON by default', () => {
    render(<Harness />);
    expect(screen.queryByLabelText(/s1-expect/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /add field/i }));
    fireEvent.change(screen.getByLabelText(/field name 1/i), { target: { value: 'risk' } });
    fireEvent.change(screen.getByLabelText(/field type 1/i), { target: { value: 'string' } });
    fireEvent.click(screen.getByLabelText(/required 1/i));

    const json = JSON.parse(screen.getByTestId('json').textContent || '{}');
    expect(json).toMatchObject({
      type: 'object',
      additionalProperties: false,
      properties: { risk: { type: 'string' } },
      required: ['risk'],
    });
  });

  it('shows a warning and the raw editor for an unsupported schema, leaving it untouched', () => {
    const unsupported = {
      type: 'object',
      properties: { nested: { type: 'object', properties: { a: { type: 'string' } } } },
    };
    render(<Harness initial={unsupported} />);
    expect(screen.getByText(/can't be shown in the visual editor/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/s1-expect/i)).toBeInTheDocument();
    // The raw value is preserved exactly.
    expect(JSON.parse(screen.getByTestId('json').textContent || '{}')).toEqual(unsupported);
  });
});
