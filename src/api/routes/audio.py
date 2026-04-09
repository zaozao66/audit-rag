import mimetypes
import os
import threading
from typing import Any, Dict, Optional

import httpx
from flask import Blueprint, Response, current_app, jsonify, request, send_file

from src.api.routes.scope_utils import extract_scope_from_request
from src.audio.services.speech_script_service import SpeechScriptService
from src.audio.services.tts_service import TTSService
from src.utils.config_loader import load_config


audio_bp = Blueprint("audio", __name__)


def _json_payload() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@audio_bp.route("/v1/speech/scripts", methods=["POST"])
def build_speech_script():
    try:
        data = _json_payload()
        text = str(data.get("text") or data.get("input") or "").strip()
        if not text:
            return jsonify({"error": "缺少 text 字段"}), 400

        style = data.get("style")
        script_service: SpeechScriptService = current_app.extensions["speech_script_service"]
        script = script_service.build_script(text, style=style)
        return jsonify(
            {
                "id": script.script_id,
                "speech_text": script.speech_text,
                "style": script.style,
                "fallback_used": script.fallback_used,
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("播报文案生成失败: %s", e, exc_info=True)
        return jsonify({"error": f"播报文案生成失败: {str(e)}"}), 500


@audio_bp.route("/v1/audio/speech", methods=["POST"])
def synthesize_speech():
    try:
        data = _json_payload()
        input_text = str(data.get("input") or "").strip()
        if not input_text:
            return jsonify({"error": "缺少 input 字段"}), 400

        scope = extract_scope_from_request(request, json_data=data) or "default"
        response_mode = str(data.get("response_mode") or "url").strip().lower()

        tts_service: TTSService = current_app.extensions["tts_service"]
        audio = tts_service.synthesize(
            input_text=input_text,
            scope=scope,
            model=data.get("model"),
            voice=data.get("voice"),
            audio_format=data.get("format") or data.get("response_format"),
            sample_rate=data.get("sample_rate"),
            speed=data.get("speed"),
            task_type=data.get("task_type"),
            language=data.get("language"),
            instructions=data.get("instructions"),
            session_id=data.get("session_id"),
            message_id=data.get("message_id"),
        )

        payload = tts_service.to_response_payload(audio)

        current_app.logger.info(
            "TTS合成完成: scope=%s provider=%s model=%s voice=%s format=%s cache_hit=%s size=%s",
            scope,
            payload.get("provider"),
            payload.get("model"),
            payload.get("voice"),
            payload.get("format"),
            payload.get("cache_hit"),
            payload.get("size_bytes"),
        )

        if response_mode == "stream":
            return Response(
                audio.audio_bytes,
                mimetype=audio.mime_type,
                headers={
                    "Content-Disposition": f'inline; filename="{audio.file_name}"',
                    "X-Audio-Id": audio.audio_id,
                    "X-Cache-Hit": str(audio.cache_hit).lower(),
                },
            )

        return jsonify(payload)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error("TTS合成失败: %s", e, exc_info=True)
        return jsonify({"error": f"TTS合成失败: {str(e)}"}), 500


@audio_bp.route("/v1/audio/files/<path:file_name>", methods=["GET"])
def get_audio_file(file_name: str):
    tts_service: TTSService = current_app.extensions.get("tts_service")
    if tts_service is None:
        return jsonify({"error": "TTS服务未启用"}), 503

    resolved = tts_service.media_store.resolve_file_path(file_name)
    if not resolved:
        return jsonify({"error": "音频文件不存在"}), 404

    mimetype, _ = mimetypes.guess_type(resolved)
    return send_file(
        resolved,
        mimetype=mimetype or "application/octet-stream",
        as_attachment=False,
        conditional=True,
        download_name=os.path.basename(resolved),
    )


# ---------------------------------------------------------------------------
# ASR 代理（懒加载 httpx 客户端）
# ---------------------------------------------------------------------------

_asr_lock = threading.Lock()
_asr_client: Optional[httpx.Client] = None
_asr_cfg: Optional[Dict] = None


def _get_asr_client():
    global _asr_client, _asr_cfg
    if _asr_client is not None:
        return _asr_client, _asr_cfg
    with _asr_lock:
        if _asr_client is not None:
            return _asr_client, _asr_cfg
        config = load_config()
        cfg = config.get("asr_proxy", {})
        ssl_verify = bool(cfg.get("ssl_verify", True))
        _asr_cfg = cfg
        _asr_client = httpx.Client(
            transport=httpx.HTTPTransport(retries=1, verify=ssl_verify),
            trust_env=False,
            timeout=float(cfg.get("request_timeout", 60)),
        )
    return _asr_client, _asr_cfg


@audio_bp.route("/v1/audio/transcriptions", methods=["POST"])
def transcriptions_proxy():
    """将 ASR 请求代理转发到配置的外部 STT 服务。"""
    try:
        client, cfg = _get_asr_client()
    except Exception as exc:
        current_app.logger.error("ASR客户端初始化失败: %s", exc)
        return jsonify({"error": f"ASR服务初始化失败: {exc}"}), 500

    endpoint = str(cfg.get("endpoint", "")).rstrip("/")
    path = str(cfg.get("path", "/audio/transcriptions"))
    api_key = str(cfg.get("api_key", ""))
    default_model = str(cfg.get("model_name", "qwen3-asr"))

    if not endpoint:
        return jsonify({"error": "ASR服务未配置（缺少 asr_proxy.endpoint）"}), 503

    target_url = endpoint + path

    # 重建 multipart 表单，允许前端覆盖 model/language
    if "file" not in request.files:
        return jsonify({"error": "缺少音频文件（file 字段）"}), 400

    audio_file = request.files["file"]
    model = request.form.get("model") or default_model
    language = request.form.get("language") or "zh"

    files = {"file": (audio_file.filename or "audio.wav", audio_file.stream, audio_file.mimetype or "audio/wav")}
    data = {"model": model, "language": language}

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = client.post(target_url, files=files, data=data, headers=headers)
        current_app.logger.info("ASR代理响应: status=%d url=%s", resp.status_code, target_url)
        return Response(resp.content, status=resp.status_code, content_type=resp.headers.get("content-type", "application/json"))
    except httpx.TimeoutException:
        current_app.logger.error("ASR请求超时: %s", target_url)
        return jsonify({"error": "ASR请求超时"}), 504
    except Exception as exc:
        current_app.logger.error("ASR代理失败: %s", exc, exc_info=True)
        return jsonify({"error": f"ASR请求失败: {exc}"}), 502
