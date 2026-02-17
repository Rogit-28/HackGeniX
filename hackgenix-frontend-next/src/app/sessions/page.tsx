'use client';

// ============================================================
// Sessions List — table with status filter, JSON inspector,
// load-by-ID, and action buttons
// ============================================================

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import { listSessions, getSession } from '@/lib/api';
import type { SessionSummary, SessionStatus } from '@/lib/types';
import {
  Loader2,
  RefreshCw,
  PlayCircle,
  FileText,
  Mic,
  Search,
  Eye,
  Copy,
  X,
} from 'lucide-react';
import { toast } from 'sonner';

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: 'all', label: 'All Statuses' },
  { value: 'created', label: 'Created' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'paused', label: 'Paused' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
];

function SessionsContent() {
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('all');

  // Load-by-ID
  const [lookupId, setLookupId] = useState('');
  const [lookupLoading, setLookupLoading] = useState(false);

  // JSON Inspector Dialog
  const [inspectData, setInspectData] = useState<unknown>(null);
  const [inspectSessionId, setInspectSessionId] = useState<string>('');
  const [inspectOpen, setInspectOpen] = useState(false);
  const [inspectLoading, setInspectLoading] = useState(false);

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

  const filteredSessions =
    statusFilter === 'all'
      ? sessions
      : sessions.filter((s) => s.status === statusFilter);

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

  // Inspect a session — fetch full detail and show JSON
  const handleInspect = async (sessionId: string) => {
    setInspectSessionId(sessionId);
    setInspectLoading(true);
    setInspectOpen(true);
    try {
      const detail = await getSession(sessionId);
      setInspectData(detail);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load session');
      setInspectData({ error: err instanceof Error ? err.message : 'Unknown error' });
    } finally {
      setInspectLoading(false);
    }
  };

  // Load session by ID
  const handleLookup = async () => {
    const id = lookupId.trim();
    if (!id) {
      toast.error('Enter a session ID');
      return;
    }
    setLookupLoading(true);
    try {
      const detail = await getSession(id);
      setInspectSessionId(id);
      setInspectData(detail);
      setInspectOpen(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Session not found');
    } finally {
      setLookupLoading(false);
    }
  };

  const copyJson = () => {
    if (inspectData) {
      navigator.clipboard.writeText(JSON.stringify(inspectData, null, 2));
      toast.success('Copied JSON to clipboard');
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Sessions</h1>
          <p className="text-muted-foreground">
            {statusFilter === 'all'
              ? `All interview sessions (${sessions.length})`
              : `${statusFilter.replace('_', ' ')} sessions (${filteredSessions.length} of ${sessions.length})`}
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

      {/* Toolbar: Status Filter + Load by ID */}
      <div className="flex flex-wrap items-end gap-4">
        {/* Status Filter */}
        <div className="space-y-1">
          <Label className="text-xs text-muted-foreground">Filter by status</Label>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Load by ID */}
        <div className="space-y-1 flex-1 min-w-[260px] max-w-md">
          <Label className="text-xs text-muted-foreground">Load session by ID</Label>
          <div className="flex gap-2">
            <Input
              value={lookupId}
              onChange={(e) => setLookupId(e.target.value)}
              placeholder="Paste session ID..."
              className="font-mono text-sm"
              onKeyDown={(e) => e.key === 'Enter' && handleLookup()}
            />
            <Button
              variant="outline"
              onClick={handleLookup}
              disabled={lookupLoading || !lookupId.trim()}
            >
              {lookupLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </div>

      {/* Sessions Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : filteredSessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <p className="text-muted-foreground mb-4">
                {sessions.length === 0
                  ? 'No sessions found'
                  : `No sessions with status "${statusFilter.replace('_', ' ')}"`}
              </p>
              {sessions.length === 0 && (
                <Button onClick={() => router.push('/setup')}>
                  Start your first interview
                </Button>
              )}
              {sessions.length > 0 && statusFilter !== 'all' && (
                <Button variant="outline" onClick={() => setStatusFilter('all')}>
                  Show all sessions
                </Button>
              )}
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
                {filteredSessions.map((session) => (
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
                        {/* Inspect button */}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleInspect(session.id)}
                          title="Inspect Session (JSON)"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
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

      {/* JSON Inspector Dialog */}
      <Dialog open={inspectOpen} onOpenChange={setInspectOpen}>
        <DialogContent className="max-w-3xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">
              Session: {inspectSessionId}
            </DialogTitle>
            <DialogDescription>
              Full session data from the backend API
            </DialogDescription>
          </DialogHeader>
          <div className="flex gap-2 mb-2">
            <Button variant="outline" size="sm" onClick={copyJson} disabled={!inspectData}>
              <Copy className="mr-2 h-3 w-3" />
              Copy JSON
            </Button>
            {(() => {
              if (!inspectData || typeof inspectData !== 'object') return null;
              const d = inspectData as Record<string, unknown>;
              if ('error' in d) return null;
              return (
                <>
                  {(d.status === 'in_progress' || d.status === 'paused' || d.status === 'created') && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setInspectOpen(false);
                        router.push(`/interview/${inspectSessionId}`);
                      }}
                    >
                      <FileText className="mr-2 h-3 w-3" />
                      Open in Interview
                    </Button>
                  )}
                  {d.status === 'completed' && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setInspectOpen(false);
                        router.push(`/reports/${inspectSessionId}`);
                      }}
                    >
                      <FileText className="mr-2 h-3 w-3" />
                      View Report
                    </Button>
                  )}
                </>
              );
            })()}
          </div>
          <div className="flex-1 overflow-auto rounded border bg-muted p-4">
            {inspectLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <pre className="text-xs whitespace-pre-wrap break-all font-mono">
                {JSON.stringify(inspectData, null, 2)}
              </pre>
            )}
          </div>
        </DialogContent>
      </Dialog>
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
