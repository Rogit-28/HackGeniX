'use client';

// ============================================================
// Admin Page — health check + token generator
// ============================================================

import { useState, useEffect } from 'react';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { useAuth } from '@/components/auth/AuthProvider';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { getHealth, getDetailedHealth, getBackendURL } from '@/lib/api';
import type { HealthStatus, Role } from '@/lib/types';
import {
  Activity,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Copy,
  Loader2,
  Server,
  Key,
} from 'lucide-react';
import { toast } from 'sonner';

function AdminContent() {
  const { user } = useAuth();
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [detailedHealth, setDetailedHealth] = useState<HealthStatus | null>(null);
  const [loadingHealth, setLoadingHealth] = useState(false);

  // Token generator
  const [tokenUserId, setTokenUserId] = useState('test-user');
  const [tokenRole, setTokenRole] = useState<Role>('hiring_manager');
  const [generatedToken, setGeneratedToken] = useState('');
  const [generatingToken, setGeneratingToken] = useState(false);

  const loadHealth = async () => {
    setLoadingHealth(true);
    try {
      const [h, dh] = await Promise.all([
        getHealth().catch(() => null),
        getDetailedHealth().catch(() => null),
      ]);
      setHealth(h);
      setDetailedHealth(dh);
    } catch {
      toast.error('Health check failed');
    } finally {
      setLoadingHealth(false);
    }
  };

  useEffect(() => {
    loadHealth();
  }, []);

  const handleGenerateToken = async () => {
    setGeneratingToken(true);
    try {
      const res = await fetch('/api/auth/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId: tokenUserId, role: tokenRole }),
      });
      const data = await res.json();
      if (data.token) {
        setGeneratedToken(data.token);
        toast.success('Token generated');
      } else {
        toast.error(data.error || 'Failed');
      }
    } catch {
      toast.error('Token generation failed');
    } finally {
      setGeneratingToken(false);
    }
  };

  const copyToken = () => {
    navigator.clipboard.writeText(generatedToken);
    toast.success('Copied to clipboard');
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Admin</h1>
        <p className="text-muted-foreground">
          System health and utilities
        </p>
      </div>

      {/* Backend Info */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Server className="h-5 w-5 text-muted-foreground" />
            <CardTitle>Backend</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex justify-between rounded-lg border p-3">
            <span className="text-sm text-muted-foreground">URL</span>
            <code className="text-sm">{getBackendURL()}</code>
          </div>
          <div className="flex justify-between rounded-lg border p-3">
            <span className="text-sm text-muted-foreground">Current User</span>
            <span className="text-sm">{user?.id} ({user?.role})</span>
          </div>
        </CardContent>
      </Card>

      {/* Health Check */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-muted-foreground" />
              <CardTitle>Health Check</CardTitle>
            </div>
            <Button variant="outline" size="sm" onClick={loadHealth} disabled={loadingHealth}>
              <RefreshCw className={`mr-2 h-4 w-4 ${loadingHealth ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Basic Health */}
          <div className="flex items-center justify-between rounded-lg border p-3">
            <span className="text-sm font-medium">Basic Health</span>
            {health ? (
              <Badge variant={health.status === 'healthy' ? 'default' : 'destructive'}>
                <CheckCircle2 className="mr-1 h-3 w-3" />
                {health.status}
              </Badge>
            ) : (
              <Badge variant="destructive">
                <XCircle className="mr-1 h-3 w-3" />
                Unreachable
              </Badge>
            )}
          </div>

          {/* Detailed Components */}
          {detailedHealth?.components && (
            <>
              <Separator />
              <h4 className="text-sm font-semibold">Components</h4>
              {Object.entries(detailedHealth.components).map(([name, comp]) => (
                <div
                  key={name}
                  className="flex items-center justify-between rounded-lg border p-3"
                >
                  <span className="text-sm capitalize">{name}</span>
                  <div className="flex items-center gap-2">
                    {comp.details && (
                      <span className="text-xs text-muted-foreground">
                        {comp.details}
                      </span>
                    )}
                    <Badge
                      variant={
                        comp.status === 'healthy' || comp.status === 'ok'
                          ? 'default'
                          : 'destructive'
                      }
                    >
                      {comp.status}
                    </Badge>
                  </div>
                </div>
              ))}
            </>
          )}
        </CardContent>
      </Card>

      {/* Token Generator */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Key className="h-5 w-5 text-muted-foreground" />
            <CardTitle>Token Generator</CardTitle>
          </div>
          <CardDescription>
            Generate JWT tokens for testing API endpoints
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>User ID</Label>
              <Input
                value={tokenUserId}
                onChange={(e) => setTokenUserId(e.target.value)}
                placeholder="user-id"
              />
            </div>
            <div className="space-y-2">
              <Label>Role</Label>
              <Select
                value={tokenRole}
                onValueChange={(v) => setTokenRole(v as Role)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="admin">Admin</SelectItem>
                  <SelectItem value="hiring_manager">Hiring Manager</SelectItem>
                  <SelectItem value="interviewer">Interviewer</SelectItem>
                  <SelectItem value="candidate">Candidate</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <Button onClick={handleGenerateToken} disabled={generatingToken}>
            {generatingToken ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Key className="mr-2 h-4 w-4" />
            )}
            Generate Token
          </Button>

          {generatedToken && (
            <div className="space-y-2">
              <Label>Generated Token</Label>
              <div className="flex gap-2">
                <code className="flex-1 rounded border bg-muted p-3 text-xs break-all max-h-24 overflow-y-auto">
                  {generatedToken}
                </code>
                <Button variant="outline" size="sm" onClick={copyToken}>
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function AdminPage() {
  return (
    <ProtectedRoute>
      <AdminContent />
    </ProtectedRoute>
  );
}
