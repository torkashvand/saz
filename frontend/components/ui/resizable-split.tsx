'use client';

import { useState, useRef, useEffect, useCallback } from 'react';

interface ResizableSplitProps {
  left: React.ReactNode;
  right: React.ReactNode;
  defaultLeftWidth?: number; // percentage
  minLeftWidth?: number;
  minRightWidth?: number;
  storageKey?: string;
}

export function ResizableSplit({
  left,
  right,
  defaultLeftWidth = 40,
  minLeftWidth = 20,
  minRightWidth = 30,
  storageKey = 'split-view-width',
}: ResizableSplitProps) {
  const [leftWidth, setLeftWidth] = useState(() => {
    if (typeof window === 'undefined') return defaultLeftWidth;
    const stored = localStorage.getItem(storageKey);
    return stored ? parseFloat(stored) : defaultLeftWidth;
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);

  const handleMouseDown = useCallback(() => {
    isDraggingRef.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDraggingRef.current || !containerRef.current) return;

    const container = containerRef.current;
    const rect = container.getBoundingClientRect();
    const newLeftWidth = ((e.clientX - rect.left) / rect.width) * 100;

    if (newLeftWidth >= minLeftWidth && newLeftWidth <= 100 - minRightWidth) {
      setLeftWidth(newLeftWidth);
    }
  }, [minLeftWidth, minRightWidth]);

  const handleMouseUp = useCallback(() => {
    if (isDraggingRef.current) {
      isDraggingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      localStorage.setItem(storageKey, leftWidth.toString());
    }
  }, [leftWidth, storageKey]);

  useEffect(() => {
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [handleMouseMove, handleMouseUp]);

  return (
    <div ref={containerRef} className="flex h-full w-full overflow-hidden">
      <div
        className="overflow-auto"
        style={{ width: `${leftWidth}%` }}
      >
        {left}
      </div>

      <div
        className="w-1 bg-slate-200 hover:bg-blue-400 cursor-col-resize transition-colors flex-shrink-0"
        onMouseDown={handleMouseDown}
        role="separator"
        aria-orientation="vertical"
      />

      <div
        className="overflow-auto"
        style={{ width: `${100 - leftWidth}%` }}
      >
        {right}
      </div>
    </div>
  );
}
