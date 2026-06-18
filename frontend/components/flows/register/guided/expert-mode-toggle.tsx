'use client';

interface ExpertModeToggleProps {
  expert: boolean;
  onChange: (next: boolean) => void;
}

/**
 * On/off toggle for expert (source) mode. A `role="switch"` button so its state
 * is announced; the sliding pill makes the on/off state visually obvious.
 */
export function ExpertModeToggle({ expert, onChange }: ExpertModeToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={expert}
      aria-label="Expert mode"
      onClick={() => onChange(!expert)}
      className="inline-flex items-center gap-2 rounded px-1 py-0.5 hover:bg-slate-50"
    >
      <span
        className={`relative inline-block h-4 w-7 rounded-full transition-colors ${
          expert ? 'bg-slate-800' : 'bg-slate-300'
        }`}
      >
        <span
          className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${
            expert ? 'left-3.5' : 'left-0.5'
          }`}
        />
      </span>
      <span className="text-xs font-medium text-slate-600">Expert mode</span>
    </button>
  );
}
