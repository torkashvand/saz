import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Validate a post-login redirect target. Only same-origin paths are allowed:
 * '//evil.com' is protocol-relative and '/\evil.com' is normalized to it by
 * browsers, so both would leave the site. Anything suspect falls back to '/'.
 */
export function sanitizeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith('/')) return '/';
  if (next.startsWith('//') || next.startsWith('/\\')) return '/';
  return next;
}
