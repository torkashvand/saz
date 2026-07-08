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

// Listeners are React setState functions, which bail out when handed the same
// object reference — state must be REASSIGNED, never mutated in place.
function setState(toasts: ToasterToast[]) {
  memoryState = { toasts };
  listeners.forEach((listener) => listener(memoryState));
}

function removeToast(id: string) {
  setState(memoryState.toasts.filter((t) => t.id !== id));
}

function dispatch(toast: Omit<ToasterToast, 'id'>) {
  const id = genId();
  setState([{ ...toast, id }, ...memoryState.toasts].slice(0, 1));

  setTimeout(() => removeToast(id), 3000);

  return { id, dismiss: () => removeToast(id) };
}

export function toast(props: Omit<Toast, 'id'>) {
  return dispatch(props);
}

export function useToast() {
  const [state, setLocalState] = React.useState(memoryState);

  React.useEffect(() => {
    listeners.push(setLocalState);
    return () => {
      const index = listeners.indexOf(setLocalState);
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
