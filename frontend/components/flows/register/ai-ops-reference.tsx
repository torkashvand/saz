'use client';

import { useState, useCallback, useEffect } from 'react';
import { useAIOps } from '@/lib/hooks';
import { Loader2, Copy, Check, ChevronRight, Zap, ArrowLeft, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { AIOpReference } from '@/lib/types';

// ---------------------------------------------------------------------------
// YAML snippet generation
// ---------------------------------------------------------------------------

function schemaToExpectYaml(schema: Record<string, any>, indent: number = 6): string {
  const pad = ' '.repeat(indent);
  const lines: string[] = [];

  lines.push(`${pad}expect:`);
  lines.push(`${pad}  type: object`);

  const properties = schema.properties || {};
  const required = schema.required || [];
  const propNames = Object.keys(properties);

  if (propNames.length > 0) {
    lines.push(`${pad}  properties:`);
    for (const name of propNames) {
      const prop = properties[name];
      const parts: string[] = [`type: ${prop.type || 'string'}`];
      if (prop.enum) {
        parts.push(`enum: [${prop.enum.join(', ')}]`);
      }
      if (prop.minimum !== undefined) {
        parts.push(`minimum: ${prop.minimum}`);
      }
      if (prop.maximum !== undefined) {
        parts.push(`maximum: ${prop.maximum}`);
      }
      if (prop.items) {
        parts.push(`items: { type: ${prop.items.type || 'string'} }`);
      }
      lines.push(`${pad}    ${name}: { ${parts.join(', ')} }`);
    }
  }

  if (required.length > 0) {
    lines.push(`${pad}  required: [${required.join(', ')}]`);
  }

  return lines.join('\n');
}

function fullStepSnippet(op: AIOpReference): string {
  const lines = [
    `    - id: my_${op.name.replace('ai.', '')}_step`,
    `      type: ${op.name}`,
    `      instruction: "TODO: describe what to ${op.name.replace('ai.', '')}"`,
  ];
  lines.push(schemaToExpectYaml(op.default_output_schema, 6));
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Copy button with feedback
// ---------------------------------------------------------------------------

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for non-secure contexts
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [text]);

  return (
    <Button variant="outline" size="sm" onClick={handleCopy} className="h-7 text-xs gap-1.5">
      {copied ? <Check className="h-3 w-3 text-green-600" /> : <Copy className="h-3 w-3" />}
      {copied ? 'Copied!' : label}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Detail view for a single AI operation
// ---------------------------------------------------------------------------

function AIOpDetail({ op, onBack }: { op: AIOpReference; onBack: () => void }) {
  const expectYaml = schemaToExpectYaml(op.default_output_schema);
  const fullSnippet = fullStepSnippet(op);
  const properties = op.default_output_schema.properties || {};
  const required = op.default_output_schema.required || [];
  const extraKeys = Object.keys(op.extras || {});
  const isFlexible = op.default_output_schema.additionalProperties === true;

  return (
    <div className="space-y-4">
      {/* Back button */}
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 transition-colors"
      >
        <ArrowLeft className="h-3 w-3" />
        All operations
      </button>

      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <Zap className="h-4 w-4 text-purple-600" />
          <h3 className="font-semibold text-sm text-slate-900">{op.name}</h3>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
            {op.output_format}
          </span>
        </div>
        <p className="text-xs text-slate-600">{op.description}</p>
      </div>

      {/* Flexible schema warning for ai.extract */}
      {isFlexible && (
        <div className="p-2.5 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800 flex gap-2">
          <Info className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
          <div>
            <span className="font-medium">Flexible schema.</span> The default accepts any fields.
            You must define exact properties, types, and required fields in your{' '}
            <code className="bg-amber-100 px-1 rounded">expect</code> for reliable results.
          </div>
        </div>
      )}

      {/* Output fields */}
      {Object.keys(properties).length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-slate-700 mb-2">Default output fields</h4>
          <div className="space-y-1">
            {Object.entries(properties).map(([name, prop]: [string, any]) => (
              <div key={name} className="flex items-start gap-2 text-xs p-1.5 rounded bg-slate-50">
                <code className="font-mono text-purple-700 flex-shrink-0">{name}</code>
                <span className="text-slate-500">{prop.type || 'any'}</span>
                {prop.enum && (
                  <span className="text-slate-400 truncate">[{prop.enum.join(', ')}]</span>
                )}
                {prop.minimum !== undefined && (
                  <span className="text-slate-400">
                    {prop.minimum}..{prop.maximum}
                  </span>
                )}
                {required.includes(name) && (
                  <span className="text-red-500 text-[10px] font-medium ml-auto">required</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Extras */}
      {extraKeys.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-slate-700 mb-2">Extras (optional params)</h4>
          <div className="space-y-1">
            {extraKeys.map((key) => (
              <div key={key} className="flex items-center gap-2 text-xs p-1.5 rounded bg-blue-50">
                <code className="font-mono text-blue-700">{key}</code>
                <span className="text-slate-500">
                  {typeof op.extras[key] === 'object'
                    ? JSON.stringify(op.extras[key])
                    : String(op.extras[key])}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Expect YAML snippet */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-medium text-slate-700">
            Starter <code className="bg-slate-100 px-1 rounded">expect</code> block
          </h4>
          <CopyButton text={expectYaml} label="Copy starter" />
        </div>
        <pre className="text-[11px] bg-slate-900 text-slate-100 p-3 rounded overflow-x-auto font-mono leading-relaxed">
          {expectYaml}
        </pre>
        <p className="text-[10px] text-slate-400 mt-1.5">
          Starter snippet — customize properties, enums, and required fields for your use case.
        </p>
      </div>

      {/* Full step snippet */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-medium text-slate-700">Starter step example</h4>
          <CopyButton text={fullSnippet} label="Copy step" />
        </div>
        <pre className="text-[11px] bg-slate-900 text-slate-100 p-3 rounded overflow-x-auto font-mono leading-relaxed">
          {fullSnippet}
        </pre>
      </div>

      {/* Usage note */}
      <div className="text-[11px] text-slate-500 border-t pt-3">
        <strong>Tip:</strong> Customize the{' '}
        <code className="bg-slate-100 px-1 rounded">expect</code> to match your actual extraction
        needs. Use <code className="bg-slate-100 px-1 rounded">enum</code> to constrain values and{' '}
        <code className="bg-slate-100 px-1 rounded">required</code> to enforce mandatory fields.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// List view of all AI operations
// ---------------------------------------------------------------------------

const OUTPUT_SUMMARY: Record<string, string> = {
  'ai.assess': 'result, confidence',
  'ai.generate': 'output (text)',
  'ai.extract': 'custom fields',
  'ai.route': 'route, reason',
  'ai.score': 'score, reason',
  'ai.normalize': 'normalized, confidence',
  'ai.match': 'id, confidence, reason',
  'ai.evaluate': 'pass, issues',
  'ai.compare': 'same, confidence, deltas',
  'ai.translate': 'output (text)',
  'ai.summarize': 'output (text)',
  'ai.plan': 'calls[]',
};

function AIOpListItem({ op, onSelect }: { op: AIOpReference; onSelect: () => void }) {
  const extras = Object.keys(op.extras || {});
  const summary = OUTPUT_SUMMARY[op.name] || '';

  return (
    <button
      onClick={onSelect}
      className="w-full text-left p-3 rounded-lg border border-slate-200 hover:border-blue-300 hover:bg-blue-50/50 transition-colors group"
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <code className="text-xs font-mono font-semibold text-purple-700">{op.name}</code>
            {extras.map((e) => (
              <span key={e} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">
                {e}
              </span>
            ))}
          </div>
          <p className="text-xs text-slate-600 line-clamp-1">{op.description}</p>
          {summary && <p className="text-[10px] text-slate-400 mt-0.5 font-mono">{summary}</p>}
        </div>
        <ChevronRight className="h-4 w-4 text-slate-300 group-hover:text-blue-500 flex-shrink-0 mt-1 transition-colors" />
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main reference panel
// ---------------------------------------------------------------------------

interface AIOpsReferencePanelProps {
  /** Pre-select an operation (e.g., from a validation error) */
  focusOp?: string | null;
  onFocusHandled?: () => void;
}

export function AIOpsReferencePanel({ focusOp, onFocusHandled }: AIOpsReferencePanelProps) {
  const { data: ops, isLoading, error } = useAIOps();
  const [selectedOp, setSelectedOp] = useState<string | null>(null);

  // Handle external focus request (e.g., from validation error action).
  // Must be in useEffect, not during render, to avoid React state-during-render.
  useEffect(() => {
    if (focusOp && focusOp !== selectedOp && ops) {
      const match = ops.find((o) => o.name === focusOp);
      if (match) {
        setSelectedOp(focusOp);
        onFocusHandled?.();
      }
    }
  }, [focusOp, ops, selectedOp, onFocusHandled]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-slate-400">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        <span className="text-sm">Loading AI operations...</span>
      </div>
    );
  }

  if (error || !ops) {
    return (
      <div className="text-center py-8 text-sm text-red-600">
        Failed to load AI operations reference.
      </div>
    );
  }

  const selected = ops.find((o) => o.name === selectedOp);

  if (selected) {
    return <AIOpDetail op={selected} onBack={() => setSelectedOp(null)} />;
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500 mb-3">
        Available AI operations. Click to see default output schema and copy a starter{' '}
        <code className="bg-slate-100 px-1 rounded">expect</code> block.
      </p>
      {ops.map((op) => (
        <AIOpListItem key={op.name} op={op} onSelect={() => setSelectedOp(op.name)} />
      ))}
    </div>
  );
}
