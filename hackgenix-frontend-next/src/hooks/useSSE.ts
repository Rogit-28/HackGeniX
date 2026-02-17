'use client';

// ============================================================
// useSSE hook — consumes SSE streams and accumulates text
// ============================================================

import { useState, useCallback, useRef } from 'react';
import { streamSSE } from '@/lib/api';
import type { SSEEvent } from '@/lib/types';

interface UseSSEOptions {
  onEvent?: (event: SSEEvent) => void;
  onComplete?: (fullText: string, lastData: unknown) => void;
  onError?: (error: string) => void;
}

export function useSSE(options: UseSSEOptions = {}) {
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef(false);

  const startStream = useCallback(
    async (url: string, fetchOptions: RequestInit = {}) => {
      setIsStreaming(true);
      setStreamText('');
      setError(null);
      abortRef.current = false;

      let fullText = '';
      let lastParsed: unknown = null;

      try {
        for await (const event of streamSSE(url, fetchOptions)) {
          if (abortRef.current) break;

          options.onEvent?.(event);

          // Try to parse the data
          try {
            const parsed = JSON.parse(event.data);
            lastParsed = parsed;

            // Accumulate text from token events
            if (parsed.token) {
              fullText += parsed.token;
              setStreamText(fullText);
            } else if (parsed.text) {
              fullText += parsed.text;
              setStreamText(fullText);
            } else if (parsed.chunk) {
              fullText += parsed.chunk;
              setStreamText(fullText);
            }
          } catch {
            // If not JSON, treat as plain text
            fullText += event.data;
            setStreamText(fullText);
          }
        }

        options.onComplete?.(fullText, lastParsed);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Stream error';
        setError(msg);
        options.onError?.(msg);
      } finally {
        setIsStreaming(false);
      }
    },
    [options]
  );

  const abort = useCallback(() => {
    abortRef.current = true;
  }, []);

  return { isStreaming, streamText, error, startStream, abort };
}
