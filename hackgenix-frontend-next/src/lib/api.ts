// ============================================================
// Backend API client — REST + SSE streaming
// ============================================================

import { getStoredToken } from './auth';
import type {
  Resume,
  JobDescription,
  SessionSummary,
  SessionDetail,
  InterviewConfig,
  Report,
  HealthStatus,
  SSEEvent,
} from './types';

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  'https://hackgenix-production.up.railway.app';

// --- Helpers ---

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.message || JSON.stringify(body);
    } catch {
      // ignore parse errors
    }
    throw new Error(`API Error ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

// --- SSE Stream Consumer ---

export async function* streamSSE(
  url: string,
  options: RequestInit = {}
): AsyncGenerator<SSEEvent> {
  const res = await fetch(`${BACKEND_URL}${url}`, {
    ...options,
    headers: {
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.text();
      detail = body || detail;
    } catch {
      // ignore
    }
    throw new Error(`SSE Error ${res.status}: ${detail}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let currentEvent: string | undefined;
      let currentData = '';

      for (const line of lines) {
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          currentData += line.slice(5).trim();
        } else if (line === '' && currentData) {
          yield { event: currentEvent, data: currentData };
          currentEvent = undefined;
          currentData = '';
        }
      }
    }

    // flush remaining
    if (buffer.trim()) {
      const remaining = buffer.trim();
      if (remaining.startsWith('data:')) {
        yield { event: undefined, data: remaining.slice(5).trim() };
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// ============================================================
// REST API Methods
// ============================================================

// --- Documents: Resumes ---

export async function listResumes(): Promise<Resume[]> {
  const res = await fetch(`${BACKEND_URL}/api/v1/documents/resumes`, {
    headers: authHeaders(),
  });
  const data = await handleResponse<{ resumes: Resume[] }>(res);
  return data.resumes ?? [];
}

export async function getResume(id: string): Promise<Resume> {
  const res = await fetch(`${BACKEND_URL}/api/v1/documents/resumes/${id}`, {
    headers: authHeaders(),
  });
  return handleResponse<Resume>(res);
}

export function uploadResumeStream(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  return streamSSE('/api/v1/documents/resumes', {
    method: 'POST',
    body: formData,
    // Don't set Content-Type — browser sets multipart boundary automatically
  });
}

export async function deleteResume(id: string): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/api/v1/documents/resumes/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Delete failed: ${res.status}`);
  }
}

// --- Documents: Job Descriptions ---

export async function listJobDescriptions(): Promise<JobDescription[]> {
  const res = await fetch(
    `${BACKEND_URL}/api/v1/documents/job-descriptions`,
    { headers: authHeaders() }
  );
  const data = await handleResponse<{ job_descriptions: JobDescription[] }>(res);
  return data.job_descriptions ?? [];
}

export function createJDStream(text: string, title?: string) {
  return streamSSE('/api/v1/documents/job-descriptions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, title }),
  });
}

export function uploadJDStream(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  return streamSSE('/api/v1/documents/job-descriptions/upload', {
    method: 'POST',
    body: formData,
  });
}

export function matchResumeToJD(resumeId: string, jdId: string) {
  return streamSSE('/api/v1/documents/match', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      resume_id: resumeId,
      job_description_id: jdId,
    }),
  });
}

// --- Sessions ---

export function startSession(
  resumeId: string,
  jdId: string,
  config?: Partial<InterviewConfig>
) {
  return streamSSE('/api/v1/sessions/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      resume_id: resumeId,
      job_description_id: jdId,
      config: config || {},
    }),
  });
}

export async function listSessions(): Promise<SessionSummary[]> {
  const res = await fetch(`${BACKEND_URL}/api/v1/sessions/`, {
    headers: authHeaders(),
  });
  return handleResponse<SessionSummary[]>(res);
}

export async function getSession(id: string): Promise<SessionDetail> {
  const res = await fetch(`${BACKEND_URL}/api/v1/sessions/${id}`, {
    headers: authHeaders(),
  });
  return handleResponse<SessionDetail>(res);
}

export function submitAnswer(sessionId: string, answerText: string) {
  return streamSSE(`/api/v1/sessions/${sessionId}/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer_text: answerText }),
  });
}

export async function endSession(sessionId: string): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/api/v1/sessions/${sessionId}/end`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`End session failed: ${res.status}`);
}

export async function pauseSession(sessionId: string): Promise<void> {
  const res = await fetch(
    `${BACKEND_URL}/api/v1/sessions/${sessionId}/pause`,
    { method: 'POST', headers: authHeaders() }
  );
  if (!res.ok) throw new Error(`Pause failed: ${res.status}`);
}

export async function resumeSession(sessionId: string): Promise<void> {
  const res = await fetch(
    `${BACKEND_URL}/api/v1/sessions/${sessionId}/resume`,
    { method: 'POST', headers: authHeaders() }
  );
  if (!res.ok) throw new Error(`Resume failed: ${res.status}`);
}

export async function getAugmentationLog(
  sessionId: string
): Promise<unknown> {
  const res = await fetch(
    `${BACKEND_URL}/api/v1/sessions/${sessionId}/augmentation-log`,
    { headers: authHeaders() }
  );
  return handleResponse<unknown>(res);
}

// --- Reports ---

export async function listReports(): Promise<Report[]> {
  const res = await fetch(`${BACKEND_URL}/api/v1/reports/`, {
    headers: authHeaders(),
  });
  return handleResponse<Report[]>(res);
}

export async function getReport(sessionId: string): Promise<Report> {
  const res = await fetch(`${BACKEND_URL}/api/v1/reports/${sessionId}`, {
    headers: authHeaders(),
  });
  return handleResponse<Report>(res);
}

export async function downloadReportPDF(sessionId: string): Promise<Blob> {
  const res = await fetch(
    `${BACKEND_URL}/api/v1/reports/${sessionId}/pdf`,
    { headers: authHeaders() }
  );
  if (!res.ok) throw new Error(`PDF download failed: ${res.status}`);
  return res.blob();
}

// --- Health ---

export async function getHealth(): Promise<HealthStatus> {
  const res = await fetch(`${BACKEND_URL}/health`);
  return handleResponse<HealthStatus>(res);
}

export async function getDetailedHealth(): Promise<HealthStatus> {
  const res = await fetch(`${BACKEND_URL}/health/detailed`, {
    headers: authHeaders(),
  });
  return handleResponse<HealthStatus>(res);
}

// --- Utility ---

export function getBackendURL(): string {
  return BACKEND_URL;
}

export function getWebSocketURL(sessionId: string): string {
  const wsBase = BACKEND_URL.replace(/^http/, 'ws');
  const token = getStoredToken();
  return `${wsBase}/api/v1/interview/ws/${sessionId}?token=${token}`;
}
