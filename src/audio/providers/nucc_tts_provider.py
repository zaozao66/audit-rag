import json
import logging
from typing import Any, Dict, Optional

import requests

from src.audio.providers.base import BaseTTSProvider, TTSRequest, TTSResult
from src.audio.providers.qwen_tts_provider import FORMAT_TO_MIME


class NUCCTTSProvider(BaseTTSProvider):
    provider_name = "nucc_tts"

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger(__name__)
        self.endpoint = str(config.get("endpoint", "")).rstrip("/")
        self.api_key = str(config.get("api_key", "")).strip()
        self.default_model = str(config.get("model", "qwen3-tts")).strip() or "qwen3-tts"
        self.default_voice = str(config.get("default_voice", "Uncle_Fu")).strip() or "Uncle_Fu"
        self.default_task_type = str(config.get("task_type", "VoiceDesign")).strip() or "VoiceDesign"
        self.default_language = str(config.get("language", "Chinese")).strip() or "Chinese"
        self.default_instructions = str(config.get("instructions", "用播音员播报的语气")).strip() or "用播音员播报的语气"
        self.ssl_verify = bool(config.get("ssl_verify", True))
        self.default_timeout = float(config.get("request_timeout", 20.0))

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if not self.endpoint:
            raise ValueError("NUCC TTS endpoint 未配置")
        if not self.api_key:
            raise ValueError("NUCC TTS api_key 未配置")

        model = str(request.model or self.default_model).strip() or self.default_model
        voice = str(request.voice or self.default_voice).strip() or self.default_voice
        task_type = str(request.task_type or self.default_task_type).strip() or self.default_task_type
        language = str(request.language or self.default_language).strip() or self.default_language
        instructions = str(request.instructions or self.default_instructions).strip() or self.default_instructions

        payload = {
            "model": model,
            "input": request.input_text,
            "voice": voice,
            "task_type": task_type,
            "language": language,
            "instructions": instructions,
        }
        headers = {
            "Authorization": self._build_authorization_header(self.api_key),
            "Content-Type": "application/json",
        }

        url = self._build_url()
        timeout = request.timeout_sec or self.default_timeout
        self._logger.info("NUCC TTS 请求URL: %s model=%s voice=%s", url, model, voice)
        response = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=timeout,
            verify=self.ssl_verify,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"NUCC TTS 请求失败({response.status_code}) url={url}: {response.text[:220]}")

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "audio/" not in content_type and "application/octet-stream" not in content_type:
            raise RuntimeError(f"NUCC TTS 返回非音频内容: {content_type or 'unknown'}")

        audio_format = self._detect_audio_format(content_type, fallback=request.audio_format or "wav")
        audio_bytes = response.content
        if not audio_bytes:
            raise RuntimeError("NUCC TTS 返回空音频")

        return TTSResult(
            audio_bytes=audio_bytes,
            mime_type=FORMAT_TO_MIME.get(audio_format, content_type or "application/octet-stream"),
            model=model,
            voice=voice,
            audio_format=audio_format,
            sample_rate=int(request.sample_rate),
            provider=self.provider_name,
            metadata={
                "task_type": task_type,
                "language": language,
                "instructions": instructions,
            },
        )

    def _build_url(self) -> str:
        if self.endpoint.endswith("/audio/speech"):
            return self.endpoint
        return f"{self.endpoint}/audio/speech"

    @staticmethod
    def _build_authorization_header(api_key: str) -> str:
        token = str(api_key or "").strip()
        if token.lower().startswith("bearer "):
            return token
        return f"Bearer {token}"

    @staticmethod
    def _detect_audio_format(content_type: str, fallback: str) -> str:
        lowered = str(content_type or "").lower()
        if "audio/wav" in lowered or "audio/x-wav" in lowered:
            return "wav"
        if "audio/mpeg" in lowered or "audio/mp3" in lowered:
            return "mp3"
        if "audio/ogg" in lowered:
            return "opus"
        if "audio/aac" in lowered:
            return "aac"
        return str(fallback or "wav").strip().lower() or "wav"
