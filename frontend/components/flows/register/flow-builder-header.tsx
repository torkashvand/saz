'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { FileCode, Layout, Check, Circle, Loader2, AlertCircle, BookOpen } from 'lucide-react';
import type { FlowBuilderMode } from '@/lib/flows/types';
import { TemplatePicker } from './template-picker';

interface FlowBuilderHeaderProps {
  mode: FlowBuilderMode;
  onModeChange: (mode: FlowBuilderMode) => void;
  onTemplateSelect: (template: string) => void;
  onClear: () => void;
  onRegister: () => void;
  isRegistering: boolean;
  isValid: boolean;
  flowName?: string;
  isEditMode?: boolean;
  dirty?: boolean;
  lastSavedAt?: Date | null;
  isSaving?: boolean;
  saveError?: string | null;
}

export function FlowBuilderHeader({
  mode,
  onModeChange,
  onTemplateSelect,
  onClear,
  onRegister,
  isRegistering,
  isValid,
  flowName,
  isEditMode = false,
  dirty = false,
  lastSavedAt,
  isSaving = false,
  saveError = null,
}: FlowBuilderHeaderProps) {
  const [pickerOpen, setPickerOpen] = useState(false);

  const formatLastSaved = (date: Date | null) => {
    if (!date) return '';
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="border-b border-slate-200 bg-white">
      <div className="max-w-[1800px] mx-auto px-6 py-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-semibold text-slate-900">
                {isEditMode
                  ? flowName && flowName !== 'new_flow'
                    ? `Edit Workflow: ${flowName}`
                    : 'Edit Workflow'
                  : 'Create Workflow'}
              </h1>
              <SaveStatusChip
                isValid={isValid}
                isSaving={isSaving}
                saveError={saveError}
                dirty={dirty}
                lastSavedAt={lastSavedAt || null}
                formatLastSaved={formatLastSaved}
              />
            </div>
            {!isEditMode && (
              <p className="text-sm text-slate-600 mt-1">
                Define your workflow using Guided Builder or YAML
              </p>
            )}
          </div>

          <div className="flex items-center gap-3">
            {!isEditMode && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPickerOpen(true)}
                data-testid="open-template-picker"
              >
                <BookOpen className="h-4 w-4 mr-1.5" aria-hidden="true" />
                Browse templates
              </Button>
            )}

            <Button variant="outline" size="sm" onClick={onClear}>
              Clear draft
            </Button>

            <Button
              onClick={onRegister}
              disabled={isSaving || !isValid}
              className="bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
            >
              {isSaving ? (
                <>
                  <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Check className="h-4 w-4 mr-1.5" />
                  Save
                </>
              )}
            </Button>
          </div>
        </div>

        {!isEditMode && (
          <TemplatePicker
            open={pickerOpen}
            onClose={() => setPickerOpen(false)}
            onSelect={(templateId) => {
              setPickerOpen(false);
              onTemplateSelect(templateId);
            }}
          />
        )}

        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-600 mr-2">Mode:</span>
          <div className="inline-flex rounded-md border border-slate-300 bg-slate-50">
            <button
              onClick={() => onModeChange('guided')}
              className={`
                flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors
                ${
                  mode === 'guided'
                    ? 'bg-white text-slate-900 shadow-sm'
                    : 'text-slate-600 hover:text-slate-900'
                }
              `}
            >
              <Layout className="h-4 w-4" />
              Guided Builder
            </button>
            <button
              onClick={() => onModeChange('yaml')}
              className={`
                flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-l border-slate-300
                ${
                  mode === 'yaml'
                    ? 'bg-white text-slate-900 shadow-sm'
                    : 'text-slate-600 hover:text-slate-900'
                }
              `}
            >
              <FileCode className="h-4 w-4" />
              YAML Expert
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function SaveStatusChip({
  isValid,
  isSaving,
  saveError,
  dirty,
  lastSavedAt,
  formatLastSaved,
}: {
  isValid: boolean;
  isSaving: boolean;
  saveError: string | null;
  dirty: boolean;
  lastSavedAt: Date | null;
  formatLastSaved: (date: Date | null) => string;
}) {
  // State machine for save status display
  if (isSaving) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded bg-blue-50 text-blue-700">
        <Loader2 className="h-3 w-3 animate-spin" />
        Saving...
      </span>
    );
  }

  if (saveError) {
    return (
      <span
        className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded bg-red-100 text-red-700 border border-red-300 cursor-help"
        title={saveError}
      >
        <AlertCircle className="h-3 w-3" />
        Save failed
      </span>
    );
  }

  if (!isValid) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded bg-red-100 text-red-700 border border-red-300">
        Invalid – see errors
      </span>
    );
  }

  if (dirty) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded bg-slate-100 text-slate-600">
        <Circle className="h-2 w-2 fill-current" />
        Unsaved changes
      </span>
    );
  }

  if (lastSavedAt) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded bg-green-100 text-green-700">
        Saved {formatLastSaved(lastSavedAt)}
      </span>
    );
  }

  return null;
}
