'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import type { FlowDraft, FlowBuilderMode, ValidationResult } from '@/lib/flows/types';
import { draftToUnifiedYaml } from '@/lib/flows/yaml-generator';
import { yamlToDraft } from '@/lib/flows/yaml-parser';
import { useRegisterFlow } from '@/lib/hooks';
import { useToast } from '@/components/ui/use-toast';
import { FlowBuilderHeader } from './flow-builder-header';
import { FlowBuilderGuided } from './flow-builder-guided';
import { FlowBuilderYaml } from './flow-builder-yaml';
import { FlowPreviewPanel } from './flow-preview-panel';
import { AlertCircle } from 'lucide-react';

const INITIAL_DRAFT: FlowDraft = {
  name: 'new_flow',
  version: '1.0',
  description: '',
  schema_version: 1,
  planner_mode: 'deterministic',
  form_fields: [],
  triggers: {
    manual: true,
  },
  policies: {
    budget_usd: 1.0,
    pii_policy: 'disallow',
  },
  credentials: [],
  workflow_steps: [],
};

type LastUpdatedBy = 'builder' | 'yaml' | null;

interface FlowBuilderProps {
  initialYaml?: string;
  initialDraft?: FlowDraft;
  flowId?: string;
  isEditMode?: boolean;
}

