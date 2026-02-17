'use client';

// ============================================================
// Dashboard — landing page with quick actions and stats
// ============================================================

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { useAuth } from '@/components/auth/AuthProvider';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { listSessions, getHealth } from '@/lib/api';
import type { SessionSummary, HealthStatus } from '@/lib/types';
import { PlayCircle, List, FileText, Activity, CheckCircle2, Clock, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';

function DashboardContent() {
  const { user } = useAuth();
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [sessionsData, healthData] = await Promise.all([
          listSessions().catch(() => []),
          getHealth().catch(() => null),
        ]);
        setSessions(sessionsData);
        setHealth(healthData);
      } catch (err) {
        toast.error('Failed to load dashboard data');
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const activeSessions = sessions.filter(
    (s) => s.status === 'in_progress' || s.status === 'paused'
  );
  const completedSessions = sessions.filter((s) => s.status === 'completed');

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold">
          Welcome back, {user?.id}
        </h1>
        <p className="text-muted-foreground">
          {health?.status === 'healthy' ? (
            <span className="inline-flex items-center gap-1">
              <CheckCircle2 className="h-4 w-4 text-success" />
              Backend connected
            </span>
          ) : (
            <span className="inline-flex items-center gap-1">
              <AlertCircle className="h-4 w-4 text-destructive" />
              Backend unreachable
            </span>
          )}
        </p>
      </div>

      {/* Quick Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="transition-shadow hover:shadow-md">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Active Sessions</CardTitle>
            <Clock className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {loading ? '...' : activeSessions.length}
            </div>
          </CardContent>
        </Card>
        <Card className="transition-shadow hover:shadow-md">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Completed</CardTitle>
            <CheckCircle2 className="h-4 w-4 text-success" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {loading ? '...' : completedSessions.length}
            </div>
          </CardContent>
        </Card>
        <Card className="transition-shadow hover:shadow-md">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Total Sessions</CardTitle>
            <Activity className="h-4 w-4 text-info" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {loading ? '...' : sessions.length}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
          <CardDescription>Get started with common tasks</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Button onClick={() => router.push('/setup')}>
            <PlayCircle className="mr-2 h-4 w-4" />
            New Interview
          </Button>
          <Button variant="outline" onClick={() => router.push('/sessions')}>
            <List className="mr-2 h-4 w-4" />
            View Sessions
          </Button>
          <Button variant="outline" onClick={() => router.push('/reports')}>
            <FileText className="mr-2 h-4 w-4" />
            View Reports
          </Button>
        </CardContent>
      </Card>

      {/* Recent Active Sessions */}
      {activeSessions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Active Sessions</CardTitle>
            <CardDescription>Sessions currently in progress</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {activeSessions.slice(0, 5).map((session) => (
                <div
                  key={session.id}
                  className="flex items-center justify-between rounded-lg border p-3 cursor-pointer hover:bg-accent transition-colors"
                  onClick={() => router.push(`/interview/${session.id}`)}
                >
                  <div className="flex items-center gap-3">
                    <Badge
                      variant={session.status === 'in_progress' ? 'default' : 'secondary'}
                    >
                      {session.status.replace('_', ' ')}
                    </Badge>
                    <span className="text-sm font-mono">{session.id.slice(0, 8)}...</span>
                    {session.current_stage && (
                      <span className="text-xs text-muted-foreground">
                        Stage: {session.current_stage}
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {session.answered_questions ?? 0}/{session.total_questions ?? '?'} questions
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <ProtectedRoute>
      <DashboardContent />
    </ProtectedRoute>
  );
}
