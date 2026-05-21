'use client';

import { useMemo, useState } from 'react';
import type { FlowDraft, ValidationError } from '@/lib/flows/types';
import { SectionNav } from './guided/section-nav';
import { BasicsSection } from './guided/basics-section';
import { FormSection } from './guided/form-section';
import { PoliciesSection } from './guided/policies-section';
import { TelemetrySection } from './guided/telemetry-section';
import { WorkflowStepsSection } from './guided/workflow-steps-section';

interface FlowBuilderGuidedProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
  errors?: ValidationError[];
}

export function FlowBuilderGuided({ draft, onChange, errors = [] }: FlowBuilderGuidedProps) {
  const [activeSection, setActiveSection] = useState<string>('basics');

  const stepErrors = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const err of errors) {
      const sid = err.step_id;
      if (!sid) continue;
      if (!map[sid]) map[sid] = [];
      map[sid].push(err.message);
    }
    return map;
  }, [errors]);

  const handleSectionClick = (sectionId: string) => {
    setActiveSection(sectionId);
    const element = document.getElementById(sectionId);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return (
    <div className="flex gap-6">
      <div className="w-56 flex-shrink-0 sticky top-6 self-start">
        <SectionNav
          activeSection={activeSection}
          onSectionClick={handleSectionClick}
          errors={errors}
        />
      </div>

      <div className="flex-1 space-y-6 pb-12">
        <BasicsSection draft={draft} onChange={onChange} />
        <FormSection draft={draft} onChange={onChange} />
        <PoliciesSection draft={draft} onChange={onChange} />
        <TelemetrySection draft={draft} onChange={onChange} />
        <WorkflowStepsSection draft={draft} onChange={onChange} stepErrors={stepErrors} />
      </div>
    </div>
  );
}
