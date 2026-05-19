'use client';

import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface BottomDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
}

export function BottomDrawer({ isOpen, onClose, title, children }: BottomDrawerProps) {
  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/20 z-40 transition-opacity" onClick={onClose} />

      {/* Drawer */}
      <div
        className={cn(
          'fixed bottom-0 left-0 right-0 bg-white border-t border-slate-200 shadow-2xl z-50',
          'transition-transform duration-300',
          isOpen ? 'translate-y-0' : 'translate-y-full',
        )}
        style={{ height: '50vh', minHeight: '400px' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-slate-50">
          <h3 className="font-semibold text-sm text-slate-900">{title || 'Details'}</h3>
          <Button variant="ghost" size="sm" onClick={onClose} className="h-7 w-7 p-0">
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Content */}
        <div className="h-[calc(100%-49px)] overflow-y-auto">{children}</div>
      </div>
    </>
  );
}
