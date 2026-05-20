'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/**
 * /admin lands on the user-management page. There is no admin dashboard
 * beyond user management — this redirect keeps the URL space tidy for
 * when more admin sub-pages arrive.
 */
export default function AdminIndexPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/admin/users');
  }, [router]);
  return null;
}
