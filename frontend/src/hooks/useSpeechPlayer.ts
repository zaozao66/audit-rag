import { useCallback, useEffect, useRef } from 'react';
import type { SpeechPlayState } from '../types/audio';

type SpeechStateChangeHandler = (messageId: string, state: SpeechPlayState, error?: string) => void;

export function useSpeechPlayer(onStateChange?: SpeechStateChangeHandler) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const currentMessageIdRef = useRef<string | null>(null);
  const onStateChangeRef = useRef<SpeechStateChangeHandler | undefined>(onStateChange);

  useEffect(() => {
    onStateChangeRef.current = onStateChange;
  }, [onStateChange]);

  useEffect(() => {
    if (!audioRef.current) {
      audioRef.current = new Audio();
      audioRef.current.preload = 'auto';
    }
    const audio = audioRef.current;

    const onPlaying = () => {
      const id = currentMessageIdRef.current;
      if (id) onStateChangeRef.current?.(id, 'playing');
    };
    const onPause = () => {
      const id = currentMessageIdRef.current;
      if (!id) return;
      if (audio.ended || audio.currentTime === 0) {
        onStateChangeRef.current?.(id, 'stopped');
      } else {
        onStateChangeRef.current?.(id, 'paused');
      }
    };
    const onEnded = () => {
      const id = currentMessageIdRef.current;
      if (id) onStateChangeRef.current?.(id, 'stopped');
    };
    const onError = () => {
      const id = currentMessageIdRef.current;
      if (id) onStateChangeRef.current?.(id, 'error', '音频播放失败');
    };

    audio.addEventListener('playing', onPlaying);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('ended', onEnded);
    audio.addEventListener('error', onError);

    return () => {
      audio.pause();
      audio.removeEventListener('playing', onPlaying);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('ended', onEnded);
      audio.removeEventListener('error', onError);
    };
  }, []);

  const stopAll = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const id = currentMessageIdRef.current;
    if (id) {
      audio.pause();
      audio.currentTime = 0;
      onStateChangeRef.current?.(id, 'stopped');
    }
    currentMessageIdRef.current = null;
  }, []);

  const playFromUrl = useCallback(async (messageId: string, audioUrl: string, fromStart = false) => {
    const audio = audioRef.current;
    if (!audio) return;

    const prevId = currentMessageIdRef.current;
    if (prevId && prevId !== messageId) {
      audio.pause();
      audio.currentTime = 0;
      onStateChangeRef.current?.(prevId, 'stopped');
    }

    currentMessageIdRef.current = messageId;
    onStateChangeRef.current?.(messageId, 'loading');

    if (audio.src !== audioUrl) {
      audio.src = audioUrl;
    }
    if (fromStart) {
      audio.currentTime = 0;
    }

    try {
      await audio.play();
    } catch (err) {
      const message = err instanceof Error ? err.message : '音频播放失败';
      onStateChangeRef.current?.(messageId, 'error', message);
      throw err;
    }
  }, []);

  const pause = useCallback((messageId: string) => {
    const audio = audioRef.current;
    if (!audio || currentMessageIdRef.current !== messageId) return;
    audio.pause();
  }, []);

  const resume = useCallback(async (messageId: string) => {
    const audio = audioRef.current;
    if (!audio || currentMessageIdRef.current !== messageId) return;
    onStateChangeRef.current?.(messageId, 'loading');
    try {
      await audio.play();
    } catch (err) {
      const message = err instanceof Error ? err.message : '继续播放失败';
      onStateChangeRef.current?.(messageId, 'error', message);
      throw err;
    }
  }, []);

  const stop = useCallback((messageId: string) => {
    const audio = audioRef.current;
    if (!audio || currentMessageIdRef.current !== messageId) return;
    audio.pause();
    audio.currentTime = 0;
    onStateChangeRef.current?.(messageId, 'stopped');
  }, []);

  return {
    playFromUrl,
    pause,
    resume,
    stop,
    stopAll,
  };
}
