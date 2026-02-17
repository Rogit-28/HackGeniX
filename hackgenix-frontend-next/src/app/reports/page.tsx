'use client';

// ============================================================
// Reports List — shows all completed sessions with reports
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
import { Loader2, RefreshCw, FileText } from 'lucide-react';
import { toast } from 'sonner';

function ReportsListContent() {
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const loadSessions = async () => {
    setLoading(true);
    try {
      const data = await listSessions();
      // Only show completed sessions (they have reports)
      setSessions(data.filter((s) => s.status === 'completed'));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSessions();
  }, []);

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
          <h1 className="text-3xl font-bold">Reports</h1>
          <p className="text-muted-foreground">
            Completed interview reports ({sessions.length})
          </p>
        </div>
        <Button variant="outline" onClick={loadSessions} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <p className="text-muted-foreground mb-4">
                No completed interviews yet
              </p>
              <Button onClick={() => router.push('/setup')}>
                Start an interview
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Session ID</TableHead>
                  <TableHead>Questions</TableHead>
                  <TableHead>Completed</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((session) => (
                  <TableRow
                    key={session.id}
                    className="cursor-pointer"
                    onClick={() => router.push(`/reports/${session.id}`)}
                  >
                    <TableCell className="font-mono text-sm">
                      {session.id.slice(0, 12)}...
                    </TableCell>
                    <TableCell>
                      {session.answered_questions ?? '-'}/{session.total_questions ?? '-'}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {session.updated_at ? formatDate(session.updated_at) : formatDate(session.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          router.push(`/reports/${session.id}`);
                        }}
                      >
                        <FileText className="mr-2 h-4 w-4" />
                        View
                      </Button>
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

export default function ReportsListPage() {
  return (
    <ProtectedRoute requiredPermission="view_reports">
      <ReportsListContent />
    </ProtectedRoute>
  );
}
