'use client';

// ============================================================
// Report View — formatted report, scores, PDF download
// ============================================================

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Separator } from '@/components/ui/separator';
import { getReport, downloadReportPDF } from '@/lib/api';
import type { Report } from '@/lib/types';
import {
  Loader2,
  Download,
  ArrowLeft,
  CheckCircle2,
  AlertTriangle,
  TrendingUp,
  BarChart3,
} from 'lucide-react';
import { toast } from 'sonner';

function ReportContent() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.id as string;

  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await getReport(sessionId);
        setReport(data);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Failed to load report');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [sessionId]);

  const handleDownloadPDF = async () => {
    setDownloading(true);
    try {
      const blob = await downloadReportPDF(sessionId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `report-${sessionId.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success('PDF downloaded');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Download failed');
    } finally {
      setDownloading(false);
    }
  };

  const scoreColor = (score: number) => {
    if (score >= 70) return 'text-success';
    if (score >= 40) return 'text-warning';
    return 'text-destructive';
  };

  const scoreBadge = (score: number): 'default' | 'secondary' | 'destructive' => {
    if (score >= 70) return 'default';
    if (score >= 40) return 'secondary';
    return 'destructive';
  };

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!report) {
    return (
      <div className="flex h-96 flex-col items-center justify-center gap-4">
        <p className="text-muted-foreground">Report not found or not yet generated</p>
        <Button variant="outline" onClick={() => router.push('/sessions')}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Sessions
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Interview Report</h1>
          <p className="text-sm text-muted-foreground">
            {report.candidate_name && <span>{report.candidate_name} | </span>}
            {report.job_title && <span>{report.job_title} | </span>}
            <span className="font-mono">{sessionId.slice(0, 16)}...</span>
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => router.push('/sessions')}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Sessions
          </Button>
          <Button onClick={handleDownloadPDF} disabled={downloading}>
            {downloading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-2 h-4 w-4" />
            )}
            Download PDF
          </Button>
        </div>
      </div>

      {/* Overall Score */}
      <Card>
        <CardContent className="py-8">
          <div className="flex items-center justify-center gap-8">
            <div className="text-center">
              <p className="text-sm text-muted-foreground mb-2">Overall Score</p>
              <div
                className={`text-6xl font-bold ${scoreColor(report.overall_score)}`}
              >
                {report.overall_score}
              </div>
              <p className="text-sm text-muted-foreground mt-1">out of 100</p>
            </div>
            <Separator orientation="vertical" className="h-24" />
            <div className="text-center">
              <p className="text-sm text-muted-foreground mb-2">Questions</p>
              <div className="text-3xl font-bold">
                {report.total_answered}/{report.total_questions}
              </div>
              <p className="text-sm text-muted-foreground mt-1">answered</p>
            </div>
            <Separator orientation="vertical" className="h-24" />
            <div className="text-center">
              <p className="text-sm text-muted-foreground mb-2">Recommendation</p>
              <Badge
                variant={scoreBadge(report.overall_score)}
                className="text-lg px-4 py-1 capitalize"
              >
                {report.recommendation}
              </Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Stage Scores */}
      {report.stage_scores && Object.keys(report.stage_scores).length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5 text-muted-foreground" />
              <CardTitle>Stage Breakdown</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {Object.entries(report.stage_scores).map(([stage, score]) => (
              <div key={stage} className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium capitalize">
                    {stage.replace('_', ' ')}
                  </span>
                  <span className={`text-sm font-bold ${scoreColor(score)}`}>
                    {score}/100
                  </span>
                </div>
                <Progress value={score} className="h-2" />
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Strengths & Improvements */}
      <div className="grid gap-4 md:grid-cols-2">
        {report.strengths?.length > 0 && (
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-success" />
                <CardTitle>Strengths</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2">
                {report.strengths.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <TrendingUp className="h-4 w-4 text-success mt-0.5 shrink-0" />
                    {s}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {report.improvements?.length > 0 && (
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-warning" />
                <CardTitle>Areas for Improvement</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2">
                {report.improvements.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <AlertTriangle className="h-4 w-4 text-warning mt-0.5 shrink-0" />
                    {s}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Detailed Analysis */}
      {report.detailed_analysis && (
        <Card>
          <CardHeader>
            <CardTitle>Detailed Analysis</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed whitespace-pre-wrap">
              {report.detailed_analysis}
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function ReportPage() {
  return (
    <ProtectedRoute requiredPermission="view_reports">
      <ReportContent />
    </ProtectedRoute>
  );
}
