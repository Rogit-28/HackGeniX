// ============================================================
// WebSocket client for voice interview
// ============================================================

import type { WSMessage } from './types';

export type WSState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'question'
  | 'listening'
  | 'processing'
  | 'evaluating'
  | 'complete'
  | 'error';

export type WSEventHandler = (msg: WSMessage) => void;
export type WSBinaryHandler = (data: ArrayBuffer) => void;
export type WSStateHandler = (state: WSState) => void;

export class VoiceWSClient {
  private ws: WebSocket | null = null;
  private url: string;
  private onMessage: WSEventHandler;
  private onBinary: WSBinaryHandler;
  private onStateChange: WSStateHandler;
  private onError: (error: string) => void;
  private _state: WSState = 'disconnected';

  constructor(opts: {
    url: string;
    onMessage: WSEventHandler;
    onBinary: WSBinaryHandler;
    onStateChange: WSStateHandler;
    onError: (error: string) => void;
  }) {
    this.url = opts.url;
    this.onMessage = opts.onMessage;
    this.onBinary = opts.onBinary;
    this.onStateChange = opts.onStateChange;
    this.onError = opts.onError;
  }

  get state(): WSState {
    return this._state;
  }

  private setState(s: WSState) {
    this._state = s;
    this.onStateChange(s);
  }

  connect() {
    if (this.ws) {
      this.ws.close();
    }

    this.setState('connecting');
    this.ws = new WebSocket(this.url);
    this.ws.binaryType = 'arraybuffer';

    this.ws.onopen = () => {
      this.setState('connected');
    };

    this.ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        this.onBinary(event.data);
        return;
      }

      try {
        const msg = JSON.parse(event.data as string) as WSMessage;

        // Auto-track state transitions from server messages
        switch (msg.type) {
          case 'connected':
            this.setState('connected');
            break;
          case 'question':
            this.setState('question');
            break;
          case 'listening':
            this.setState('listening');
            break;
          case 'transcript':
            this.setState('processing');
            break;
          case 'evaluating':
            this.setState('evaluating');
            break;
          case 'interview_complete':
            this.setState('complete');
            break;
          case 'error':
            if (!(msg as { recoverable?: boolean }).recoverable) {
              this.setState('error');
            }
            break;
        }

        this.onMessage(msg);
      } catch (err) {
        console.error('WS parse error:', err);
      }
    };

    this.ws.onerror = () => {
      this.onError('WebSocket connection error');
      this.setState('error');
    };

    this.ws.onclose = (event) => {
      if (this._state !== 'complete') {
        this.setState('disconnected');
        if (event.code !== 1000) {
          this.onError(`Connection closed: ${event.reason || event.code}`);
        }
      }
    };
  }

  sendJSON(msg: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  sendBinary(data: ArrayBuffer | Blob) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(data);
    }
  }

  // Convenience methods for control messages
  startRecording() {
    this.sendJSON({ type: 'control', action: 'start_recording' });
  }

  stopRecording() {
    this.sendJSON({ type: 'control', action: 'stop_recording' });
  }

  skipQuestion() {
    this.sendJSON({ type: 'control', action: 'skip_question' });
  }

  endInterview() {
    this.sendJSON({ type: 'control', action: 'end_interview' });
  }

  pause() {
    this.sendJSON({ type: 'control', action: 'pause' });
  }

  resume() {
    this.sendJSON({ type: 'control', action: 'resume' });
  }

  sendTextAnswer(text: string) {
    this.sendJSON({ type: 'text_answer', text });
  }

  sendAudioMeta(mimeType: string) {
    this.sendJSON({ type: 'audio_meta', mime_type: mimeType });
  }

  disconnect() {
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.setState('disconnected');
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
