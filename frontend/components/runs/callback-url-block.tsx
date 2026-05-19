'use client';

import { useState } from 'react';
import { Copy, CheckCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface CallbackUrlBlockProps {
  /** Absolute callback URL the operator can POST to. */
  url: string;
  /**
   * Action sent in the curl example. Defaults to "approve" because the
   * curl block is a quick reference for the happy path.
   */
  exampleAction?: 'approve' | 'reject';
  /** Inline label shown above the URL. */
  label?: string;
  /**
   * Whether to render the collapsible curl example. Defaults to true;
   * callers that already document the URL elsewhere can hide it.
   */
  showCurlExample?: boolean;
}

/**
 * Read-only display of a callback URL with copy-to-clipboard + an
 * expandable curl example. Used by both HumanApprovalPanel and
 * WebhookCallbackPanel so suspended runs surface the same self-serve
 * affordance regardless of the suspension type.
 */
export function CallbackUrlBlock({
  url,
  exampleAction = 'approve',
  label = 'Webhook callback URL',
  showCurlExample = true,
}: CallbackUrlBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Browser may block clipboard in insecure contexts — the URL is
      // still visible inline, so the user can still copy manually.
    }
  };

  const curlBody =
    exampleAction === 'approve' ? '{"action": "approve"}' : '{"action": "reject", "reason": "..."}';

  return (
    <div data-testid="callback-url-block">
      <label className="text-xs font-medium uppercase tracking-wide text-slate-600">{label}</label>
      <div className="mt-1 flex gap-2">
        <code
          data-testid="callback-url-value"
          className="flex-1 rounded border border-slate-200 bg-white px-3 py-2 text-xs font-mono text-slate-800 overflow-x-auto whitespace-nowrap"
        >
          {url}
        </code>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleCopy}
          aria-label="Copy callback URL"
          data-testid="callback-url-copy"
        >
          {copied ? (
            <CheckCheck className="h-4 w-4 text-green-600" aria-hidden="true" />
          ) : (
            <Copy className="h-4 w-4" aria-hidden="true" />
          )}
        </Button>
      </div>
      {showCurlExample && (
        <details className="mt-2 text-xs text-slate-600">
          <summary className="cursor-pointer select-none">Show curl example</summary>
          <pre className="mt-2 overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
            {`curl -X POST ${url} \\
  -H "Content-Type: application/json" \\
  -d '${curlBody}'`}
          </pre>
        </details>
      )}
    </div>
  );
}
