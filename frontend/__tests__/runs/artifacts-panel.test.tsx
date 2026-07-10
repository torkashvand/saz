import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

afterEach(cleanup);

import { ArtifactsPanel } from '@/components/runs/artifacts-panel';

const getRunArtifacts = vi.fn();
const downloadArtifact = vi.fn();
const toastMock = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    getRunArtifacts: (...a: any[]) => getRunArtifacts(...a),
    downloadArtifact: (...a: any[]) => downloadArtifact(...a),
  },
}));

vi.mock('@/components/ui/use-toast', () => ({
  useToast: () => ({ toast: toastMock }),
}));

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ArtifactsPanel runId="run-1" />
    </QueryClientProvider>,
  );
}

describe('ArtifactsPanel', () => {
  beforeEach(() => {
    getRunArtifacts.mockReset();
    downloadArtifact.mockReset();
    // The real api.downloadArtifact always returns a promise.
    downloadArtifact.mockResolvedValue(undefined);
    toastMock.mockReset();
  });

  it('lists artifacts and downloads on click', async () => {
    getRunArtifacts.mockResolvedValue({
      run_id: 'run-1',
      artifacts: [
        {
          id: 'a1',
          step_id: 'render_final',
          filename: 'rfq_final_T88815.docx',
          content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          size_bytes: 109132,
          created_at: '2026-06-17T00:00:00Z',
        },
      ],
    });

    renderPanel();

    expect(await screen.findByText('rfq_final_T88815.docx')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('download-a1'));
    expect(downloadArtifact).toHaveBeenCalledWith('run-1', 'a1', 'rfq_final_T88815.docx');
  });

  it('renders nothing when there are no artifacts', async () => {
    getRunArtifacts.mockResolvedValue({ run_id: 'run-1', artifacts: [] });
    const { container } = renderPanel();
    await waitFor(() => expect(getRunArtifacts).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('REGRESSION: a failed download surfaces a toast, not an unhandled rejection', async () => {
    getRunArtifacts.mockResolvedValue({
      run_id: 'run-1',
      artifacts: [
        {
          id: 'a1',
          step_id: 'render_final',
          filename: 'report.docx',
          content_type: 'application/octet-stream',
          size_bytes: 1024,
          created_at: '2026-06-17T00:00:00Z',
        },
      ],
    });
    downloadArtifact.mockRejectedValue(new Error('HTTP 500'));

    renderPanel();
    fireEvent.click(await screen.findByTestId('download-a1'));

    // The operator must see WHY nothing downloaded.
    await waitFor(() => expect(toastMock).toHaveBeenCalled());
    expect(toastMock.mock.calls[0][0].description).toMatch(/HTTP 500/);
  });
});