export function FlowBuilder({
  initialYaml = '',
  initialDraft,
  flowId,
  isEditMode = false,
}: FlowBuilderProps) {
  const router = useRouter();
  const { toast } = useToast();
  const registerMutation = useRegisterFlow();

  const [mode, setMode] = useState<FlowBuilderMode>(initialYaml ? 'yaml' : 'guided');
  const [draft, setDraft] = useState<FlowDraft>(initialDraft || INITIAL_DRAFT);
  const [yaml, setYaml] = useState(initialYaml);
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [lastUpdatedBy, setLastUpdatedBy] = useState<LastUpdatedBy>(initialYaml ? 'yaml' : null);
  const [builderDisabled, setBuilderDisabled] = useState(false);
  const [advancedMessage, setAdvancedMessage] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [lastSavedYaml, setLastSavedYaml] = useState<string>(initialYaml);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const autoValidateTimer = useRef<NodeJS.Timeout | null>(null);
  const isUpdating = useRef(false);
  const initialLoadComplete = useRef(!!initialYaml);

  // Track dirty state
  useEffect(() => {
    if (initialLoadComplete.current || !isEditMode) {
      const isDirty = yaml !== lastSavedYaml && yaml.trim() !== '';
      setDirty(isDirty);
    }
  }, [yaml, lastSavedYaml, isEditMode]);

  // Beforeunload guard
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [dirty]);

  // Guided Builder → YAML: Generate YAML from draft
  useEffect(() => {
    if (lastUpdatedBy === 'builder' || (mode === 'guided' && !yaml.trim())) {
      const generated = draftToUnifiedYaml(draft);
      setYaml(generated);
    }
  }, [draft, lastUpdatedBy]);

  // YAML → Guided Builder: Parse YAML and sync to draft (debounced)
  useEffect(() => {
    if (mode === 'yaml' && lastUpdatedBy === 'yaml') {
      if (autoValidateTimer.current) {
        clearTimeout(autoValidateTimer.current);
      }

      autoValidateTimer.current = setTimeout(() => {
        syncYamlToDraft();
      }, 700);
    }

    return () => {
      if (autoValidateTimer.current) {
        clearTimeout(autoValidateTimer.current);
      }
    };
  }, [yaml, mode, lastUpdatedBy]);

  const syncYamlToDraft = async () => {
    if (isUpdating.current) return;
    if (!yaml.trim()) {
      setValidationResult({
        valid: false,
        errors: [{ message: 'YAML content is required' }],
      });
      return;
    }

    isUpdating.current = true;

    try {
      const parseResult = await yamlToDraft(yaml);

      if (parseResult.ok) {
        setDraft(parseResult.draft);
        setBuilderDisabled(false);
        setAdvancedMessage(null);
        setValidationResult({
          valid: true,
          errors: [],
          warnings: parseResult.warnings,
          validated_at: new Date(),
          flow_name: parseResult.compileResponse.flow_name,
          workflow_summary: parseResult.compileResponse.workflow_summary,
          form_schema: parseResult.compileResponse.form_schema,
        });
      } else if (parseResult.advanced) {
        setBuilderDisabled(true);
        setAdvancedMessage(parseResult.errors[0]?.message || 'Advanced features detected');
        setValidationResult({
          valid: false,
          errors: parseResult.errors,
        });
      } else {
        setValidationResult({
          valid: false,
          errors: parseResult.errors,
          validated_at: new Date(),
        });
      }
    } catch (error: any) {
      setValidationResult({
        valid: false,
        errors: [{ message: error.message || 'Failed to parse YAML' }],
        validated_at: new Date(),
      });
    } finally {
      isUpdating.current = false;
    }
  };

  const handleModeChange = (newMode: FlowBuilderMode) => {
    if (newMode === 'yaml' && mode === 'guided') {
      const generated = draftToUnifiedYaml(draft);
      setYaml(generated);
      setLastUpdatedBy('builder');
    }
    setMode(newMode);
  };

  const handleTemplateSelect = async (templateId: string) => {
    if (dirty) {
      const confirmed = window.confirm('You have unsaved changes. Load template anyway?');
      if (!confirmed) return;
    }

    try {
      const { api } = await import('@/lib/api');
      const template = await api.getTemplate(templateId);

      setYaml(template.yaml);
      setMode('yaml');
      setLastUpdatedBy('yaml');

      const parseResult = await yamlToDraft(template.yaml);
      if (parseResult.ok) {
        setDraft(parseResult.draft);
        setBuilderDisabled(false);
        setAdvancedMessage(null);
        setValidationResult({
          valid: true,
          errors: [],
          warnings: parseResult.warnings,
          validated_at: new Date(),
          flow_name: parseResult.compileResponse.flow_name,
          workflow_summary: parseResult.compileResponse.workflow_summary,
          form_schema: parseResult.compileResponse.form_schema,
        });
      }

      toast({
        title: 'Template Loaded',
        description: `Loaded template: ${template.metadata.title}`,
      });
    } catch (error: any) {
      toast({
        title: 'Failed to Load Template',
        description: error.message || 'An error occurred',
        variant: 'destructive',
      });
    }
  };

  const handleClear = () => {
    if (dirty) {
      const confirmed = window.confirm('You have unsaved changes. Clear anyway?');
      if (!confirmed) return;
    }

    setDraft(INITIAL_DRAFT);
    setYaml('');
    setValidationResult(null);
    setLastUpdatedBy(null);
    setBuilderDisabled(false);
    setAdvancedMessage(null);
    setDirty(false);
    setLastSavedYaml('');
    toast({
      title: 'Cleared',
      description: 'Flow builder has been reset',
    });
  };

  const handleRegister = async () => {
    // Block save if YAML is empty
    if (!yaml.trim()) {
      setSaveError('Cannot save empty workflow');
      toast({
        title: 'Error',
        description: 'Cannot save empty workflow',
        variant: 'destructive',
      });
      return;
    }

    // Block save if validation failed
    if (!validationResult?.valid) {
      setSaveError('Fix validation errors before saving');
      toast({
        title: 'Cannot save',
        description: 'Fix validation errors below first',
        variant: 'destructive',
      });
      return;
    }

    // Clear previous error and start saving
    setSaveError(null);
    setIsSaving(true);

    try {
      const result = await registerMutation.mutateAsync({ yaml });

      // Only update success state after mutation succeeds
      setLastSavedYaml(yaml);
      setLastSavedAt(new Date());
      setDirty(false);
      setIsSaving(false);
      setSaveError(null);

      toast({
        title: 'Success',
        description: `Workflow "${result.name}" saved successfully`,
      });

      if (!isEditMode && !flowId) {
        setTimeout(() => {
          router.push(`/flows/${result.id}/edit`);
        }, 500);
      }
    } catch (error: any) {
      // On failure: keep dirty state, set error, do NOT update lastSavedAt
      const errorMessage = error.message || 'Save failed – server returned an error';
      setIsSaving(false);
      setSaveError(errorMessage);
      // dirty state remains true

      toast({
        title: 'Save Failed',
        description: errorMessage,
        variant: 'destructive',
      });
    }
  };

  const handleDraftChange = (updates: Partial<FlowDraft>) => {
    setDraft((prev) => ({ ...prev, ...updates }));
    setLastUpdatedBy('builder');
    setSaveError(null); // Clear error when user edits
  };

  const handleYamlChange = (newYaml: string) => {
    setYaml(newYaml);
    setLastUpdatedBy('yaml');
    setSaveError(null); // Clear error when user edits
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <FlowBuilderHeader
        mode={mode}
        onModeChange={handleModeChange}
        onTemplateSelect={handleTemplateSelect}
        onClear={handleClear}
        onRegister={handleRegister}
        isRegistering={registerMutation.isPending}
        isValid={validationResult?.valid || false}
        flowName={draft.name}
        isEditMode={isEditMode}
        dirty={dirty}
        lastSavedAt={lastSavedAt}
        isSaving={isSaving}
        saveError={saveError}
      />

      {builderDisabled && advancedMessage && (
        <div className="max-w-[1800px] mx-auto px-6 pt-4">
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="text-sm font-semibold text-amber-900">Guided Builder Disabled</div>
              <div className="text-sm text-amber-800 mt-1">{advancedMessage}</div>
              <div className="text-xs text-amber-700 mt-1">
                You can still edit YAML and view the preview. Simplify the YAML to re-enable the
                builder.
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="max-w-[1800px] mx-auto px-6 py-6">
        <div className="grid grid-cols-12 gap-6">
          <div className="col-span-8">
            {mode === 'guided' ? (
              builderDisabled ? (
                <div className="bg-white border border-slate-200 rounded-lg p-12 text-center">
                  <AlertCircle className="h-12 w-12 text-slate-400 mx-auto mb-4" />
                  <h3 className="text-lg font-semibold text-slate-900 mb-2">
                    Guided Builder Unavailable
                  </h3>
                  <p className="text-sm text-slate-600 max-w-md mx-auto">
                    This flow uses advanced DSL features that cannot be edited in Guided Builder
                    mode. Switch to YAML Expert mode to make changes.
                  </p>
                </div>
              ) : (
                <FlowBuilderGuided draft={draft} onChange={handleDraftChange} />
              )
            ) : (
              <FlowBuilderYaml
                yaml={yaml}
                onChange={handleYamlChange}
                validationResult={validationResult}
                baselineYaml={lastSavedYaml}
                lastSavedAt={lastSavedAt}
                hasUnsavedChanges={dirty}
              />
            )}
          </div>

          <div className="col-span-4">
            <div
              className="sticky top-6 bg-white border border-slate-200 rounded-lg p-4"
              style={{ maxHeight: 'calc(100vh - 180px)' }}
            >
              <FlowPreviewPanel validationResult={validationResult} draft={draft} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
