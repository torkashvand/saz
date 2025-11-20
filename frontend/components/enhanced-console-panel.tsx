'use client';

import { useState, useMemo, useRef, useEffect } from 'react';
import { Search, X, Filter } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import type { Event } from '@/lib/types';

interface EnhancedConsolePanelProps {
  events: Event[];
  selectedStepId: string | null;
  onSelectStep: (stepId: string) => void;
}

type LevelFilter = 'all' | 'info' | 'warning' | 'error';

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('en-US', { hour12: false, fractionalSecondDigits: 3 });
}

function getEventLevel(event: Event): string {
  const type = event.event_type.toLowerCase();
  if (type.includes('error') || type.includes('failed')) return 'error';
  if (type.includes('warn') || type.includes('warning')) return 'warning';
  return 'info';
}

function LogLine({
  event,
  highlight,
  onClickStep,
}: {
  event: Event;
  highlight: string;
  onClickStep: () => void;
}) {
  const level = getEventLevel(event);
  const message = event.summary || JSON.stringify(event.payload);

  // Highlight search term
  const highlightedMessage = highlight
    ? message.replace(
        new RegExp(highlight.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'),
        (match) => `<mark class="bg-yellow-300 text-yellow-900">${match}</mark>`
      )
    : message;

  const levelColors = {
    error: 'text-red-400',
    warning: 'text-yellow-400',
    info: 'text-blue-400',
  };

  return (
    <div
      className={`
        flex gap-3 px-3 py-1.5 hover:bg-slate-700/50 font-mono text-xs
        ${level === 'error' ? 'bg-red-950/20' : ''}
        ${level === 'warning' ? 'bg-yellow-950/20' : ''}
      `}
    >
      <span className="text-slate-500 flex-shrink-0 w-24">
        {formatTimestamp(event.timestamp)}
      </span>

      {event.step_id && (
        <button
          onClick={onClickStep}
          className="px-2 py-0.5 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs flex-shrink-0 transition-colors"
          title="Jump to this step"
        >
          [step-{event.step_id.slice(0, 8)}]
        </button>
      )}

      <span className={`font-semibold flex-shrink-0 w-32 ${levelColors[level as keyof typeof levelColors]}`}>
        {event.event_type}
      </span>

      <span
        className="text-slate-200 flex-1 break-words"
        dangerouslySetInnerHTML={{ __html: highlightedMessage }}
      />
    </div>
  );
}

export function EnhancedConsolePanel({
  events,
  selectedStepId,
  onSelectStep,
}: EnhancedConsolePanelProps) {
  const [search, setSearch] = useState('');
  const [levelFilter, setLevelFilter] = useState<LevelFilter>('all');
  const [autoScroll, setAutoScroll] = useState(true);
  const logEndRef = useRef<HTMLDivElement>(null);
  const logViewerRef = useRef<HTMLDivElement>(null);

  // Filter events
  const filteredEvents = useMemo(() => {
    let result = events;

    // Filter by selected step
    if (selectedStepId) {
      result = result.filter((e) => e.step_id === selectedStepId);
    }

    // Filter by level
    if (levelFilter !== 'all') {
      result = result.filter((e) => {
        const level = getEventLevel(e);
        return level === levelFilter;
      });
    }

    // Filter by search
    if (search) {
      const lower = search.toLowerCase();
      result = result.filter((e) => {
        const message = e.summary || JSON.stringify(e.payload);
        return (
          message.toLowerCase().includes(lower) ||
          e.event_type.toLowerCase().includes(lower)
        );
      });
    }

    return result;
  }, [events, selectedStepId, levelFilter, search]);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (autoScroll && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [filteredEvents, autoScroll]);

  // Calculate stats
  const stats = useMemo(() => {
    const errorCount = events.filter((e) => getEventLevel(e) === 'error').length;
    const warningCount = events.filter((e) => getEventLevel(e) === 'warning').length;
    const infoCount = events.filter((e) => getEventLevel(e) === 'info').length;

    return { errorCount, warningCount, infoCount, total: events.length };
  }, [events]);

  return (
    <div className="flex flex-col h-full bg-slate-900 text-slate-200">
      {/* Toolbar */}
      <div className="p-3 bg-slate-800 border-b border-slate-700 space-y-3">
        {/* Search bar */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input
              type="text"
              placeholder="Search logs..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-slate-700 border-slate-600 text-slate-200 placeholder:text-slate-400 focus:border-blue-500"
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2 flex-wrap">
          <Filter className="h-4 w-4 text-slate-400" />
          <span className="text-xs font-medium text-slate-400">Level:</span>

          <button
            onClick={() => setLevelFilter('all')}
            className={`
              px-3 py-1 rounded-full text-xs font-medium transition-colors
              ${
                levelFilter === 'all'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }
            `}
          >
            All ({stats.total})
          </button>

          <button
            onClick={() => setLevelFilter('info')}
            className={`
              px-3 py-1 rounded-full text-xs font-medium transition-colors
              ${
                levelFilter === 'info'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-blue-300 hover:bg-slate-600'
              }
            `}
          >
            Info ({stats.infoCount})
          </button>

          <button
            onClick={() => setLevelFilter('warning')}
            className={`
              px-3 py-1 rounded-full text-xs font-medium transition-colors
              ${
                levelFilter === 'warning'
                  ? 'bg-yellow-600 text-white'
                  : 'bg-slate-700 text-yellow-300 hover:bg-slate-600'
              }
            `}
          >
            Warning ({stats.warningCount})
          </button>

          <button
            onClick={() => setLevelFilter('error')}
            className={`
              px-3 py-1 rounded-full text-xs font-medium transition-colors
              ${
                levelFilter === 'error'
                  ? 'bg-red-600 text-white'
                  : 'bg-slate-700 text-red-300 hover:bg-slate-600'
              }
            `}
          >
            Error ({stats.errorCount})
          </button>

          {selectedStepId && (
            <>
              <span className="text-slate-600">|</span>
              <button
                onClick={() => onSelectStep(null)}
                className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-full text-xs font-medium flex items-center gap-1 transition-colors"
              >
                Clear step filter
                <X className="h-3 w-3" />
              </button>
            </>
          )}

          <div className="ml-auto flex items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
                className="rounded border-slate-600 bg-slate-700 text-blue-600 focus:ring-blue-500 focus:ring-offset-slate-800"
              />
              Auto-scroll
            </label>
          </div>
        </div>

        {/* Filter results info */}
        {(search || selectedStepId || levelFilter !== 'all') && (
          <div className="text-xs text-slate-400">
            Showing {filteredEvents.length} of {events.length} events
          </div>
        )}
      </div>

      {/* Log viewer */}
      <div
        ref={logViewerRef}
        className="flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-800"
      >
        {filteredEvents.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-slate-500">
              <p className="text-sm">No logs match the current filters</p>
              {(search || selectedStepId || levelFilter !== 'all') && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setSearch('');
                    setLevelFilter('all');
                    onSelectStep(null);
                  }}
                  className="mt-2 text-xs text-slate-400 hover:text-slate-200"
                >
                  Clear all filters
                </Button>
              )}
            </div>
          </div>
        ) : (
          <>
            {filteredEvents.map((event) => (
              <LogLine
                key={event.id}
                event={event}
                highlight={search}
                onClickStep={() => event.step_id && onSelectStep(event.step_id)}
              />
            ))}
            <div ref={logEndRef} className="h-4" />
          </>
        )}
      </div>
    </div>
  );
}
