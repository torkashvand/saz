'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import dynamic from 'next/dynamic';
import type { editor } from 'monaco-editor';
import type { ValidationResult } from '@/lib/flows/types';
import { computeLineDiff, formatTimeAgo, type LineDiff } from '@/lib/flows/diff-utils';

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false });

interface FlowBuilderYamlProps {
  yaml: string;
  onChange: (yaml: string) => void;
  validationResult: ValidationResult | null;
  baselineYaml: string;
  lastSavedAt: Date | null;
  hasUnsavedChanges: boolean;
}

export function FlowBuilderYaml({
  yaml,
  onChange,
  validationResult,
  baselineYaml,
  lastSavedAt,
  hasUnsavedChanges,
}: FlowBuilderYamlProps) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const decorationsRef = useRef<string[]>([]);
  const diffTimerRef = useRef<NodeJS.Timeout | null>(null);
  const [timeAgo, setTimeAgo] = useState<string>('');

  // Update time ago every 10 seconds
  useEffect(() => {
    const updateTimeAgo = () => {
      setTimeAgo(formatTimeAgo(lastSavedAt));
    };
    updateTimeAgo();

    const interval = setInterval(updateTimeAgo, 10000);
    return () => clearInterval(interval);
  }, [lastSavedAt]);

  // Apply diff decorations (debounced)
  const applyDiffDecorations = useCallback(() => {
    if (!editorRef.current || !baselineYaml) return;

    const diffs = computeLineDiff(baselineYaml, yaml);

    const newDecorations: editor.IModelDeltaDecoration[] = diffs
      .filter((diff) => diff.changeType !== 'unchanged')
      .map((diff) => ({
        range: {
          startLineNumber: diff.lineNumber,
          startColumn: 1,
          endLineNumber: diff.lineNumber,
          endColumn: 1,
        },
        options: {
          isWholeLine: false,
          linesDecorationsClassName:
            diff.changeType === 'added' ? 'line-added-gutter' : 'line-modified-gutter',
          overviewRuler: {
            color: diff.changeType === 'added' ? '#22c55e' : '#3b82f6',
            position: 1, // right side
          },
        },
      }));

    decorationsRef.current = editorRef.current.deltaDecorations(
      decorationsRef.current,
      newDecorations
    );
  }, [yaml, baselineYaml]);

  // Debounced diff calculation on YAML change
  useEffect(() => {
    if (diffTimerRef.current) {
      clearTimeout(diffTimerRef.current);
    }

    diffTimerRef.current = setTimeout(() => {
      applyDiffDecorations();
    }, 500);

    return () => {
      if (diffTimerRef.current) {
        clearTimeout(diffTimerRef.current);
      }
    };
  }, [yaml, baselineYaml, applyDiffDecorations]);

  // Handle editor mount
  const handleEditorDidMount = (editorInstance: editor.IStandaloneCodeEditor) => {
    editorRef.current = editorInstance;
    // Apply initial decorations
    applyDiffDecorations();
  };

  return (
    <div className="flex flex-col h-full">
      {/* Change status header */}
      <div className="mb-3 px-1 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {hasUnsavedChanges ? (
            <>
              <div className="flex items-center gap-1.5">
                <div className="w-1.5 h-1.5 rounded-full bg-amber-500"></div>
                <span className="text-xs font-medium text-slate-700">Unsaved changes</span>
              </div>
              {lastSavedAt && (
                <span className="text-xs text-slate-500">• Last saved {timeAgo}</span>
              )}
            </>
          ) : (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-green-500"></div>
              <span className="text-xs font-medium text-slate-700">
                {lastSavedAt ? `Saved ${timeAgo}` : 'No changes'}
              </span>
            </div>
          )}
        </div>

        {/* Legend for change markers */}
        {hasUnsavedChanges && (
          <div className="flex items-center gap-3 text-xs text-slate-600">
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-3 border-l-2 border-green-500"></div>
              <span>Added</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-3 border-l-2 border-blue-500"></div>
              <span>Modified</span>
            </div>
          </div>
        )}
      </div>

      <div className="flex-1 border border-slate-200 rounded-lg overflow-hidden">
        <MonacoEditor
          height="calc(100vh - 280px)"
          language="yaml"
          value={yaml}
          onChange={(value) => onChange(value || '')}
          onMount={handleEditorDidMount}
          theme="vs-light"
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            tabSize: 2,
            wordWrap: 'on',
            glyphMargin: true, // Enable gutter for decorations
            overviewRulerLanes: 2,
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

      {/* CSS for gutter decorations */}
      <style jsx global>{`
        .line-added-gutter {
          background: rgba(34, 197, 94, 0.2);
          border-left: 3px solid #22c55e !important;
          width: 5px !important;
        }

        .line-modified-gutter {
          background: rgba(59, 130, 246, 0.2);
          border-left: 3px solid #3b82f6 !important;
          width: 5px !important;
        }
      `}</style>
    </div>
  );
}
