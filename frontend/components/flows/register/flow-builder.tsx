'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import type {
  FlowDraft,
  FlowBuilderMode,
  ValidationError,
  ValidationResult,
} from '@/lib/flows/types';
import { emptyDraft } from '@/lib/flows/types';
import { draftToUnifiedYaml } from '@/lib/flows/yaml-generator';
import { yamlToDraft } from '@/lib/flows/yaml-parser';
import { useRegisterFlow, useUpdateFlow } from '@/lib/hooks';
import { useToast } from '@/components/ui/use-toast';
import { FlowBuilderHeader } from './flow-builder-header';
import { FlowBuilderGuided } from './flow-builder-guided';
import { FlowBuilderYaml } from './flow-builder-yaml';
import { FlowPreviewPanel } from './flow-preview-panel';
import { api } from '@/lib/api';
import type { FlowLintResponse, LintFinding } from '@/lib/types';
import { AlertCircle } from 'lucide-react';

type LastUpdatedBy = 'builder' | 'yaml' | null;

// A blocking lint finding renders through the same per-step/preview error path
// as compile errors.
function lintToValidationError(f: LintFinding): ValidationError {
  return {
    section: 'consistency',
    step_id: f.step_id ?? undefined,
    code: f.code,
    message: f.suggested_fix ? `${f.message} (${f.suggested_fix})` : f.message,
  };
}

