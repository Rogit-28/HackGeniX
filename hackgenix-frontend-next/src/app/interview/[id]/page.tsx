'use client';

// ============================================================
// Text Interview Page — question display, answer input,
// streaming evaluation, progress, timer
// ============================================================

import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Separator } from '@/components/ui/separator';
import { getSession, submitAnswer, endSession, pauseSession, resumeSession, synthesizeSpeech } from '@/lib/api';
import type { SessionDetail, Question, Evaluation, SSEEvent } from '@/lib/types';
import {
  Send,
  SkipForward,
  Square,
  Clock,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Mic,
  MicOff,
  ChevronRight,
  Pause,
  Play,
  Volume2,
} from 'lucide-react';
import { toast } from 'sonner';

function InterviewContent() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.id as string;

  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [answer, setAnswer] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [evalText, setEvalText] = useState('');
  const [lastEvaluation, setLastEvaluation] = useState<Evaluation | null>(null);
  const [timer, setTimer] = useState<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [questionStartTime, setQuestionStartTime] = useState<number>(0);

  // Pause / Resume
  const [paused, setPaused] = useState(false);
  const [pauseLoading, setPauseLoading] = useState(false);

  // TTS playback
  const [ttsPlaying, setTtsPlaying] = useState(false);
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);

  // Audio answer recording
  const [answerMode, setAnswerMode] = useState<'text' | 'audio'>('text');
  const [recording, setRecording] = useState(false);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  // Load session
  const loadSession = useCallback(async () => {
    try {
      const data = await getSession(sessionId);
      setSession(data);
      setPaused(data.status === 'paused');

      // Start timer for current question
      if (data.current_question?.duration_seconds) {
        setTimer(data.current_question.duration_seconds);
        setQuestionStartTime(Date.now());
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load session');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    loadSession();
  }, [loadSession]);

  // Timer countdown
  useEffect(() => {
    if (timer > 0 && questionStartTime > 0) {
      timerRef.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - questionStartTime) / 1000);
        const remaining = timer - elapsed;
        if (remaining <= 0) {
          if (timerRef.current) clearInterval(timerRef.current);
        }
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [timer, questionStartTime]);

  const getRemainingTime = () => {
    if (!timer || !questionStartTime) return null;
    const elapsed = Math.floor((Date.now() - questionStartTime) / 1000);
    return Math.max(0, timer - elapsed);
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  // Submit answer
  const handleSubmit = async () => {
    if (!answer.trim()) {
      toast.error('Please enter an answer');
      return;
    }

    setSubmitting(true);
    setEvalText('');
    setLastEvaluation(null);

    try {
      let newEval: Evaluation | null = null;
      for await (const event of submitAnswer(sessionId, answer.trim())) {
        try {
          const parsed = JSON.parse(event.data);

          // Accumulate streaming evaluation text
          if (parsed.token || parsed.text || parsed.chunk) {
            setEvalText(
              (prev) => prev + (parsed.token || parsed.text || parsed.chunk || '')
            );
          }

          // Capture structured evaluation
          if (parsed.evaluation) {
            newEval = parsed.evaluation;
            setLastEvaluation(parsed.evaluation);
          }
          if (parsed.score !== undefined) {
            newEval = parsed as unknown as Evaluation;
            setLastEvaluation(parsed as unknown as Evaluation);
          }
        } catch {
          setEvalText((prev) => prev + event.data);
        }
      }

      setAnswer('');
      toast.success('Answer submitted');

      // Reload session to get next question
      await loadSession();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Submit failed');
    } finally {
      setSubmitting(false);
    }
  };

  // Skip question
  const handleSkip = async () => {
    setSubmitting(true);
    try {
      // Submit with a skip indicator
      for await (const event of submitAnswer(sessionId, '[SKIPPED]')) {
        // consume stream
      }
      setAnswer('');
      setEvalText('');
      setLastEvaluation(null);
      await loadSession();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Skip failed');
    } finally {
      setSubmitting(false);
    }
  };

  // End interview
  const handleEnd = async () => {
    try {
      await endSession(sessionId);
      toast.success('Interview ended');
      router.push(`/reports/${sessionId}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'End failed');
    }
  };

  // Pause / Resume
  const handlePauseResume = async () => {
    setPauseLoading(true);
    try {
      if (paused) {
        await resumeSession(sessionId);
        setPaused(false);
        toast.success('Interview resumed');
      } else {
        await pauseSession(sessionId);
        setPaused(true);
        toast.success('Interview paused');
      }
      await loadSession();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Pause/resume failed');
    } finally {
      setPauseLoading(false);
    }
  };

  // TTS: read question aloud
  const handleTTS = async () => {
    if (!question?.text) return;
    if (ttsPlaying && ttsAudioRef.current) {
      ttsAudioRef.current.pause();
      ttsAudioRef.current.currentTime = 0;
      setTtsPlaying(false);
      return;
    }
    setTtsPlaying(true);
    try {
      const blob = await synthesizeSpeech(question.text);
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      ttsAudioRef.current = audio;
      audio.onended = () => {
        setTtsPlaying(false);
        URL.revokeObjectURL(url);
      };
      audio.onerror = () => {
        setTtsPlaying(false);
        URL.revokeObjectURL(url);
        toast.error('Audio playback failed');
      };
      audio.play();
    } catch (err) {
      setTtsPlaying(false);
      toast.error(err instanceof Error ? err.message : 'TTS failed');
    }
  };

  // Audio recording: start
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      audioChunksRef.current = [];
      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      mediaRecorder.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        setAudioBlob(blob);
        stream.getTracks().forEach((t) => t.stop());
      };
      mediaRecorderRef.current = mediaRecorder;
      mediaRecorder.start(250);
      setRecording(true);
      setAudioBlob(null);
    } catch (err) {
      toast.error('Microphone access denied');
    }
  };

  // Audio recording: stop
  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setRecording(false);
  };

  // Submit audio answer
  const handleAudioSubmit = async () => {
    if (!audioBlob) {
      toast.error('No audio recorded');
      return;
    }
    setSubmitting(true);
    setEvalText('');
    setLastEvaluation(null);

    try {
      // Convert blob to base64
      const buffer = await audioBlob.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      let binary = '';
      for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      const base64 = btoa(binary);

      let newEval: Evaluation | null = null;
      for await (const event of submitAnswer(sessionId, undefined, base64)) {
        try {
          const parsed = JSON.parse(event.data);
          if (parsed.token || parsed.text || parsed.chunk) {
            setEvalText((prev) => prev + (parsed.token || parsed.text || parsed.chunk || ''));
          }
          if (parsed.evaluation) {
            newEval = parsed.evaluation;
            setLastEvaluation(parsed.evaluation);
          }
          if (parsed.score !== undefined) {
            newEval = parsed as unknown as Evaluation;
            setLastEvaluation(parsed as unknown as Evaluation);
          }
        } catch {
          setEvalText((prev) => prev + event.data);
        }
      }

      setAudioBlob(null);
      toast.success('Audio answer submitted');
      await loadSession();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Submit failed');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!session) {
    return (
      <div className="flex h-96 items-center justify-center">
        <p className="text-muted-foreground">Session not found</p>
      </div>
    );
  }

  if (session.status === 'completed') {
    return (
      <div className="space-y-6">
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-12">
            <CheckCircle2 className="h-16 w-16 text-success" />
            <h2 className="text-2xl font-bold">Interview Complete</h2>
            <p className="text-muted-foreground">
              All questions have been answered
            </p>
            <div className="flex gap-3">
              <Button onClick={() => router.push(`/reports/${sessionId}`)}>
                View Report
              </Button>
              <Button variant="outline" onClick={() => router.push('/sessions')}>
                All Sessions
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const question = session.current_question;
  const progress = session.progress;
  const remaining = getRemainingTime();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Interview Session</h1>
          <p className="text-sm text-muted-foreground font-mono">
            {sessionId.slice(0, 16)}...
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handlePauseResume}
            disabled={pauseLoading}
          >
            {pauseLoading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : paused ? (
              <Play className="mr-2 h-4 w-4" />
            ) : (
              <Pause className="mr-2 h-4 w-4" />
            )}
            {paused ? 'Resume' : 'Pause'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => router.push(`/interview/${sessionId}/voice`)}
          >
            <Mic className="mr-2 h-4 w-4" />
            Switch to Voice
          </Button>
          <Badge variant={session.status === 'in_progress' ? 'default' : session.status === 'paused' ? 'outline' : 'secondary'}>
            {session.status.replace('_', ' ')}
          </Badge>
        </div>
      </div>

      {/* Progress */}
      {progress && (
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-muted-foreground">
                Question {progress.current_question_number} of {progress.total_questions}
              </span>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="capitalize">
                  {progress.current_stage?.replace('_', ' ')}
                </Badge>
                {remaining !== null && (
                  <span
                    className={`text-sm font-mono flex items-center gap-1 ${
                      remaining < 60 ? 'text-destructive' : 'text-muted-foreground'
                    }`}
                  >
                    <Clock className="h-3 w-3" />
                    {formatTime(remaining)}
                  </span>
                )}
              </div>
            </div>
            <Progress value={progress.percentage} />
          </CardContent>
        </Card>
      )}

      {/* Current Question */}
      {question && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CardTitle className="text-lg">
                  {question.is_follow_up ? 'Follow-up Question' : 'Question'}
                </CardTitle>
                {question.is_follow_up && (
                  <Badge variant="secondary">Follow-up</Badge>
                )}
                {question.sub_question_label && (
                  <Badge variant="outline">{question.sub_question_label}</Badge>
                )}
                {question.difficulty && (
                  <Badge variant="outline" className="capitalize">
                    {question.difficulty}
                  </Badge>
                )}
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleTTS}
                title={ttsPlaying ? 'Stop playback' : 'Read question aloud'}
              >
                {ttsPlaying ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Volume2 className="h-4 w-4" />
                )}
              </Button>
            </div>
            <Badge variant="outline" className="w-fit capitalize">
              {question.type?.replace('_', ' ')}
            </Badge>
          </CardHeader>
          <CardContent>
            <p className="text-base leading-relaxed whitespace-pre-wrap">
              {question.text}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Answer Input */}
      <Card>
        <CardContent className="py-4 space-y-3">
          {/* Mode Toggle */}
          <div className="flex gap-2">
            <Button
              variant={answerMode === 'text' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setAnswerMode('text')}
              disabled={submitting}
            >
              <Send className="mr-1.5 h-3.5 w-3.5" />
              Text
            </Button>
            <Button
              variant={answerMode === 'audio' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setAnswerMode('audio')}
              disabled={submitting}
            >
              <Mic className="mr-1.5 h-3.5 w-3.5" />
              Audio
            </Button>
          </div>

          {answerMode === 'text' ? (
            <>
              <Textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="Type your answer here..."
                rows={6}
                disabled={submitting || paused}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    handleSubmit();
                  }
                }}
              />
              <div className="flex gap-2">
                <Button
                  onClick={handleSubmit}
                  disabled={!answer.trim() || submitting || paused}
                  className="flex-1"
                >
                  {submitting ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="mr-2 h-4 w-4" />
                  )}
                  {submitting ? 'Evaluating...' : 'Submit Answer (Ctrl+Enter)'}
                </Button>
                <Button variant="outline" onClick={handleSkip} disabled={submitting || paused}>
                  <SkipForward className="mr-2 h-4 w-4" />
                  Skip
                </Button>
                <Button variant="destructive" onClick={handleEnd} disabled={submitting}>
                  <Square className="mr-2 h-4 w-4" />
                  End
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-col items-center gap-3 py-4">
                {recording ? (
                  <Button
                    variant="destructive"
                    size="lg"
                    onClick={stopRecording}
                    className="h-16 w-16 rounded-full"
                  >
                    <MicOff className="h-6 w-6" />
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="lg"
                    onClick={startRecording}
                    disabled={submitting || paused}
                    className="h-16 w-16 rounded-full"
                  >
                    <Mic className="h-6 w-6" />
                  </Button>
                )}
                <p className="text-sm text-muted-foreground">
                  {recording
                    ? 'Recording... click to stop'
                    : audioBlob
                    ? 'Audio recorded. Submit or re-record.'
                    : 'Click to start recording'}
                </p>
                {audioBlob && (
                  <audio
                    controls
                    src={URL.createObjectURL(audioBlob)}
                    className="w-full max-w-md"
                  />
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  onClick={handleAudioSubmit}
                  disabled={!audioBlob || submitting || paused}
                  className="flex-1"
                >
                  {submitting ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="mr-2 h-4 w-4" />
                  )}
                  {submitting ? 'Evaluating...' : 'Submit Audio Answer'}
                </Button>
                <Button variant="outline" onClick={handleSkip} disabled={submitting || paused}>
                  <SkipForward className="mr-2 h-4 w-4" />
                  Skip
                </Button>
                <Button variant="destructive" onClick={handleEnd} disabled={submitting}>
                  <Square className="mr-2 h-4 w-4" />
                  End
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Streaming Evaluation */}
      {evalText && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Evaluation</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap text-sm">{evalText}</pre>
          </CardContent>
        </Card>
      )}

      {/* Structured Evaluation */}
      {lastEvaluation && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg">Score</CardTitle>
              <Badge
                variant={
                  lastEvaluation.score >= 70
                    ? 'default'
                    : lastEvaluation.score >= 40
                    ? 'secondary'
                    : 'destructive'
                }
                className="text-lg px-3 py-1"
              >
                {lastEvaluation.score}/100
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {lastEvaluation.strengths?.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-success mb-1">Strengths</h4>
                <ul className="list-disc list-inside text-sm space-y-1">
                  {lastEvaluation.strengths.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {lastEvaluation.improvements?.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-warning mb-1">Areas for Improvement</h4>
                <ul className="list-disc list-inside text-sm space-y-1">
                  {lastEvaluation.improvements.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {lastEvaluation.recommendation && (
              <div>
                <h4 className="text-sm font-semibold mb-1">Recommendation</h4>
                <p className="text-sm capitalize">{lastEvaluation.recommendation}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Previous Answers */}
      {session.answers.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Previous Answers ({session.answers.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {session.answers
              .slice()
              .reverse()
              .slice(0, 5)
              .map((a, i) => (
                <div key={i} className="rounded-lg border p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground font-mono">
                      Q: {a.question_id.slice(0, 8)}
                    </span>
                    {a.evaluation && (
                      <Badge
                        variant={
                          a.evaluation.score >= 70
                            ? 'default'
                            : a.evaluation.score >= 40
                            ? 'secondary'
                            : 'destructive'
                        }
                      >
                        {a.evaluation.score}/100
                      </Badge>
                    )}
                  </div>
                  <p className="text-sm line-clamp-2">{a.answer_text}</p>
                </div>
              ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function InterviewPage() {
  return (
    <ProtectedRoute>
      <InterviewContent />
    </ProtectedRoute>
  );
}
