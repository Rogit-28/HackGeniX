'use client';

// ============================================================
// Setup Wizard — multi-step interview setup
// Step 1: Select/Upload Resume
// Step 2: Select/Upload Job Description
// Step 3: Configure Interview Settings
// Step 4: Review & Start
// ============================================================

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  listResumes,
  listJobDescriptions,
  uploadResumeStream,
  uploadJDStream,
  createJDStream,
  startSession,
  streamSSE,
} from '@/lib/api';
import type { Resume, JobDescription, InterviewConfig, SSEEvent } from '@/lib/types';
import {
  Upload,
  FileText,
  ChevronRight,
  ChevronLeft,
  Play,
  Check,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import { toast } from 'sonner';

const STEPS = [
  { label: 'Resume', description: 'Select or upload a resume' },
  { label: 'Job Description', description: 'Select or upload a job description' },
  { label: 'Configure', description: 'Interview settings' },
  { label: 'Start', description: 'Review and launch' },
];

function SetupContent() {
  const router = useRouter();
  const [step, setStep] = useState(0);

  // Step 1: Resume
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [selectedResumeId, setSelectedResumeId] = useState<string>('');
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [uploadingResume, setUploadingResume] = useState(false);
  const [resumeStreamText, setResumeStreamText] = useState('');

  // Step 2: JD
  const [jds, setJds] = useState<JobDescription[]>([]);
  const [selectedJDId, setSelectedJDId] = useState<string>('');
  const [jdFile, setJdFile] = useState<File | null>(null);
  const [jdText, setJdText] = useState('');
  const [jdTitle, setJdTitle] = useState('');
  const [uploadingJD, setUploadingJD] = useState(false);
  const [jdStreamText, setJdStreamText] = useState('');

  // Step 3: Config
  const [config, setConfig] = useState<InterviewConfig>({
    questions: {
      screening: 3,
      technical: 5,
      behavioral: 3,
      system_design: 1,
    },
    time_limits: {
      max_duration_seconds: 3600,
      question_timeout_seconds: 300,
    },
    adaptive: {
      adaptive_difficulty: true,
      enable_question_augmentation: true,
    },
    follow_ups: {
      enabled: true,
      max_per_question: 2,
      max_after_dont_know: 1,
      require_depth_increase: true,
      allow_different_angle_on_failure: true,
      trigger_rules: {
        poor_score_threshold: 40,
        standout_score_threshold: 70,
        hooks_trigger_alone: false,
      },
    },
  });

  // Step 4: Starting
  const [starting, setStarting] = useState(false);
  const [startStreamText, setStartStreamText] = useState('');

  // Load data
  const loadResumes = useCallback(async () => {
    try {
      const data = await listResumes();
      setResumes(data);
    } catch {
      // silently fail, list might be empty
    }
  }, []);

  const loadJDs = useCallback(async () => {
    try {
      const data = await listJobDescriptions();
      setJds(data);
    } catch {
      // silently fail
    }
  }, []);

  useEffect(() => {
    loadResumes();
    loadJDs();
  }, [loadResumes, loadJDs]);

  // Upload resume
  const handleUploadResume = async () => {
    if (!resumeFile) return;
    setUploadingResume(true);
    setResumeStreamText('');

    try {
      let lastData: Record<string, unknown> = {};
      for await (const event of uploadResumeStream(resumeFile)) {
        try {
          const parsed = JSON.parse(event.data);
          lastData = parsed;
          if (parsed.token || parsed.text || parsed.chunk) {
            setResumeStreamText((prev) => prev + (parsed.token || parsed.text || parsed.chunk || ''));
          }
          if (parsed.status) {
            setResumeStreamText((prev) => prev + `\n[${parsed.status}] `);
          }
        } catch {
          setResumeStreamText((prev) => prev + event.data);
        }
      }

      // Extract resume_id from the last event
      const resumeId = (lastData.resume_id || lastData.id || '') as string;
      if (resumeId) {
        setSelectedResumeId(resumeId);
        toast.success('Resume uploaded successfully');
        await loadResumes();
      } else {
        toast.success('Resume processed');
        await loadResumes();
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploadingResume(false);
      setResumeFile(null);
    }
  };

  // Upload JD
  const handleUploadJD = async () => {
    setUploadingJD(true);
    setJdStreamText('');

    try {
      let lastData: Record<string, unknown> = {};
      const stream = jdFile
        ? uploadJDStream(jdFile)
        : createJDStream(jdText, jdTitle || undefined);

      for await (const event of stream) {
        try {
          const parsed = JSON.parse(event.data);
          lastData = parsed;
          if (parsed.token || parsed.text || parsed.chunk) {
            setJdStreamText((prev) => prev + (parsed.token || parsed.text || parsed.chunk || ''));
          }
          if (parsed.status) {
            setJdStreamText((prev) => prev + `\n[${parsed.status}] `);
          }
        } catch {
          setJdStreamText((prev) => prev + event.data);
        }
      }

      const jdId = (lastData.job_description_id || lastData.id || '') as string;
      if (jdId) {
        setSelectedJDId(jdId);
        toast.success('Job description created successfully');
        await loadJDs();
      } else {
        toast.success('Job description processed');
        await loadJDs();
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploadingJD(false);
      setJdFile(null);
      setJdText('');
    }
  };

  // Start interview
  const handleStart = async () => {
    if (!selectedResumeId || !selectedJDId) {
      toast.error('Please select both a resume and a job description');
      return;
    }

    setStarting(true);
    setStartStreamText('');

    try {
      let sessionId = '';
      for await (const event of startSession(selectedResumeId, selectedJDId, config)) {
        try {
          const parsed = JSON.parse(event.data);
          if (parsed.session_id || parsed.id) {
            sessionId = (parsed.session_id || parsed.id) as string;
          }
          if (parsed.token || parsed.text || parsed.chunk) {
            setStartStreamText((prev) => prev + (parsed.token || parsed.text || parsed.chunk || ''));
          }
          if (parsed.status) {
            setStartStreamText((prev) => prev + `\n[${parsed.status}] `);
          }
        } catch {
          setStartStreamText((prev) => prev + event.data);
        }
      }

      if (sessionId) {
        toast.success('Interview session started!');
        router.push(`/interview/${sessionId}`);
      } else {
        toast.error('Session started but no session ID received');
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to start session');
    } finally {
      setStarting(false);
    }
  };

  const canProceed = () => {
    switch (step) {
      case 0:
        return !!selectedResumeId;
      case 1:
        return !!selectedJDId;
      case 2:
        return true;
      case 3:
        return !!selectedResumeId && !!selectedJDId;
      default:
        return false;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold">Setup Interview</h1>
        <p className="text-muted-foreground">
          Configure and start a new interview session
        </p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2">
        {STEPS.map((s, i) => (
          <div key={i} className="flex items-center gap-2">
            <button
              onClick={() => i < step && setStep(i)}
              className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors ${
                i === step
                  ? 'bg-primary text-primary-foreground'
                  : i < step
                  ? 'bg-success/15 text-success cursor-pointer hover:bg-success/25'
                  : 'bg-muted text-muted-foreground'
              }`}
            >
              {i < step ? (
                <Check className="h-4 w-4" />
              ) : (
                <span className="flex h-5 w-5 items-center justify-center rounded-full border text-xs">
                  {i + 1}
                </span>
              )}
              {s.label}
            </button>
            {i < STEPS.length - 1 && (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
          </div>
        ))}
      </div>

      {/* Step Content */}
      {step === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Select Resume</CardTitle>
            <CardDescription>
              Choose an existing resume or upload a new one
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Tabs defaultValue="select">
              <TabsList>
                <TabsTrigger value="select">Select Existing</TabsTrigger>
                <TabsTrigger value="upload">Upload New</TabsTrigger>
              </TabsList>

              <TabsContent value="select" className="space-y-3">
                {resumes.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4">
                    No resumes found. Upload one first.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {resumes.map((r) => (
                      <div
                        key={r.id}
                        onClick={() => setSelectedResumeId(r.id)}
                        className={`flex items-center justify-between rounded-lg border p-3 cursor-pointer transition-colors ${
                          selectedResumeId === r.id
                            ? 'border-primary bg-primary/5'
                            : 'hover:bg-accent'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <FileText className="h-4 w-4 text-muted-foreground" />
                          <div>
                            <p className="text-sm font-medium">
                              {r.candidate_name || r.filename || r.id.slice(0, 12)}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {r.filename} {r.experience_years ? `| ${r.experience_years}y exp` : ''}
                            </p>
                          </div>
                        </div>
                        {selectedResumeId === r.id && (
                          <Check className="h-4 w-4 text-primary" />
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="upload" className="space-y-3">
                <div className="space-y-2">
                  <Label>Resume File (PDF, DOCX, TXT)</Label>
                  <Input
                    type="file"
                    accept=".pdf,.docx,.txt,.doc"
                    onChange={(e) => setResumeFile(e.target.files?.[0] || null)}
                  />
                </div>
                <Button
                  onClick={handleUploadResume}
                  disabled={!resumeFile || uploadingResume}
                >
                  {uploadingResume ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="mr-2 h-4 w-4" />
                  )}
                  {uploadingResume ? 'Processing...' : 'Upload & Process'}
                </Button>
                {resumeStreamText && (
                  <pre className="mt-2 max-h-40 overflow-y-auto rounded bg-muted p-3 text-xs whitespace-pre-wrap">
                    {resumeStreamText}
                  </pre>
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      )}

      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Select Job Description</CardTitle>
            <CardDescription>
              Choose an existing JD, upload a file, or paste text
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Tabs defaultValue="select">
              <TabsList>
                <TabsTrigger value="select">Select Existing</TabsTrigger>
                <TabsTrigger value="upload">Upload File</TabsTrigger>
                <TabsTrigger value="paste">Paste Text</TabsTrigger>
              </TabsList>

              <TabsContent value="select" className="space-y-3">
                {jds.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4">
                    No job descriptions found. Create one first.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {jds.map((jd) => (
                      <div
                        key={jd.id}
                        onClick={() => setSelectedJDId(jd.id)}
                        className={`flex items-center justify-between rounded-lg border p-3 cursor-pointer transition-colors ${
                          selectedJDId === jd.id
                            ? 'border-primary bg-primary/5'
                            : 'hover:bg-accent'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <FileText className="h-4 w-4 text-muted-foreground" />
                          <div>
                            <p className="text-sm font-medium">
                              {jd.title || jd.id.slice(0, 12)}
                            </p>
                            {jd.company && (
                              <p className="text-xs text-muted-foreground">
                                {jd.company}
                              </p>
                            )}
                          </div>
                        </div>
                        {selectedJDId === jd.id && (
                          <Check className="h-4 w-4 text-primary" />
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="upload" className="space-y-3">
                <div className="space-y-2">
                  <Label>JD File (PDF, DOCX, TXT)</Label>
                  <Input
                    type="file"
                    accept=".pdf,.docx,.txt,.doc"
                    onChange={(e) => setJdFile(e.target.files?.[0] || null)}
                  />
                </div>
                <Button
                  onClick={handleUploadJD}
                  disabled={!jdFile || uploadingJD}
                >
                  {uploadingJD ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="mr-2 h-4 w-4" />
                  )}
                  {uploadingJD ? 'Processing...' : 'Upload & Process'}
                </Button>
              </TabsContent>

              <TabsContent value="paste" className="space-y-3">
                <div className="space-y-2">
                  <Label>Title (optional)</Label>
                  <Input
                    value={jdTitle}
                    onChange={(e) => setJdTitle(e.target.value)}
                    placeholder="e.g., Senior Software Engineer"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Job Description Text</Label>
                  <Textarea
                    value={jdText}
                    onChange={(e) => setJdText(e.target.value)}
                    placeholder="Paste the full job description here..."
                    rows={8}
                  />
                </div>
                <Button
                  onClick={handleUploadJD}
                  disabled={!jdText.trim() || uploadingJD}
                >
                  {uploadingJD ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <FileText className="mr-2 h-4 w-4" />
                  )}
                  {uploadingJD ? 'Processing...' : 'Create JD'}
                </Button>
              </TabsContent>
            </Tabs>

            {jdStreamText && (
              <pre className="mt-2 max-h-40 overflow-y-auto rounded bg-muted p-3 text-xs whitespace-pre-wrap">
                {jdStreamText}
              </pre>
            )}
          </CardContent>
        </Card>
      )}

      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle>Interview Configuration</CardTitle>
            <CardDescription>
              Customize question counts, timing, and pipeline settings
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Question Counts */}
            <div>
              <h3 className="text-sm font-semibold mb-3">Question Counts</h3>
              <div className="grid grid-cols-2 gap-4">
                {(['screening', 'technical', 'behavioral', 'system_design'] as const).map((stage) => (
                  <div key={stage} className="space-y-1">
                    <Label className="capitalize">{stage.replace('_', ' ')}</Label>
                    <Input
                      type="number"
                      min={0}
                      max={20}
                      value={config.questions?.[stage] ?? 0}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          questions: {
                            ...prev.questions,
                            [stage]: parseInt(e.target.value) || 0,
                          },
                        }))
                      }
                    />
                  </div>
                ))}
              </div>
            </div>

            <Separator />

            {/* Time Limits */}
            <div>
              <h3 className="text-sm font-semibold mb-3">Time Limits</h3>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label>Max Duration (seconds)</Label>
                  <Input
                    type="number"
                    min={300}
                    max={7200}
                    step={300}
                    value={config.time_limits?.max_duration_seconds ?? 3600}
                    onChange={(e) =>
                      setConfig((prev) => ({
                        ...prev,
                        time_limits: {
                          ...prev.time_limits,
                          max_duration_seconds: parseInt(e.target.value) || 3600,
                        },
                      }))
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label>Question Timeout (seconds)</Label>
                  <Input
                    type="number"
                    min={30}
                    max={600}
                    step={30}
                    value={config.time_limits?.question_timeout_seconds ?? 300}
                    onChange={(e) =>
                      setConfig((prev) => ({
                        ...prev,
                        time_limits: {
                          ...prev.time_limits,
                          question_timeout_seconds: parseInt(e.target.value) || 300,
                        },
                      }))
                    }
                  />
                </div>
              </div>
            </div>

            <Separator />

            {/* Adaptive Settings */}
            <div>
              <h3 className="text-sm font-semibold mb-3">Adaptive Settings</h3>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <Label>Adaptive Difficulty</Label>
                    <p className="text-xs text-muted-foreground">
                      Adjust question difficulty based on performance
                    </p>
                  </div>
                  <Switch
                    checked={config.adaptive?.adaptive_difficulty ?? true}
                    onCheckedChange={(checked) =>
                      setConfig((prev) => ({
                        ...prev,
                        adaptive: { ...prev.adaptive, adaptive_difficulty: checked },
                      }))
                    }
                  />
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <Label>Question Augmentation</Label>
                    <p className="text-xs text-muted-foreground">
                      Dynamically adapt questions based on prior answers
                    </p>
                  </div>
                  <Switch
                    checked={config.adaptive?.enable_question_augmentation ?? true}
                    onCheckedChange={(checked) =>
                      setConfig((prev) => ({
                        ...prev,
                        adaptive: { ...prev.adaptive, enable_question_augmentation: checked },
                      }))
                    }
                  />
                </div>
              </div>
            </div>

            <Separator />

            {/* Follow-ups */}
            <div>
              <h3 className="text-sm font-semibold mb-3">Follow-up Questions</h3>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label>Enable Follow-ups</Label>
                  <Switch
                    checked={config.follow_ups?.enabled ?? true}
                    onCheckedChange={(checked) =>
                      setConfig((prev) => ({
                        ...prev,
                        follow_ups: { ...prev.follow_ups, enabled: checked },
                      }))
                    }
                  />
                </div>
                {config.follow_ups?.enabled && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-1">
                        <Label>Max Per Question</Label>
                        <Input
                          type="number"
                          min={0}
                          max={5}
                          value={config.follow_ups?.max_per_question ?? 2}
                          onChange={(e) =>
                            setConfig((prev) => ({
                              ...prev,
                              follow_ups: {
                                ...prev.follow_ups,
                                max_per_question: parseInt(e.target.value) || 2,
                              },
                            }))
                          }
                        />
                      </div>
                      <div className="space-y-1">
                        <Label>Max After &quot;Don&apos;t Know&quot;</Label>
                        <Input
                          type="number"
                          min={0}
                          max={3}
                          value={config.follow_ups?.max_after_dont_know ?? 1}
                          onChange={(e) =>
                            setConfig((prev) => ({
                              ...prev,
                              follow_ups: {
                                ...prev.follow_ups,
                                max_after_dont_know: parseInt(e.target.value) || 1,
                              },
                            }))
                          }
                        />
                      </div>
                      <div className="space-y-1">
                        <Label>Poor Score Threshold</Label>
                        <Input
                          type="number"
                          min={0}
                          max={100}
                          value={config.follow_ups?.trigger_rules?.poor_score_threshold ?? 40}
                          onChange={(e) =>
                            setConfig((prev) => ({
                              ...prev,
                              follow_ups: {
                                ...prev.follow_ups,
                                trigger_rules: {
                                  ...prev.follow_ups?.trigger_rules,
                                  poor_score_threshold: parseInt(e.target.value) || 40,
                                },
                              },
                            }))
                          }
                        />
                      </div>
                      <div className="space-y-1">
                        <Label>Standout Score Threshold</Label>
                        <Input
                          type="number"
                          min={0}
                          max={100}
                          value={config.follow_ups?.trigger_rules?.standout_score_threshold ?? 70}
                          onChange={(e) =>
                            setConfig((prev) => ({
                              ...prev,
                              follow_ups: {
                                ...prev.follow_ups,
                                trigger_rules: {
                                  ...prev.follow_ups?.trigger_rules,
                                  standout_score_threshold: parseInt(e.target.value) || 70,
                                },
                              },
                            }))
                          }
                        />
                      </div>
                    </div>

                    <Separator />

                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <div>
                          <Label>Require Depth Increase</Label>
                          <p className="text-xs text-muted-foreground">
                            Follow-ups must go deeper than the original question
                          </p>
                        </div>
                        <Switch
                          checked={config.follow_ups?.require_depth_increase ?? true}
                          onCheckedChange={(checked) =>
                            setConfig((prev) => ({
                              ...prev,
                              follow_ups: {
                                ...prev.follow_ups,
                                require_depth_increase: checked,
                              },
                            }))
                          }
                        />
                      </div>
                      <div className="flex items-center justify-between">
                        <div>
                          <Label>Different Angle on Failure</Label>
                          <p className="text-xs text-muted-foreground">
                            Try a different approach when candidate struggles
                          </p>
                        </div>
                        <Switch
                          checked={config.follow_ups?.allow_different_angle_on_failure ?? true}
                          onCheckedChange={(checked) =>
                            setConfig((prev) => ({
                              ...prev,
                              follow_ups: {
                                ...prev.follow_ups,
                                allow_different_angle_on_failure: checked,
                              },
                            }))
                          }
                        />
                      </div>
                      <div className="flex items-center justify-between">
                        <div>
                          <Label>Hooks Trigger Alone</Label>
                          <p className="text-xs text-muted-foreground">
                            Allow hooks to trigger follow-ups without score thresholds
                          </p>
                        </div>
                        <Switch
                          checked={config.follow_ups?.trigger_rules?.hooks_trigger_alone ?? false}
                          onCheckedChange={(checked) =>
                            setConfig((prev) => ({
                              ...prev,
                              follow_ups: {
                                ...prev.follow_ups,
                                trigger_rules: {
                                  ...prev.follow_ups?.trigger_rules,
                                  hooks_trigger_alone: checked,
                                },
                              },
                            }))
                          }
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 3 && (
        <Card>
          <CardHeader>
            <CardTitle>Review & Start</CardTitle>
            <CardDescription>
              Confirm your setup before launching the interview
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3">
              <div className="flex justify-between rounded-lg border p-3">
                <span className="text-sm text-muted-foreground">Resume</span>
                <span className="text-sm font-medium font-mono">
                  {selectedResumeId ? selectedResumeId.slice(0, 16) + '...' : 'None'}
                </span>
              </div>
              <div className="flex justify-between rounded-lg border p-3">
                <span className="text-sm text-muted-foreground">Job Description</span>
                <span className="text-sm font-medium font-mono">
                  {selectedJDId ? selectedJDId.slice(0, 16) + '...' : 'None'}
                </span>
              </div>
              <div className="flex justify-between rounded-lg border p-3">
                <span className="text-sm text-muted-foreground">Total Questions</span>
                <span className="text-sm font-medium">
                  {Object.values(config.questions || {}).reduce((a, b) => a + (b || 0), 0)}
                </span>
              </div>
              <div className="flex justify-between rounded-lg border p-3">
                <span className="text-sm text-muted-foreground">Adaptive</span>
                <Badge variant={config.adaptive?.adaptive_difficulty ? 'default' : 'secondary'}>
                  {config.adaptive?.adaptive_difficulty ? 'On' : 'Off'}
                </Badge>
              </div>
              <div className="flex justify-between rounded-lg border p-3">
                <span className="text-sm text-muted-foreground">Follow-ups</span>
                <Badge variant={config.follow_ups?.enabled ? 'default' : 'secondary'}>
                  {config.follow_ups?.enabled ? 'On' : 'Off'}
                </Badge>
              </div>
              <div className="flex justify-between rounded-lg border p-3">
                <span className="text-sm text-muted-foreground">Augmentation</span>
                <Badge variant={config.adaptive?.enable_question_augmentation ? 'default' : 'secondary'}>
                  {config.adaptive?.enable_question_augmentation ? 'On' : 'Off'}
                </Badge>
              </div>
            </div>

            {startStreamText && (
              <pre className="max-h-40 overflow-y-auto rounded bg-muted p-3 text-xs whitespace-pre-wrap">
                {startStreamText}
              </pre>
            )}

            <div className="flex gap-3">
              <Button
                className="flex-1"
                onClick={handleStart}
                disabled={starting || !selectedResumeId || !selectedJDId}
              >
                {starting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Play className="mr-2 h-4 w-4" />
                )}
                {starting ? 'Starting Interview...' : 'Start Text Interview'}
              </Button>
              <Button
                variant="outline"
                className="flex-1"
                onClick={async () => {
                  // Start session then navigate to voice
                  if (!selectedResumeId || !selectedJDId) {
                    toast.error('Please select both resume and JD');
                    return;
                  }
                  setStarting(true);
                  try {
                    let sessionId = '';
                    for await (const event of startSession(selectedResumeId, selectedJDId, config)) {
                      try {
                        const parsed = JSON.parse(event.data);
                        if (parsed.session_id || parsed.id) {
                          sessionId = (parsed.session_id || parsed.id) as string;
                        }
                      } catch {
                        // ignore
                      }
                    }
                    if (sessionId) {
                      toast.success('Session created! Launching voice interview...');
                      router.push(`/interview/${sessionId}/voice`);
                    }
                  } catch (err) {
                    toast.error(err instanceof Error ? err.message : 'Failed');
                  } finally {
                    setStarting(false);
                  }
                }}
                disabled={starting || !selectedResumeId || !selectedJDId}
              >
                {starting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Play className="mr-2 h-4 w-4" />
                )}
                Start Voice Interview
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Navigation */}
      <div className="flex justify-between">
        <Button
          variant="outline"
          onClick={() => setStep(step - 1)}
          disabled={step === 0}
        >
          <ChevronLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
        {step < STEPS.length - 1 && (
          <Button
            onClick={() => setStep(step + 1)}
            disabled={!canProceed()}
          >
            Next
            <ChevronRight className="ml-2 h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  );
}

export default function SetupPage() {
  return (
    <ProtectedRoute requiredPermission="create_session">
      <SetupContent />
    </ProtectedRoute>
  );
}
