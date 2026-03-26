import { useCallback, useRef } from 'react';

function base64ToUint8Array(base64: string): Uint8Array {
  const binary = window.atob(base64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function pcm16ToFloat32(bytes: Uint8Array): Float32Array {
  const sampleCount = Math.floor(bytes.length / 2);
  const out = new Float32Array(sampleCount);
  for (let i = 0; i < sampleCount; i += 1) {
    const lo = bytes[i * 2];
    const hi = bytes[i * 2 + 1];
    let val = (hi << 8) | lo;
    if (val & 0x8000) val -= 0x10000;
    out[i] = val / 32768;
  }
  return out;
}

export function useRealtimePcmPlayer() {
  const audioContextRef = useRef<AudioContext | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const sourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const currentMessageIdRef = useRef<string | null>(null);

  const ensureContext = useCallback(async (sampleRate = 24000) => {
    if (!audioContextRef.current || audioContextRef.current.state === 'closed') {
      const Ctx = (window.AudioContext || (window as any).webkitAudioContext) as typeof AudioContext;
      audioContextRef.current = new Ctx({ sampleRate });
      nextPlayTimeRef.current = audioContextRef.current.currentTime;
    }
    const ctx = audioContextRef.current;
    if (ctx.state === 'suspended') {
      await ctx.resume();
    }
    return ctx;
  }, []);

  const start = useCallback(async (messageId: string, sampleRate = 24000) => {
    await ensureContext(sampleRate);
    currentMessageIdRef.current = messageId;
  }, [ensureContext]);

  const appendBase64Pcm = useCallback(async (messageId: string, base64Delta: string, sampleRate = 24000) => {
    const ctx = await ensureContext(sampleRate);
    if (currentMessageIdRef.current !== messageId) {
      currentMessageIdRef.current = messageId;
      nextPlayTimeRef.current = ctx.currentTime;
    }

    const bytes = base64ToUint8Array(base64Delta);
    const floatData = pcm16ToFloat32(bytes);
    if (!floatData.length) return;

    const audioBuffer = ctx.createBuffer(1, floatData.length, sampleRate);
    audioBuffer.getChannelData(0).set(floatData);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    const startAt = Math.max(ctx.currentTime + 0.02, nextPlayTimeRef.current);
    source.start(startAt);
    nextPlayTimeRef.current = startAt + audioBuffer.duration;

    sourcesRef.current.add(source);
    source.onended = () => {
      sourcesRef.current.delete(source);
    };
  }, [ensureContext]);

  const pause = useCallback(async (messageId: string) => {
    if (currentMessageIdRef.current !== messageId) return;
    const ctx = audioContextRef.current;
    if (!ctx) return;
    await ctx.suspend();
  }, []);

  const resume = useCallback(async (messageId: string) => {
    if (currentMessageIdRef.current !== messageId) return;
    const ctx = audioContextRef.current;
    if (!ctx) return;
    await ctx.resume();
  }, []);

  const stop = useCallback(async (messageId?: string) => {
    if (messageId && currentMessageIdRef.current !== messageId) return;

    for (const source of sourcesRef.current) {
      try {
        source.stop();
      } catch {
        // ignore
      }
    }
    sourcesRef.current.clear();

    const ctx = audioContextRef.current;
    if (ctx && ctx.state !== 'closed') {
      await ctx.close();
    }
    audioContextRef.current = null;
    nextPlayTimeRef.current = 0;
    currentMessageIdRef.current = null;
  }, []);

  return {
    start,
    appendBase64Pcm,
    pause,
    resume,
    stop,
    getCurrentMessageId: () => currentMessageIdRef.current,
  };
}
