import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useRef, useState } from 'react';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

afterEach(() => cleanup());
import { ExpressionPicker } from '@/components/flows/register/guided/expression-picker';
import type { FlowDraft } from '@/lib/flows/types';
import { emptyDraft } from '@/lib/flows/types';

function Harness({ draft }: { draft: FlowDraft }) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [value, setValue] = useState('');
  return (
    <div>
      <input
        ref={inputRef}
        aria-label="target"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <ExpressionPicker
        inputRef={inputRef as React.RefObject<HTMLInputElement>}
        value={value}
        onChange={setValue}
        draft={draft}
      />
      <div aria-label="output">{value}</div>
    </div>
  );
}

describe('ExpressionPicker', () => {
  beforeEach(() => {
    // requestAnimationFrame is used to restore focus; stub so tests don't race.
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    });
  });

  it('inserts $form token for a form field at cursor', () => {
    const draft: FlowDraft = {
      ...emptyDraft(),
      form: { fields: [{ name: 'severity', type: 'string', required: true }] },
    };
    render(<Harness draft={draft} />);
    fireEvent.click(screen.getByRole('button', { name: /insert expression/i }));
    fireEvent.click(screen.getByText(/\$form\.severity/));
    expect(screen.getByLabelText('output').textContent).toBe('{{ $form.severity }}');
  });

  it('inserts $step token for prior step ids', () => {
    const draft: FlowDraft = {
      ...emptyDraft(),
      workflow: {
        planner_mode: 'deterministic',
        steps: [{ id: 'classify', type: 'ai.extract' }],
      },
    };
    render(<Harness draft={draft} />);
    fireEvent.click(screen.getByRole('button', { name: /insert expression/i }));
    // Click the step token text. It appears inside the button label.
    const tokenBtn = screen.getByText(/\$step\('classify'\)/);
    fireEvent.click(tokenBtn);
    expect(screen.getByLabelText('output').textContent).toContain("{{ $step('classify') }}");
  });

  it('shows an $env helper even when no other context exists', () => {
    render(<Harness draft={emptyDraft()} />);
    fireEvent.click(screen.getByRole('button', { name: /insert expression/i }));
    expect(screen.getByText('$env(VAR)')).toBeInTheDocument();
  });
});
