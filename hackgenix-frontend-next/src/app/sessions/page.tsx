'use client';

// ============================================================
// Sessions List — table with status badges, click to open
// ============================================================

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { listSessions } from '@/lib/api';
import type { SessionSummary } from '@/lib/types';
import { Loader2, RefreshCw, PlayCircle, FileText, Mic } from 'lucide-react';
import { toast } from 'sonner';

function SessionsContent() {
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const loadSessions = async () => {
    setLoading(true);
    try {
      const data = await listSessions();
      setSessions(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSessions();
  }, []);

  const statusVariant = (
    status: string
  ): 'default' | 'secondary' | 'destructive' | 'outline' => {
    switch (status) {
      case 'in_progress':
        return 'default';
      case 'completed':
        return 'secondary';
      case 'paused':
        return 'outline';
      case 'cancelled':
        return 'destructive';
      default:
        return 'outline';
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Sessions</h1>
          <p className="text-muted-foreground">
            All interview sessions ({sessions.length})
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={loadSessions} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button onClick={() => router.push('/setup')}>
            <PlayCircle className="mr-2 h-4 w-4" />
            New Interview
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <p className="text-muted-foreground mb-4">No sessions found</p>
              <Button onClick={() => router.push('/setup')}>
                Start your first interview
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Session ID</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Stage</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((session) => (
                  <TableRow
                    key={session.id}
                    className="cursor-pointer"
                    onClick={() => {
                      if (session.status === 'completed') {
                        router.push(`/reports/${session.id}`);
                      } else {
                        router.push(`/interview/${session.id}`);
                      }
                    }}
                  >
                    <TableCell className="font-mono text-sm">
                      {session.id.slice(0, 12)}...
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(session.status)}>
                        {session.status.replace('_', ' ')}
                      </Badge>
                    </TableCell>
                    <TableCell className="capitalize">
                      {session.current_stage?.replace('_', ' ') || '-'}
                    </TableCell>
                    <TableCell>
                      {session.answered_questions !== undefined
                        ? `${session.answered_questions}/${session.total_questions ?? '?'}`
                        : '-'}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(session.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                        {(session.status === 'in_progress' || session.status === 'paused' || session.status === 'created') && (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => router.push(`/interview/${session.id}`)}
                              title="Text Interview"
                            >
                              <FileText className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => router.push(`/interview/${session.id}/voice`)}
                              title="Voice Interview"
                            >
                              <Mic className="h-4 w-4" />
                            </Button>
                          </>
                        )}
                        {session.status === 'completed' && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => router.push(`/reports/${session.id}`)}
                            title="View Report"
                          >
                            <FileText className="h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function SessionsPage() {
  return (
    <ProtectedRoute requiredPermission="view_session">
      <SessionsContent />
    </ProtectedRoute>
  );
}
