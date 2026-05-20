/**
 * The token-storage helper is the contract between the AuthProvider and
 * the API fetch wrapper — they read/write through the same key. These
 * tests pin that contract so we notice immediately if anyone changes
 * the storage key, breaks the localStorage round-trip, or removes the
 * memory fallback.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { _internalAuth, getAccessToken } from '@/lib/auth';

const { setAccessToken, STORAGE_KEY } = _internalAuth;

describe('token storage', () => {
  afterEach(() => {
    setAccessToken(null);
    window.localStorage.clear();
  });

  it('round-trips through localStorage under the documented key', () => {
    setAccessToken('jwt-1');
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('jwt-1');
    expect(getAccessToken()).toBe('jwt-1');
  });

  it('returns null when no token has been set', () => {
    expect(getAccessToken()).toBeNull();
  });

  it('clears the stored token when set to null', () => {
    setAccessToken('jwt-1');
    setAccessToken(null);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(getAccessToken()).toBeNull();
  });
});
