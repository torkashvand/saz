'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

interface JsonViewProps {
  data: any;
  collapsed?: boolean;
}

export function JsonView({ data, collapsed = false }: JsonViewProps) {
  return (
    <pre className="text-xs bg-muted p-4 rounded overflow-auto max-h-96 font-mono">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

interface CollapsibleJsonProps {
  label: string;
  data: any;
  defaultOpen?: boolean;
}

export function CollapsibleJson({ label, data, defaultOpen = false }: CollapsibleJsonProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="border rounded-lg overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-4 py-2 bg-muted hover:bg-muted/80 transition-colors text-sm font-medium"
      >
        {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        {label}
      </button>
      {isOpen && (
        <div className="p-4">
          <JsonView data={data} />
        </div>
      )}
    </div>
  );
}
