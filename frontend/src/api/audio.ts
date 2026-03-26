import { apiFetch } from './client';
import type { AudioSpeechResponse, SpeechScriptResponse } from '../types/audio';

export function buildSpeechScript(payload: {
  text: string;
  style?: 'brief' | 'full' | 'report' | string;
  sessionId?: string;
  messageId?: string;
}) {
  return apiFetch<SpeechScriptResponse>('/v1/speech/scripts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: payload.text,
      style: payload.style || 'brief',
      session_id: payload.sessionId,
      message_id: payload.messageId,
    }),
  });
}

export function synthesizeSpeech(payload: {
  input: string;
  model?: string;
  voice?: string;
  format?: string;
  sampleRate?: number;
  sessionId?: string;
  messageId?: string;
}) {
  return apiFetch<AudioSpeechResponse>('/v1/audio/speech', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      input: payload.input,
      model: payload.model,
      voice: payload.voice,
      format: payload.format,
      sample_rate: payload.sampleRate,
      response_mode: 'url',
      session_id: payload.sessionId,
      message_id: payload.messageId,
    }),
  });
}
