'use client';

// ============================================================
// Login page — dev-mode role picker with token display
// ============================================================

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/components/auth/AuthProvider';
import type { Role } from '@/lib/types';
import { ROLE_PERMISSIONS } from '@/lib/types';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Mic, Copy, Shield, Key, ChevronDown } from 'lucide-react';
import { toast } from 'sonner';

const ROLES: { value: Role; label: string; description: string }[] = [
  { value: 'admin', label: 'Admin', description: 'Full system access' },
  { value: 'hiring_manager', label: 'Hiring Manager', description: 'Create & manage interviews' },
  { value: 'interviewer', label: 'Interviewer', description: 'Conduct interviews, view reports' },
  { value: 'candidate', label: 'Candidate', description: 'Participate in interviews' },
];

export default function LoginPage() {
  const [userId, setUserId] = useState('admin');
  const [role, setRole] = useState<Role>('admin');
  const [isLoading, setIsLoading] = useState(false);
  const { login, user } = useAuth();
  const router = useRouter();

  const handleLogin = async () => {
    if (!userId.trim()) {
      toast.error('Please enter a user ID');
      return;
    }

    setIsLoading(true);
    try {
      await login(userId.trim(), role);
      toast.success(`Logged in as ${role}`);
      router.push('/');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setIsLoading(false);
    }
  };

  const copyToken = () => {
    if (user?.token) {
      navigator.clipboard.writeText(user.token);
      toast.success('Token copied to clipboard');
    }
  };

  // Get permissions for the currently selected role (preview before login)
  const selectedPermissions = ROLE_PERMISSIONS[role] || [];

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-sidebar via-sidebar/90 to-primary/30">
      <Card className="w-full max-w-md shadow-xl border-0">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary">
            <Mic className="h-6 w-6 text-primary-foreground" />
          </div>
          <CardTitle className="text-2xl">HackGeniX</CardTitle>
          <CardDescription>
            AI-Powered Interview Platform
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="userId">User ID</Label>
            <Input
              id="userId"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="Enter user ID"
              onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="role">Role</Label>
            <Select value={role} onValueChange={(v) => setRole(v as Role)}>
              <SelectTrigger id="role">
                <SelectValue placeholder="Select role" />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => (
                  <SelectItem key={r.value} value={r.value}>
                    <div className="flex flex-col">
                      <span>{r.label}</span>
                      <span className="text-xs text-muted-foreground">
                        {r.description}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Role Permissions Preview */}
          <div className="rounded-lg border p-3 space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Shield className="h-4 w-4 text-muted-foreground" />
              <span>Permissions for {ROLES.find((r) => r.value === role)?.label}</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {selectedPermissions.map((perm) => (
                <Badge key={perm} variant="outline" className="text-xs">
                  {perm}
                </Badge>
              ))}
            </div>
          </div>

          <Button
            className="w-full"
            onClick={handleLogin}
            disabled={isLoading}
          >
            {isLoading ? 'Signing in...' : 'Sign In'}
          </Button>

          {/* Current Token Display (shown after login) */}
          {user?.token && (
            <Accordion type="single" collapsible className="w-full">
              <AccordionItem value="token" className="border rounded-lg">
                <AccordionTrigger className="px-3 py-2 text-sm hover:no-underline">
                  <div className="flex items-center gap-2">
                    <Key className="h-4 w-4 text-muted-foreground" />
                    <span className="text-muted-foreground">Current JWT Token</span>
                  </div>
                </AccordionTrigger>
                <AccordionContent className="px-3 pb-3">
                  <div className="space-y-2">
                    <code className="block rounded bg-muted p-2 text-xs break-all max-h-32 overflow-y-auto font-mono">
                      {user.token}
                    </code>
                    <Button variant="outline" size="sm" className="w-full" onClick={copyToken}>
                      <Copy className="mr-2 h-3 w-3" />
                      Copy Token
                    </Button>
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}

          <p className="text-center text-xs text-muted-foreground">
            Dev mode — tokens are generated locally with a shared secret
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
