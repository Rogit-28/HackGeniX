'use client';

// ============================================================
// Voice Interview Page — WebSocket, MediaRecorder, TTS playback,
// audio visualizer, state machine
// ============================================================

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { getWebSocketURL } from '@/lib/api';
import { VoiceWSClient, type WSState } from '@/lib/ws';
import type { WSMessage, Question, Evaluation } from '@/lib/types';
import {
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  SkipForward,
  Square,
  Clock,
  Loader2,
  Volume2,
  Send,
  Keyboard,
  CheckCircle2,
} from 'lucide-react';
import { toast } from 'sonner';

function VoiceInterviewContent() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.id as string;

  // State
  const [wsState, setWsState] = useState<WSState>('disconnected');
  const [currentQuestion, setCurrentQuestion] = useState<Question | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [transcript, setTranscript] = useState('');
  const [progress, setProgress] = useState({ current: 0, total: 0, stage: '' });
  const [timer, setTimer] = useState<number>(0);
  const [timerMax, setTimerMax] = useState<number>(0);
  const [isRecording, setIsRecording] = useState(false);
  const [showTextFallback, setShowTextFallback] = useState(false);
  const [textAnswer, setTextAnswer] = useState('');
  const [log, setLog] = useState<string[]>([]);
  const [showLog, setShowLog] = useState(false);

  // Refs
  const wsClientRef = useRef<VoiceWSClient | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioQueueRef = useRef<ArrayBuffer[]>([]);
  const isPlayingRef = useRef(false);
  const timerIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number>(0);

  const addLog = useCallback((msg: string) => {
    const ts = new Date().toLocaleTimeString();
    setLog((prev) => [...prev.slice(-100), `[${ts}] ${msg}`]);
  }, []);

  // --- Audio Playback Queue ---
  const playNextAudio = useCallback(async () => {
    if (isPlayingRef.current || audioQueueRef.current.length === 0) return;
    isPlayingRef.current = true;

    const buffer = audioQueueRef.current.shift()!;
    try {
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext();
      }
      const ctx = audioContextRef.current;
      const audioBuffer = await ctx.decodeAudioData(buffer.slice(0));
      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);
      source.onended = () => {
        isPlayingRef.current = false;
        playNextAudio();
      };
      source.start();
    } catch (err) {
      addLog(`Audio playback error: ${err}`);
      isPlayingRef.current = false;
      playNextAudio();
    }
  }, [addLog]);

  const queueAudio = useCallback(
    (data: ArrayBuffer) => {
      audioQueueRef.current.push(data);
      playNextAudio();
    },
    [playNextAudio]
  );

  // --- Timer ---
  const startTimer = useCallback((seconds: number) => {
    if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
    setTimerMax(seconds);
    setTimer(seconds);
    timerIntervalRef.current = setInterval(() => {
      setTimer((prev) => {
        if (prev <= 1) {
          if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerIntervalRef.current) {
      clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
  }, []);

  // --- Audio Visualizer ---
  const drawVisualizer = useCallback(() => {
    const canvas = canvasRef.current;
    const analyser = analyserRef.current;
    if (!canvas || !analyser) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const draw = () => {
      animFrameRef.current = requestAnimationFrame(draw);
      analyser.getByteFrequencyData(dataArray);

      ctx.fillStyle = 'rgb(20, 25, 35)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      const barWidth = (canvas.width / bufferLength) * 2.5;
      let x = 0;

      for (let i = 0; i < bufferLength; i++) {
        const barHeight = (dataArray[i] / 255) * canvas.height;
        // Teal hue range (170-200) matching the brand palette
        const hue = (i / bufferLength) * 30 + 170;
        ctx.fillStyle = `hsl(${hue}, 65%, 50%)`;
        ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
        x += barWidth + 1;
      }
    };

    draw();
  }, []);

  // --- MediaRecorder ---
  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Set up analyser for visualizer
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext();
      }
      const ctx = audioContextRef.current;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;
      drawVisualizer();

      const recorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm;codecs=opus',
      });

      recorder.ondataavailable = async (event) => {
        if (event.data.size > 0 && wsClientRef.current?.isConnected) {
          const buffer = await event.data.arrayBuffer();
          wsClientRef.current.sendBinary(buffer);
        }
      };

      recorder.start(250); // send chunks every 250ms
      mediaRecorderRef.current = recorder;
      setIsRecording(true);

      // Tell server we're recording
      wsClientRef.current?.sendAudioMeta('audio/webm;codecs=opus');
      wsClientRef.current?.startRecording();

      addLog('Recording started');
    } catch (err) {
      toast.error('Microphone access denied');
      addLog(`Mic error: ${err}`);
    }
  }, [addLog, drawVisualizer]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current.stream.getTracks().forEach((t) => t.stop());
      mediaRecorderRef.current = null;
    }
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
    }
    analyserRef.current = null;
    setIsRecording(false);
    wsClientRef.current?.stopRecording();
    addLog('Recording stopped');
  }, [addLog]);

  // --- WebSocket Message Handler ---
  const handleMessage = useCallback(
    (msg: WSMessage) => {
      addLog(`WS: ${msg.type}`);

      switch (msg.type) {
        case 'connected':
          addLog(`Connected: ${(msg as Record<string, unknown>).message}`);
          break;

        case 'question': {
          const q = msg as { question?: Question; text?: string; duration_seconds?: number; is_follow_up?: boolean; sub_question_label?: string; follow_up_count?: number; type: string };
          const question: Question = q.question || {
            id: '',
            text: (q.text as string) || '',
            type: 'technical',
            duration_seconds: q.duration_seconds,
            is_follow_up: q.is_follow_up,
            sub_question_label: q.sub_question_label,
            follow_up_count: q.follow_up_count,
          };
          setCurrentQuestion(question);
          setEvaluation(null);
          setTranscript('');
          if (q.duration_seconds) {
            startTimer(q.duration_seconds as number);
          }
          break;
        }

        case 'listening':
          // Auto-start recording
          startRecording();
          break;

        case 'transcript':
          setTranscript((msg as { text?: string }).text || '');
          break;

        case 'evaluating':
          stopRecording();
          stopTimer();
          break;

        case 'evaluation': {
          const evalMsg = msg as { evaluation?: Evaluation; score?: number; strengths?: string[]; improvements?: string[]; recommendation?: string };
          const evaluation = evalMsg.evaluation || {
            score: evalMsg.score || 0,
            strengths: evalMsg.strengths || [],
            improvements: evalMsg.improvements || [],
            recommendation: evalMsg.recommendation || '',
          };
          setEvaluation(evaluation);
          break;
        }

        case 'progress': {
          const p = msg as { current_question?: number; total_questions?: number; current_stage?: string };
          setProgress({
            current: p.current_question || 0,
            total: p.total_questions || 0,
            stage: (p.current_stage as string) || '',
          });
          break;
        }

        case 'stage_change':
          addLog(`Stage: ${(msg as Record<string, unknown>).stage}`);
          break;

        case 'timer_warning':
          toast.warning(`${(msg as { remaining_seconds?: number }).remaining_seconds}s remaining!`);
          break;

        case 'timer_expired':
          stopRecording();
          stopTimer();
          toast.error('Time expired');
          break;

        case 'interview_complete':
          stopRecording();
          stopTimer();
          toast.success('Interview complete!');
          break;

        case 'error':
          toast.error((msg as { message?: string }).message || 'Error');
          break;

        case 'tts_start':
          audioQueueRef.current = [];
          break;

        case 'tts_end':
          // TTS finished, queue should drain naturally
          break;
      }
    },
    [addLog, startRecording, stopRecording, startTimer, stopTimer]
  );

  // --- Connect ---
  const connect = useCallback(() => {
    const url = getWebSocketURL(sessionId);
    const client = new VoiceWSClient({
      url,
      onMessage: handleMessage,
      onBinary: queueAudio,
      onStateChange: setWsState,
      onError: (err) => {
        addLog(`Error: ${err}`);
        toast.error(err);
      },
    });
    wsClientRef.current = client;
    client.connect();
  }, [sessionId, handleMessage, queueAudio, addLog]);

  // --- Disconnect ---
  const disconnect = useCallback(() => {
    stopRecording();
    stopTimer();
    wsClientRef.current?.disconnect();
    wsClientRef.current = null;
  }, [stopRecording, stopTimer]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const stateLabel: Record<WSState, string> = {
    disconnected: 'Disconnected',
    connecting: 'Connecting...',
    connected: 'Connected',
    question: 'Question',
    listening: 'Listening',
    processing: 'Processing',
    evaluating: 'Evaluating',
    complete: 'Complete',
    error: 'Error',
  };

  const stateVariant = (s: WSState): 'default' | 'secondary' | 'destructive' | 'outline' => {
    switch (s) {
      case 'connected':
      case 'listening':
        return 'default';
      case 'error':
        return 'destructive';
      case 'complete':
        return 'default';
      default:
        return 'secondary';
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Voice Interview</h1>
          <p className="text-sm text-muted-foreground font-mono">
            {sessionId.slice(0, 16)}...
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={stateVariant(wsState)}>
            {stateLabel[wsState]}
          </Badge>
          {isRecording && (
            <Badge variant="destructive" className="animate-pulse">
              REC
            </Badge>
          )}
        </div>
      </div>

      {/* Progress */}
      {progress.total > 0 && (
        <Card>
          <CardContent className="py-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-muted-foreground">
                Q {progress.current}/{progress.total}
              </span>
              <div className="flex items-center gap-2">
                {progress.stage && (
                  <Badge variant="outline" className="capitalize">
                    {progress.stage.replace('_', ' ')}
                  </Badge>
                )}
                {timer > 0 && (
                  <span
                    className={`text-sm font-mono flex items-center gap-1 ${
                      timer < 60 ? 'text-destructive' : ''
                    }`}
                  >
                    <Clock className="h-3 w-3" />
                    {formatTime(timer)}
                  </span>
                )}
              </div>
            </div>
            <Progress
              value={progress.total > 0 ? (progress.current / progress.total) * 100 : 0}
            />
          </CardContent>
        </Card>
      )}

      {/* Main Content */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Left: Question + Audio */}
        <div className="space-y-4">
          {/* Connection */}
          {wsState === 'disconnected' && (
            <Card>
              <CardContent className="flex flex-col items-center gap-4 py-12">
                <Phone className="h-12 w-12 text-muted-foreground" />
                <p className="text-muted-foreground">
                  Click to start the voice interview
                </p>
                <Button size="lg" onClick={connect}>
                  <Phone className="mr-2 h-5 w-5" />
                  Connect
                </Button>
              </CardContent>
            </Card>
          )}

          {wsState === 'complete' && (
            <Card>
              <CardContent className="flex flex-col items-center gap-4 py-12">
                <CheckCircle2 className="h-16 w-16 text-success" />
                <h2 className="text-xl font-bold">Interview Complete</h2>
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
          )}

          {/* Current Question */}
          {currentQuestion && wsState !== 'complete' && wsState !== 'disconnected' && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <CardTitle className="text-base">
                    {currentQuestion.is_follow_up ? 'Follow-up' : 'Question'}
                  </CardTitle>
                  {currentQuestion.is_follow_up && (
                    <Badge variant="secondary" className="text-xs">Follow-up</Badge>
                  )}
                  {currentQuestion.sub_question_label && (
                    <Badge variant="outline" className="text-xs">{currentQuestion.sub_question_label}</Badge>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-relaxed whitespace-pre-wrap">
                  {currentQuestion.text}
                </p>
              </CardContent>
            </Card>
          )}

          {/* Audio Visualizer */}
          {wsState !== 'disconnected' && wsState !== 'complete' && (
            <Card>
              <CardContent className="py-3">
                <canvas
                  ref={canvasRef}
                  width={500}
                  height={80}
                  className="w-full rounded bg-black"
                />
              </CardContent>
            </Card>
          )}

          {/* Controls */}
          {wsState !== 'disconnected' && wsState !== 'complete' && (
            <Card>
              <CardContent className="py-3">
                <div className="flex flex-wrap gap-2">
                  {wsState === 'listening' && !isRecording && (
                    <Button onClick={startRecording}>
                      <Mic className="mr-2 h-4 w-4" />
                      Record
                    </Button>
                  )}
                  {isRecording && (
                    <Button variant="destructive" onClick={stopRecording}>
                      <MicOff className="mr-2 h-4 w-4" />
                      Stop Recording
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    onClick={() => wsClientRef.current?.skipQuestion()}
                  >
                    <SkipForward className="mr-2 h-4 w-4" />
                    Skip
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setShowTextFallback(!showTextFallback)}
                  >
                    <Keyboard className="mr-2 h-4 w-4" />
                    Text
                  </Button>
                  <Button variant="destructive" onClick={() => {
                    wsClientRef.current?.endInterview();
                  }}>
                    <PhoneOff className="mr-2 h-4 w-4" />
                    End
                  </Button>
                </div>

                {/* Text fallback */}
                {showTextFallback && (
                  <div className="mt-3 flex gap-2">
                    <Textarea
                      value={textAnswer}
                      onChange={(e) => setTextAnswer(e.target.value)}
                      placeholder="Type your answer..."
                      rows={3}
                      className="flex-1"
                    />
                    <Button
                      onClick={() => {
                        if (textAnswer.trim()) {
                          wsClientRef.current?.sendTextAnswer(textAnswer.trim());
                          setTextAnswer('');
                          setShowTextFallback(false);
                        }
                      }}
                      disabled={!textAnswer.trim()}
                    >
                      <Send className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        {/* Right: Transcript + Evaluation */}
        <div className="space-y-4">
          {/* Transcript */}
          {transcript && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Transcript</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm italic text-muted-foreground">
                  &quot;{transcript}&quot;
                </p>
              </CardContent>
            </Card>
          )}

          {/* Evaluation */}
          {evaluation && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">Evaluation</CardTitle>
                  <Badge
                    variant={
                      evaluation.score >= 70
                        ? 'default'
                        : evaluation.score >= 40
                        ? 'secondary'
                        : 'destructive'
                    }
                    className="text-lg px-3"
                  >
                    {evaluation.score}/100
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {evaluation.strengths?.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-success mb-1">Strengths</h4>
                    <ul className="list-disc list-inside text-xs space-y-0.5">
                      {evaluation.strengths.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {evaluation.improvements?.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold text-warning mb-1">Improvements</h4>
                    <ul className="list-disc list-inside text-xs space-y-0.5">
                      {evaluation.improvements.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {evaluation.recommendation && (
                  <p className="text-xs">
                    <span className="font-semibold">Recommendation:</span>{' '}
                    <span className="capitalize">{evaluation.recommendation}</span>
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Status indicator for mid-states */}
          {(wsState === 'connecting' || wsState === 'processing' || wsState === 'evaluating') && (
            <Card>
              <CardContent className="flex items-center gap-3 py-6">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span className="text-sm text-muted-foreground capitalize">
                  {wsState === 'connecting'
                    ? 'Connecting to server...'
                    : wsState === 'processing'
                    ? 'Processing your answer...'
                    : 'Evaluating your answer...'}
                </span>
              </CardContent>
            </Card>
          )}

          {/* Debug Log */}
          <Card>
            <CardHeader className="cursor-pointer py-3" onClick={() => setShowLog(!showLog)}>
              <CardTitle className="text-sm text-muted-foreground">
                {showLog ? 'Hide' : 'Show'} Debug Log ({log.length})
              </CardTitle>
            </CardHeader>
            {showLog && (
              <CardContent>
                <pre className="max-h-48 overflow-y-auto text-xs text-muted-foreground whitespace-pre-wrap">
                  {log.join('\n')}
                </pre>
              </CardContent>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

export default function VoiceInterviewPage() {
  return (
    <ProtectedRoute>
      <VoiceInterviewContent />
    </ProtectedRoute>
  );
}
