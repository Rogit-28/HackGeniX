'use client';

// ============================================================
// App shell — conditionally renders sidebar (hidden on login page)
// ============================================================

import { usePathname } from 'next/navigation';
import { useAuth } from '@/components/auth/AuthProvider';
import { Sidebar } from './Sidebar';

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user } = useAuth();

  // Don't show sidebar on login page or when not authenticated
  const showSidebar = user && pathname !== '/login';

  if (!showSidebar) {
    return <>{children}</>;
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto bg-muted/50">
        <div className="container mx-auto max-w-6xl px-6 py-6">
          {children}
        </div>
      </main>
    </div>
  );
}
