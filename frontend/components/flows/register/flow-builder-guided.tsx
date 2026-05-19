'use client';

import { useState } from 'react';
import type { FlowDraft } from '@/lib/flows/types';
import { SectionNav } from './guided/section-nav';
import { BasicsSection } from './guided/basics-section';
import { FormSection } from './guided/form-section';
import { TriggersSection } from './guided/triggers-section';
import { PoliciesSection } from './guided/policies-section';
import { WorkflowStepsSection } from './guided/workflow-steps-section';

interface FlowBuilderGuidedProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

export function FlowBuilderGuided({ draft, onChange }: FlowBuilderGuidedProps) {
  const [activeSection, setActiveSection] = useState<string>('basics');

  const handleSectionClick = (sectionId: string) => {
    setActiveSection(sectionId);
    const element = document.getElementById(sectionId);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return (
    <div className="flex gap-6">
      {/* Left: Section Nav */}
      <div className="w-56 flex-shrink-0 sticky top-6 self-start">
        <SectionNav activeSection={activeSection} onSectionClick={handleSectionClick} />
      </div>

      {/* Center: Scrollable Content */}
      <div className="flex-1 space-y-6 pb-12">
        <BasicsSection draft={draft} onChange={onChange} />
        <FormSection draft={draft} onChange={onChange} />
        <TriggersSection draft={draft} onChange={onChange} />
        <PoliciesSection draft={draft} onChange={onChange} />
        <WorkflowStepsSection draft={draft} onChange={onChange} />
      </div>
    </div>
  );
}