function lintWarningText(f: LintFinding): string {
  return f.step_id ? `${f.step_id}: ${f.message}` : f.message;
}

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
  const updateMutation = useUpdateFlow(flowId || '');

  const [mode, setMode] = useState<FlowBuilderMode>('guided');
  const [draft, setDraft] = useState<FlowDraft>(initialDraft || emptyDraft());
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
  const [lintResult, setLintResult] = useState<FlowLintResponse | null>(null);

  const autoValidateTimer = useRef<NodeJS.Timeout | null>(null);
  const directCompileTimer = useRef<NodeJS.Timeout | null>(null);
  const lintTimer = useRef<NodeJS.Timeout | null>(null);
  const isUpdating = useRef(false);
  const initialLoadComplete = useRef(!!initialYaml);
  const initialParseRan = useRef(false);

  // Edit mode: parse the initial YAML once into the semantic draft.
  useEffect(() => {
    if (!initialYaml || initialParseRan.current) return;
    // The ref above already guards against double-invocation in React
    // strict mode dev — adding a cleanup-based cancellation flag races
    // against it, because the cleanup fires before the async completes
    // and silently drops the parsed result. We trust the ref and let
    // the async finish.
    initialParseRan.current = true;
    (async () => {
      const result = await yamlToDraft(initialYaml);
      if (result.ok) {
        setDraft(result.draft);
        setValidationResult(buildValidation(result));
      } else if (result.advanced) {
        setMode('yaml');
        setBuilderDisabled(true);
        setAdvancedMessage(result.errors[0]?.message || 'Advanced features detected');
        setValidationResult({ valid: false, errors: result.errors });
      } else {
        setMode('yaml');
        setValidationResult({ valid: false, errors: result.errors });
      }
    })();
  }, [initialYaml]);

  useEffect(() => {
    if (initialLoadComplete.current || !isEditMode) {
      const isDirty = yaml !== lastSavedYaml && yaml.trim() !== '';
      setDirty(isDirty);
    }
  }, [yaml, lastSavedYaml, isEditMode]);

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

  // Guided edits → regenerate YAML AND run a debounced direct compile so the
  // user sees validation feedback without flipping to YAML mode.
  useEffect(() => {
    if (lastUpdatedBy === 'builder' || (mode === 'guided' && !yaml.trim())) {
      const generated = draftToUnifiedYaml(draft);
      setYaml(generated);

      if (mode === 'guided') {
        if (directCompileTimer.current) clearTimeout(directCompileTimer.current);
        directCompileTimer.current = setTimeout(() => {
          runDirectCompile(generated);
        }, 500);
      }
    }
    return () => {
      if (directCompileTimer.current) clearTimeout(directCompileTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, lastUpdatedBy, mode]);

  // YAML edits → debounced parse into draft.
  useEffect(() => {
    if (mode === 'yaml' && lastUpdatedBy === 'yaml') {
      if (autoValidateTimer.current) clearTimeout(autoValidateTimer.current);
      autoValidateTimer.current = setTimeout(() => {
        syncYamlToDraft();
      }, 700);
    }
    return () => {
      if (autoValidateTimer.current) clearTimeout(autoValidateTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [yaml, mode, lastUpdatedBy]);

  // Debounced consistency lint on whatever YAML is current (both modes). Lint
  // is best-effort: a failure never blocks the editor, it just clears findings.
  useEffect(() => {
    if (!yaml.trim()) {
      setLintResult(null);
      return;
    }
    if (lintTimer.current) clearTimeout(lintTimer.current);
    lintTimer.current = setTimeout(async () => {
      try {
        setLintResult(await api.lintFlow({ yaml }));
      } catch {
        setLintResult(null);
      }
    }, 500);
    return () => {
      if (lintTimer.current) clearTimeout(lintTimer.current);
    };
  }, [yaml]);

  const runDirectCompile = async (generated: string) => {
    if (!generated.trim()) return;
    try {
      const response = await api.compileFlow({ yaml: generated });
      if (response.valid) {
        setValidationResult({
          valid: true,
          errors: [],
          warnings: response.warnings,
          validated_at: new Date(),
          flow_name: response.flow_name,
          workflow_summary: response.workflow_summary,
          form_schema: response.form_schema,
          normalized_dsl: response.normalized_dsl ?? undefined,
        });
      } else {
        const errors: ValidationError[] = (response.errors || []).map((e) => ({
          message: e.message,
          section: e.section || undefined,
          step_id: e.step_id || undefined,
          code: e.code,
          json_pointer: e.json_pointer || undefined,
        }));
        setValidationResult({
          valid: false,
          errors,
          validated_at: new Date(),
        });
      }
    } catch (err: any) {
      setValidationResult({
        valid: false,
        errors: [{ message: err?.message || 'Validation failed' }],
        validated_at: new Date(),
      });
    }
  };

  const syncYamlToDraft = async () => {
    if (isUpdating.current) return;
    if (!yaml.trim()) {
      setValidationResult({ valid: false, errors: [{ message: 'YAML content is required' }] });
      return;
    }
    isUpdating.current = true;
    try {
      const parseResult = await yamlToDraft(yaml);
      if (parseResult.ok) {
        setDraft(parseResult.draft);
        setBuilderDisabled(false);
        setAdvancedMessage(null);
        setValidationResult(buildValidation(parseResult));
      } else if (parseResult.advanced) {
        setBuilderDisabled(true);
        setAdvancedMessage(parseResult.errors[0]?.message || 'Advanced features detected');
        setValidationResult({ valid: false, errors: parseResult.errors });
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
    // Only re-serialize the draft to YAML when the guided builder has actually
    // changed something (lastUpdatedBy === 'builder' — in which case the
    // regenerate effect has already kept `yaml` in sync). Re-serializing on a
    // no-op switch produces a formatting/ordering round-trip that differs from
    // the loaded YAML and falsely flags "unsaved changes". When there are no
    // pending builder edits, keep the existing YAML untouched.
    if (newMode === 'yaml' && mode === 'guided' && lastUpdatedBy === 'builder') {
      const generated = draftToUnifiedYaml(draft);
      setYaml(generated);
    }
    setMode(newMode);
  };

  const handleTemplateSelect = async (templateId: string) => {
    if (dirty) {
      const confirmed = window.confirm('You have unsaved changes. Load template anyway?');
      if (!confirmed) return;
    }
    try {
      const template = await api.getTemplate(templateId);
      setYaml(template.yaml);
      const parseResult = await yamlToDraft(template.yaml);
      if (parseResult.ok) {
        setDraft(parseResult.draft);
        setBuilderDisabled(false);
        setAdvancedMessage(null);
        setMode('guided');
        setLastUpdatedBy('builder');
        setValidationResult(buildValidation(parseResult));
      } else if (parseResult.advanced) {
        setMode('yaml');
        setLastUpdatedBy('yaml');
        setBuilderDisabled(true);
        setAdvancedMessage(parseResult.errors[0]?.message || 'Advanced features detected');
        setValidationResult({ valid: false, errors: parseResult.errors });
      } else {
        setMode('yaml');
        setLastUpdatedBy('yaml');
        setValidationResult({ valid: false, errors: parseResult.errors });
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
    setDraft(emptyDraft());
    setYaml('');
    setValidationResult(null);
    setLastUpdatedBy(null);
    setBuilderDisabled(false);
    setAdvancedMessage(null);
    setDirty(false);
    setLastSavedYaml('');
    toast({ title: 'Cleared', description: 'Flow builder has been reset' });
  };

  // Merge consistency-lint findings into the validation result so they surface
  // per-step and in the preview and gate Save. Skipped when the YAML doesn't
  // compile — compile errors take precedence and already show.
  const lintFindings = lintResult && !lintResult.compile_error ? lintResult.findings : [];
  const lintErrors = lintFindings.filter((f) => f.severity === 'error' && !f.suppressed);
  const lintWarnings = lintFindings.filter((f) => f.severity === 'warning' && !f.suppressed);

  const effectiveValidation: ValidationResult | null =
    !validationResult && lintFindings.length === 0
      ? validationResult
      : (() => {
          const base: ValidationResult = validationResult ?? {
            valid: true,
            errors: [],
            validated_at: new Date(),
          };
          return {
            ...base,
            valid: base.valid && lintErrors.length === 0,
            errors: [...base.errors, ...lintErrors.map(lintToValidationError)],
            warnings: [...(base.warnings ?? []), ...lintWarnings.map(lintWarningText)],
          };
        })();

  const handleRegister = async () => {
    if (!yaml.trim()) {
      setSaveError('Cannot save empty workflow');
      toast({ title: 'Error', description: 'Cannot save empty workflow', variant: 'destructive' });
      return;
    }
    if (!effectiveValidation?.valid) {
      setSaveError('Fix validation errors before saving');
      toast({
        title: 'Cannot save',
        description: 'Fix validation errors below first',
        variant: 'destructive',
      });
      return;
    }
    setSaveError(null);
    setIsSaving(true);
    try {
      const result =
        isEditMode && flowId
          ? await updateMutation.mutateAsync({ yaml })
          : await registerMutation.mutateAsync({ yaml });

      setLastSavedYaml(yaml);
      setLastSavedAt(new Date());
      setDirty(false);
      setIsSaving(false);
      setSaveError(null);
      toast({ title: 'Success', description: `Workflow "${result.name}" saved successfully` });
      if (!isEditMode && !flowId) {
        setTimeout(() => {
          router.push(`/flows/${result.id}/edit`);
        }, 500);
      }
    } catch (error: any) {
      const errorMessage = error.message || 'Save failed – server returned an error';
      setIsSaving(false);
      setSaveError(errorMessage);
      toast({ title: 'Save Failed', description: errorMessage, variant: 'destructive' });
    }
  };

  const handleDraftChange = (updates: Partial<FlowDraft>) => {
    setDraft((prev) => ({ ...prev, ...updates }));
    setLastUpdatedBy('builder');
    setSaveError(null);
  };

  const handleYamlChange = (newYaml: string) => {
    setYaml(newYaml);
    setLastUpdatedBy('yaml');
    setSaveError(null);
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <FlowBuilderHeader
        mode={mode}
        onModeChange={handleModeChange}
        onTemplateSelect={handleTemplateSelect}
        onClear={handleClear}
        onRegister={handleRegister}
        isRegistering={registerMutation.isPending || updateMutation.isPending}
        isValid={effectiveValidation?.valid || false}
        flowName={draft.flow.name}
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
                <FlowBuilderGuided
                  draft={draft}
                  onChange={handleDraftChange}
                  errors={effectiveValidation?.errors || []}
                />
              )
            ) : (
              <FlowBuilderYaml
                yaml={yaml}
                onChange={handleYamlChange}
                validationResult={effectiveValidation}
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
              <FlowPreviewPanel validationResult={effectiveValidation} draft={draft} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function buildValidation(
  result: Extract<Awaited<ReturnType<typeof yamlToDraft>>, { ok: true }>,
): ValidationResult {
  return {
    valid: true,
    errors: [],
    warnings: result.warnings,
    validated_at: new Date(),
    flow_name: result.compileResponse.flow_name,
    workflow_summary: result.compileResponse.workflow_summary,
    form_schema: result.compileResponse.form_schema,
    normalized_dsl: result.compileResponse.normalized_dsl ?? undefined,
  };
}
