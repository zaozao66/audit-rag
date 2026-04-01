import mimetypes
import os
from typing import Any, Dict

from flask import Blueprint, Response, current_app, jsonify, request, send_file

from src.api.routes.scope_utils import extract_scope_from_request
from src.audio.services.speech_script_service import SpeechScriptService
from src.audio.services.tts_service import TTSService


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


@audio_bp.route("/v1/audio/transcriptions", methods=["POST"])
def transcriptions_placeholder():
    return jsonify({
        "error": "STT接口已预留，当前版本暂未启用"
    }), 501
