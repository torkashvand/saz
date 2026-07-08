/**
 * Regression: dispatch() used to mutate the shared state object and pass the
 * SAME reference to every listener; React's Object.is bailout meant Toaster
 * never re-rendered, so no toast ever appeared anywhere in the app.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { Toaster } from '@/components/ui/toaster';
import { toast } from '@/components/ui/use-toast';

describe('Toaster', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    act(() => {
      vi.runAllTimers();
    });
    vi.useRealTimers();
    cleanup();
  });

  it('renders a toast fired via toast()', () => {
    render(<Toaster />);
    act(() => {
      toast({ title: 'Saved', description: 'Credential created' });
    });
    expect(screen.getByText('Saved')).toBeInTheDocument();
    expect(screen.getByText('Credential created')).toBeInTheDocument();
  });

  it('applies the destructive variant styling', () => {
    render(<Toaster />);
    act(() => {
      toast({ title: 'Save failed', variant: 'destructive' });
    });
    const title = screen.getByText('Save failed');
    expect(title.closest('.border-destructive')).not.toBeNull();
  });

  it('auto-dismisses after the timeout', () => {
    render(<Toaster />);
    act(() => {
      toast({ title: 'Transient' });
    });
    expect(screen.getByText('Transient')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.queryByText('Transient')).toBeNull();
  });

  it('shows the newest toast when several fire in a row', () => {
    render(<Toaster />);
    act(() => {
      toast({ title: 'First' });
      toast({ title: 'Second' });
    });
    expect(screen.getByText('Second')).toBeInTheDocument();
  });

  it('dismiss() removes the toast immediately', () => {
    render(<Toaster />);
    let handle: { dismiss: () => void } | undefined;
    act(() => {
      handle = toast({ title: 'Dismiss me' });
    });
    expect(screen.getByText('Dismiss me')).toBeInTheDocument();
    act(() => {
      handle!.dismiss();
    });
    expect(screen.queryByText('Dismiss me')).toBeNull();
  });
});
