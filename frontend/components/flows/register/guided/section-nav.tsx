'use client';

import { Info, FileText, Zap, Shield, GitBranch } from 'lucide-react';
import { cn } from '@/lib/utils';

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
  { id: 'steps', label: 'Workflow Steps', icon: GitBranch },
];

interface SectionNavProps {
  activeSection?: string;
  onSectionClick: (sectionId: string) => void;
}

export function SectionNav({ activeSection, onSectionClick }: SectionNavProps) {
  return (
    <nav className="flex flex-col gap-1">
      {SECTIONS.map((section) => {
        const Icon = section.icon;
        const isActive = activeSection === section.id;

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
          >
            <Icon className="h-4 w-4 flex-shrink-0" />
            <span>{section.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
