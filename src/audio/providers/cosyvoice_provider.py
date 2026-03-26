import base64
import json
import logging
from typing import Any, Dict, Optional

import requests

from src.audio.providers.base import BaseTTSProvider, TTSRequest, TTSResult
from src.audio.providers.qwen_tts_provider import FORMAT_TO_MIME


class CosyVoiceProvider(BaseTTSProvider):
    provider_name = "cosyvoice"

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger(__name__)
        self.endpoint = str(config.get("endpoint", "")).rstrip("/")
        self.path = str(config.get("path", "/tts"))
        self.default_model = str(config.get("model", "cosyvoice"))
        self.default_voice = str(config.get("default_voice", "default"))
        self.ssl_verify = bool(config.get("ssl_verify", True))
        self.default_timeout = float(config.get("request_timeout", 20.0))

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if not self.endpoint:
            raise ValueError("CosyVoice endpoint 未配置")

        audio_format = (request.audio_format or "mp3").lower()
        url = f"{self.endpoint}{self.path}"
        payload = {
            "model": request.model or self.default_model,
            "text": request.input_text,
            "voice": request.voice or self.default_voice,
            "format": audio_format,
            "sample_rate": int(request.sample_rate),
            "speed": float(request.speed),
        }

        response = requests.post(
            url,
            json=payload,
            timeout=request.timeout_sec or self.default_timeout,
            verify=self.ssl_verify,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"CosyVoice 请求失败({response.status_code}): {response.text[:220]}")

        content_type = (response.headers.get("Content-Type") or "").lower()
        audio_bytes = response.content
        if "application/json" in content_type:
            audio_bytes = self._decode_audio_json(response.text)

        if not audio_bytes:
            raise RuntimeError("CosyVoice 返回空音频")

        return TTSResult(
            audio_bytes=audio_bytes,
            mime_type=FORMAT_TO_MIME.get(audio_format, "application/octet-stream"),
            model=payload["model"],
            voice=payload["voice"],
            audio_format=audio_format,
            sample_rate=int(request.sample_rate),
            provider=self.provider_name,
        )

    def _decode_audio_json(self, payload_text: str) -> bytes:
        payload = json.loads(payload_text)
        for key in ("audio", "audio_base64", "b64_audio"):
            value = payload.get(key)
            if not value:
                continue
            try:
                return base64.b64decode(value)
            except Exception:
                continue
        raise RuntimeError("CosyVoice JSON中未找到可解码音频")
