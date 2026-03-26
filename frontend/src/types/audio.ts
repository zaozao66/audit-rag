export type SpeechPlayState = 'idle' | 'loading' | 'playing' | 'paused' | 'stopped' | 'error';

export interface SpeechScriptResponse {
  id: string;
  speech_text: string;
  style: 'brief' | 'full' | 'report' | string;
  fallback_used: boolean;
}

export interface AudioSpeechResponse {
  id: string;
  object: 'audio.speech' | string;
  created: number;
  provider: string;
  model: string;
  voice: string;
  format: string;
  sample_rate: number;
  audio_url: string;
  file_name: string;
  cache_hit: boolean;
  size_bytes: number;
  duration_ms?: number | null;
}

export interface MessageSpeechState {
  state: SpeechPlayState;
  speechText?: string;
  audioUrl?: string;
  audioId?: string;
  error?: string;
}
