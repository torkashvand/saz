import * as React from 'react';

export interface Toast {
  id: string;
  title?: string;
  description?: string;
  variant?: 'default' | 'destructive';
}

type ToasterToast = Toast;

let count = 0;
function genId() {
  count = (count + 1) % Number.MAX_VALUE;
  return count.toString();
}

const listeners: Array<(state: { toasts: ToasterToast[] }) => void> = [];
let memoryState: { toasts: ToasterToast[] } = { toasts: [] };

function dispatch(toast: Omit<ToasterToast, 'id'>) {
  const id = genId();
  const newToast = { ...toast, id, open: true };
  memoryState.toasts = [newToast, ...memoryState.toasts].slice(0, 1);

  listeners.forEach((listener) => {
    listener(memoryState);
  });

  setTimeout(() => {
    memoryState.toasts = memoryState.toasts.filter((t) => t.id !== id);
    listeners.forEach((listener) => listener(memoryState));
  }, 3000);

  return { id, dismiss: () => {} };
}

export function toast(props: Omit<Toast, 'id'>) {
  return dispatch(props);
}

export function useToast() {
  const [state, setState] = React.useState(memoryState);

  React.useEffect(() => {
    listeners.push(setState);
    return () => {
      const index = listeners.indexOf(setState);
      if (index > -1) {
        listeners.splice(index, 1);
      }
    };
  }, []);

  return {
    ...state,
    toast,
  };
}
