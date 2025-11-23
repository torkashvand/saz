'use client';

import dynamic from 'next/dynamic';
import type { ValidationResult } from '@/lib/flows/types';

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false });

interface FlowBuilderYamlProps {
  yaml: string;
  onChange: (yaml: string) => void;
  validationResult: ValidationResult | null;
}

export function FlowBuilderYaml({ yaml, onChange, validationResult }: FlowBuilderYamlProps) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 border border-slate-200 rounded-lg overflow-hidden">
        <MonacoEditor
          height="calc(100vh - 280px)"
          language="yaml"
          value={yaml}
          onChange={(value) => onChange(value || '')}
          theme="vs-light"
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            tabSize: 2,
            wordWrap: 'on',
          }}
        />
      </div>

      {/* Validation Summary */}
      {validationResult && (
        <div className="mt-4 p-4 border border-slate-200 rounded-lg bg-white">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-900">Validation Status</h3>
            {validationResult.validated_at && (
              <span className="text-xs text-slate-500">
                {validationResult.validated_at.toLocaleTimeString()}
              </span>
            )}
          </div>

          {validationResult.valid ? (
            <div className="flex items-start gap-2 text-sm text-green-700">
              <div className="flex-shrink-0 w-1.5 h-1.5 rounded-full bg-green-500 mt-1.5"></div>
              <div>
                <div className="font-medium">Valid</div>
                {validationResult.flow_name && (
                  <div className="text-xs text-slate-600 mt-0.5">
                    Flow: {validationResult.flow_name}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-start gap-2 text-sm text-red-700">
                <div className="flex-shrink-0 w-1.5 h-1.5 rounded-full bg-red-500 mt-1.5"></div>
                <div className="font-medium">{validationResult.errors.length} errors found</div>
              </div>
              <div className="pl-4 space-y-1">
                {validationResult.errors.slice(0, 5).map((err, idx) => (
                  <div key={idx} className="text-xs text-red-600">
                    {err.section && <span className="font-mono">[{err.section}]</span>} {err.message}
                  </div>
                ))}
                {validationResult.errors.length > 5 && (
                  <div className="text-xs text-slate-500">
                    ...and {validationResult.errors.length - 5} more
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}