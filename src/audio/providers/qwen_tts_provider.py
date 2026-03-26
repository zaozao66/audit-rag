import base64
import json
import logging
from typing import Any, Dict, Optional

import requests

from src.audio.providers.base import BaseTTSProvider, TTSRequest, TTSResult


FORMAT_TO_MIME = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
    "opus": "audio/ogg",
    "aac": "audio/aac",
}


class QwenTTSProvider(BaseTTSProvider):
    provider_name = "qwen"

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger(__name__)
        self.endpoint = str(config.get("endpoint", "")).rstrip("/")
        self.api_key = str(config.get("api_key", ""))
        self.default_model = str(config.get("model", "qwen-tts"))
        self.ssl_verify = bool(config.get("ssl_verify", True))
        self.default_timeout = float(config.get("request_timeout", 20.0))

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if not self.endpoint:
            raise ValueError("Qwen TTS endpoint 未配置")
        if not self.api_key:
            raise ValueError("Qwen TTS api_key 未配置")

        model = request.model or self.default_model
        if "realtime" in model.lower():
            raise ValueError(
                "当前 /v1/audio/speech 仅支持 HTTP TTS。"
                "realtime 模型请走 WebSocket 实时接口（wss://dashscope.aliyuncs.com/api-ws/v1/realtime）"
            )

        audio_format = (request.audio_format or "mp3").lower()
        if self._is_dashscope_endpoint(self.endpoint):
            return self._synthesize_by_dashscope_multimodal(request, model, audio_format)

        return self._synthesize_by_openai_compatible(request, model, audio_format)

    def _synthesize_by_openai_compatible(self, request: TTSRequest, model: str, audio_format: str) -> TTSResult:
        payload = {
            "model": model,
            "input": request.input_text,
            "voice": request.voice,
            "response_format": audio_format,
            "sample_rate": int(request.sample_rate),
            "speed": float(request.speed),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        timeout = request.timeout_sec or self.default_timeout
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error = None
        for url in self._build_candidate_urls():
            self._logger.info("Qwen TTS(OpenAI兼容) 请求URL: %s model=%s", url, model)
            response = requests.post(
                url,
                headers=headers,
                data=request_body,
                timeout=timeout,
                verify=self.ssl_verify,
            )
            if response.status_code == 404:
                last_error = f"Qwen TTS 请求失败(404) url={url}: {response.text[:220]}"
                self._logger.warning(last_error)
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"Qwen TTS 请求失败({response.status_code}) url={url}: {response.text[:220]}")
            break
        else:
            raise RuntimeError(last_error or "Qwen TTS 请求失败: 未找到可用接口地址")

        content_type = (response.headers.get("Content-Type") or "").lower()
        audio_bytes = response.content
        if "application/json" in content_type:
            audio_bytes = self._decode_audio_json(response.text)

        if not audio_bytes:
            raise RuntimeError("Qwen TTS 返回空音频")

        return TTSResult(
            audio_bytes=audio_bytes,
            mime_type=FORMAT_TO_MIME.get(audio_format, "application/octet-stream"),
            model=model,
            voice=request.voice,
            audio_format=audio_format,
            sample_rate=int(request.sample_rate),
            provider=self.provider_name,
        )

    def _synthesize_by_dashscope_multimodal(self, request: TTSRequest, model: str, audio_format: str) -> TTSResult:
        url = self._build_dashscope_generation_url(self.endpoint)
        timeout = request.timeout_sec or self.default_timeout
        payload = {
            "model": model,
            "input": {
                "text": request.input_text,
                "voice": request.voice,
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        self._logger.info("Qwen TTS(DashScope) 请求URL: %s model=%s", url, model)
        response = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=timeout,
            verify=self.ssl_verify,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Qwen TTS 请求失败({response.status_code}) url={url}: {response.text[:220]}")

        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"Qwen TTS 响应解析失败: {response.text[:220]}") from exc

        output = data.get("output", {}) if isinstance(data.get("output"), dict) else {}
        audio_node = output.get("audio", {}) if isinstance(output.get("audio"), dict) else {}
        audio_data = audio_node.get("data")
        audio_url = audio_node.get("url")

        if audio_data:
            audio_bytes = self._decode_audio_json(json.dumps({"audio": audio_data}, ensure_ascii=False))
            return TTSResult(
                audio_bytes=audio_bytes,
                mime_type=FORMAT_TO_MIME.get(audio_format, "application/octet-stream"),
                model=model,
                voice=request.voice,
                audio_format=audio_format,
                sample_rate=int(request.sample_rate),
                provider=self.provider_name,
            )

        if audio_url:
            audio_resp = requests.get(
                str(audio_url),
                timeout=timeout,
                verify=self.ssl_verify,
            )
            if audio_resp.status_code >= 400:
                raise RuntimeError(
                    f"Qwen TTS 音频下载失败({audio_resp.status_code}) audio_url={audio_url}: {audio_resp.text[:180]}"
                )

            content_type = (audio_resp.headers.get("Content-Type") or "").lower()
            detected_format = audio_format
            if "wav" in content_type or str(audio_url).lower().endswith(".wav"):
                detected_format = "wav"
            elif "mpeg" in content_type or "mp3" in content_type or str(audio_url).lower().endswith(".mp3"):
                detected_format = "mp3"

            return TTSResult(
                audio_bytes=audio_resp.content,
                mime_type=FORMAT_TO_MIME.get(detected_format, "application/octet-stream"),
                model=model,
                voice=request.voice,
                audio_format=detected_format,
                sample_rate=int(request.sample_rate),
                provider=self.provider_name,
                metadata={"audio_url": audio_url},
            )

        raise RuntimeError(f"Qwen TTS 返回中未找到音频字段: {json.dumps(data, ensure_ascii=False)[:260]}")

    def _decode_audio_json(self, payload_text: str) -> bytes:
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Qwen TTS JSON响应解析失败") from exc

        data_node = payload.get("data")
        candidates = [
            payload.get("audio"),
            payload.get("audio_base64"),
        ]
        if isinstance(data_node, dict):
            candidates.append(data_node.get("audio"))

        data_array = data_node
        if isinstance(data_array, list) and data_array:
            first = data_array[0] if isinstance(data_array[0], dict) else {}
            candidates.append(first.get("b64_json"))
            candidates.append(first.get("audio"))

        for candidate in candidates:
            if not candidate:
                continue
            try:
                return base64.b64decode(candidate)
            except Exception:
                continue

        raise RuntimeError("Qwen TTS JSON中未找到可解码音频")

    def _build_candidate_urls(self) -> list[str]:
        endpoint = self.endpoint.rstrip("/")
        candidates = [f"{endpoint}/audio/speech"]

        if "dashscope.aliyuncs.com" in endpoint:
            if "/compatible-mode/v1" not in endpoint:
                candidates.append(f"{endpoint}/compatible-mode/v1/audio/speech")
            if endpoint.endswith("/v1") and "/compatible-mode/" not in endpoint:
                base = endpoint[: -len("/v1")]
                candidates.append(f"{base}/compatible-mode/v1/audio/speech")

        # Deduplicate while preserving order.
        result = []
        seen = set()
        for item in candidates:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    @staticmethod
    def _is_dashscope_endpoint(endpoint: str) -> bool:
        value = str(endpoint or "").lower()
        return "dashscope.aliyuncs.com" in value or "dashscope-intl.aliyuncs.com" in value

    @staticmethod
    def _build_dashscope_generation_url(endpoint: str) -> str:
        value = str(endpoint or "").rstrip("/")
        if value.endswith("/compatible-mode/v1"):
            value = value[: -len("/compatible-mode/v1")] + "/api/v1"
        elif value.endswith("/compatible-api/v1"):
            value = value[: -len("/compatible-api/v1")] + "/api/v1"
        elif value.endswith("/v1") and "/api/" not in value:
            value = value[: -len("/v1")] + "/api/v1"
        elif not value.endswith("/api/v1"):
            if value.endswith("/api"):
                value = value + "/v1"
            else:
                value = value + "/api/v1"

        return f"{value}/services/aigc/multimodal-generation/generation"
