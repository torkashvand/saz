import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

/**
 * OIDC callback forwarder.
 *
 * Some IdPs register a frontend redirect URI (e.g. /api/auth/callback/oidc).
 * The browser lands here after the IdP redirect; we forward the code/state to
 * the backend's generic callback as a top-level redirect so the backend's
 * HttpOnly transaction cookie (shared across localhost ports) is sent and the
 * flow can complete there.
 */
export function GET(request: NextRequest) {
  const incoming = request.nextUrl.searchParams;
  const target = new URL(`${API_BASE_URL}/api/v1/auth/oidc/callback`);
  for (const key of ['code', 'state', 'error'] as const) {
    const value = incoming.get(key);
    if (value !== null) target.searchParams.set(key, value);
  }
  return NextResponse.redirect(target, { status: 303 });
}
