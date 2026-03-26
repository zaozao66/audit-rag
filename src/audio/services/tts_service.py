import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.audio.providers.base import BaseTTSProvider, TTSRequest
from src.audio.services.media_store import MediaStore


@dataclass
class SynthesizedAudio:
    audio_id: str
    created: int
    provider: str
    model: str
    voice: str
    audio_format: str
    sample_rate: int
    mime_type: str
    audio_url: str
    file_name: str
    cache_hit: bool
    size_bytes: int
    duration_ms: Optional[int]
    audio_bytes: bytes


class TTSService:
    def __init__(
        self,
        provider: BaseTTSProvider,
        media_store: MediaStore,
        provider_name: str,
        default_model: str,
        default_voice: str,
        default_format: str,
        default_sample_rate: int,
        request_timeout: float = 20.0,
    ):
        self.provider = provider
        self.media_store = media_store
        self.provider_name = provider_name
        self.default_model = default_model
        self.default_voice = default_voice
        self.default_format = default_format
        self.default_sample_rate = int(default_sample_rate)
        self.request_timeout = float(request_timeout)

    def synthesize(
        self,
        input_text: str,
        scope: str,
        *,
        model: Optional[str] = None,
        voice: Optional[str] = None,
        audio_format: Optional[str] = None,
        sample_rate: Optional[int] = None,
        speed: Optional[float] = None,
        session_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> SynthesizedAudio:
        clean_text = str(input_text or "").strip()
        if not clean_text:
            raise ValueError("input 不能为空")

        final_model = str(model or self.default_model)
        final_voice = str(voice or self.default_voice)
        final_format = str(audio_format or self.default_format).lower()
        final_sample_rate = int(sample_rate or self.default_sample_rate)
        final_speed = float(speed or 1.0)

        cache_key = self.media_store.build_cache_key(
            clean_text,
            provider=self.provider_name,
            model=final_model,
            voice=final_voice,
            audio_format=final_format,
            sample_rate=final_sample_rate,
        )

        try:
            cached_item = self.media_store.ensure_audio(scope, cache_key, final_format, audio_bytes=None)
            with open(cached_item.file_path, "rb") as f:
                cached_bytes = f.read()
            return SynthesizedAudio(
                audio_id=f"aud_{uuid.uuid4().hex[:12]}",
                created=int(time.time()),
                provider=self.provider_name,
                model=final_model,
                voice=final_voice,
                audio_format=final_format,
                sample_rate=final_sample_rate,
                mime_type=self._guess_mime_type(final_format),
                audio_url=cached_item.audio_url,
                file_name=cached_item.file_name,
                cache_hit=True,
                size_bytes=cached_item.size_bytes,
                duration_ms=None,
                audio_bytes=cached_bytes,
            )
        except FileNotFoundError:
            pass

        tts_result = self.provider.synthesize(
            TTSRequest(
                input_text=clean_text,
                model=final_model,
                voice=final_voice,
                audio_format=final_format,
                sample_rate=final_sample_rate,
                speed=final_speed,
                timeout_sec=self.request_timeout,
                session_id=session_id,
                message_id=message_id,
                scope=scope,
            )
        )

        media_item = self.media_store.ensure_audio(
            scope=scope,
            cache_key=cache_key,
            audio_format=final_format,
            audio_bytes=tts_result.audio_bytes,
        )

        return SynthesizedAudio(
            audio_id=f"aud_{uuid.uuid4().hex[:12]}",
            created=int(time.time()),
            provider=self.provider_name,
            model=tts_result.model,
            voice=tts_result.voice,
            audio_format=tts_result.audio_format,
            sample_rate=tts_result.sample_rate,
            mime_type=tts_result.mime_type,
            audio_url=media_item.audio_url,
            file_name=media_item.file_name,
            cache_hit=media_item.cache_hit,
            size_bytes=media_item.size_bytes,
            duration_ms=tts_result.duration_ms,
            audio_bytes=tts_result.audio_bytes,
        )

    @staticmethod
    def _guess_mime_type(audio_format: str) -> str:
        lower = str(audio_format or "mp3").lower()
        if lower == "wav":
            return "audio/wav"
        if lower == "mp3":
            return "audio/mpeg"
        if lower == "pcm":
            return "audio/pcm"
        if lower == "opus":
            return "audio/ogg"
        return "application/octet-stream"

    def to_response_payload(self, audio: SynthesizedAudio) -> Dict[str, Any]:
        return {
            "id": audio.audio_id,
            "object": "audio.speech",
            "created": audio.created,
            "provider": audio.provider,
            "model": audio.model,
            "voice": audio.voice,
            "format": audio.audio_format,
            "sample_rate": audio.sample_rate,
            "audio_url": audio.audio_url,
            "file_name": audio.file_name,
            "cache_hit": audio.cache_hit,
            "size_bytes": audio.size_bytes,
            "duration_ms": audio.duration_ms,
        }
