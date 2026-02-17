'use client';

// ============================================================
// Sidebar navigation layout
// ============================================================

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/components/auth/AuthProvider';
import { cn } from '@/lib/utils';
import {
  LayoutDashboard,
  PlayCircle,
  List,
  FileText,
  Settings,
  LogOut,
  Mic,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard, permission: null },
  { href: '/setup', label: 'New Interview', icon: PlayCircle, permission: 'create_session' },
  { href: '/sessions', label: 'Sessions', icon: List, permission: 'view_session' },
  { href: '/reports', label: 'Reports', icon: FileText, permission: 'view_reports' },
  { href: '/admin', label: 'Admin', icon: Settings, permission: null },
];

export function Sidebar() {
  const { user, logout, hasPermission } = useAuth();
  const pathname = usePathname();

  if (!user) return null;

  const filteredItems = NAV_ITEMS.filter(
    (item) => !item.permission || hasPermission(item.permission)
  );

  return (
    <aside className="flex h-screen w-64 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      {/* Logo / Title */}
      <div className="flex items-center gap-2 px-6 py-5">
        <Mic className="h-6 w-6 text-sidebar-primary" />
        <span className="text-lg font-bold text-sidebar-foreground">HackGeniX</span>
      </div>

      <div className="mx-4 h-px bg-sidebar-border" />

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {filteredItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== '/' && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                  : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground'
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mx-4 h-px bg-sidebar-border" />

      {/* User info + logout */}
      <div className="px-4 py-4">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-sidebar-primary text-xs font-bold text-sidebar-primary-foreground">
            {user.id.charAt(0).toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <p className="truncate text-sm font-medium text-sidebar-foreground">{user.id}</p>
            <Badge variant="secondary" className="text-xs bg-sidebar-accent text-sidebar-accent-foreground border-0">
              {user.role.replace('_', ' ')}
            </Badge>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="w-full border-sidebar-border text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
          onClick={logout}
        >
          <LogOut className="mr-2 h-4 w-4" />
          Sign Out
        </Button>
      </div>
    </aside>
  );
}
