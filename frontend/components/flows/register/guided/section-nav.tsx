'use client';

import { Info, FileText, Zap, Shield, GitBranch, Activity } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ValidationError } from '@/lib/flows/types';

interface Section {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const SECTIONS: Section[] = [
  { id: 'basics', label: 'Basics', icon: Info },
  { id: 'form', label: 'Form', icon: FileText },
  { id: 'triggers', label: 'Triggers', icon: Zap },
  { id: 'policies', label: 'Policies & Credentials', icon: Shield },
  { id: 'telemetry', label: 'Telemetry', icon: Activity },
  { id: 'steps', label: 'Workflow Steps', icon: GitBranch },
];

const SECTION_FOR_ERROR: Record<string, string> = {
  flow: 'basics',
  form: 'form',
  triggers: 'triggers',
  policies: 'policies',
  telemetry: 'telemetry',
  workflow: 'steps',
};

interface SectionNavProps {
  activeSection?: string;
  onSectionClick: (sectionId: string) => void;
  errors?: ValidationError[];
}

export function SectionNav({ activeSection, onSectionClick, errors = [] }: SectionNavProps) {
  const errorCounts: Record<string, number> = {};
  for (const err of errors) {
    const sec = err.section ? SECTION_FOR_ERROR[err.section] : undefined;
    if (sec) errorCounts[sec] = (errorCounts[sec] || 0) + 1;
  }

  return (
    <nav className="flex flex-col gap-1" aria-label="Guided builder sections">
      {SECTIONS.map((section) => {
        const Icon = section.icon;
        const isActive = activeSection === section.id;
        const count = errorCounts[section.id] || 0;
        return (
          <button
            key={section.id}
            onClick={() => onSectionClick(section.id)}
            className={cn(
              'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors text-left',
              isActive
                ? 'bg-blue-50 text-blue-700 border-l-2 border-blue-600'
                : 'text-slate-700 hover:bg-slate-100',
            )}
            aria-current={isActive ? 'true' : undefined}
          >
            <Icon className="h-4 w-4 flex-shrink-0" />
            <span className="flex-1">{section.label}</span>
            {count > 0 && (
              <span
                aria-label={`${count} error${count === 1 ? '' : 's'} in ${section.label}`}
                className="ml-auto text-[10px] font-semibold bg-red-600 text-white px-1.5 py-0.5 rounded-full"
              >
                {count}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
