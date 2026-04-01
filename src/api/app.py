import os
from typing import Any, Dict, List, Union
from flask import Flask
from flask_cors import CORS

from src.api.routes.audio import audio_bp
from src.api.routes.chat import chat_bp
from src.api.routes.documents import documents_bp
from src.api.routes.ai_proxy import ai_proxy_bp
from src.api.routes.files import files_bp
from src.api.routes.storage import storage_bp
from src.api.routes.system import system_bp
from src.audio.services.media_store import MediaStore
from src.audio.services.speech_script_service import SpeechScriptService
from src.audio.services.tts_service import TTSService
from src.api.services.file_storage_service import UnifiedFileStorageService
from src.api.services.file_upload_session_service import (
    FileUploadSessionService,
    build_default_upload_temp_dir,
)
from src.core.factory import RAGFactory
from src.api.services.conversation_service import ConversationService
from src.api.services.rag_service import RAGService
from src.utils.config_loader import load_config


DEFAULT_CORS_ALLOW_HEADERS = [
    'Content-Type',
    'Authorization',
    'X-Knowledge-Scope',
    'X-RAG-Scope',
    'X-Scope',
]


def _resolve_cors_origins(config: Dict[str, Any]) -> Union[List[str], str]:
    cors_config = config.get('cors', {})
    configured_origins = cors_config.get('origins')
    env_origins = os.getenv('CORS_ORIGINS', '')

    if env_origins.strip():
        origins = [origin.strip() for origin in env_origins.split(',') if origin.strip()]
        return origins if origins else '*'

    if configured_origins:
        if isinstance(configured_origins, str):
            return configured_origins
        if isinstance(configured_origins, list):
            origins = [str(origin).strip() for origin in configured_origins if str(origin).strip()]
            return origins if origins else '*'

    return '*'


def _resolve_cors_allow_headers(config: Dict[str, Any]) -> List[str]:
    cors_config = config.get('cors', {})
    configured_headers = cors_config.get('allow_headers')

    merged_headers: List[str] = []
    seen = set()

    def _add(header: Any) -> None:
        normalized = str(header or '').strip()
        if not normalized:
            return
        lowered = normalized.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        merged_headers.append(normalized)

    for header in DEFAULT_CORS_ALLOW_HEADERS:
        _add(header)

    if isinstance(configured_headers, str):
        items = [item.strip() for item in configured_headers.split(',')]
        for item in items:
            _add(item)
    elif isinstance(configured_headers, list):
        for item in configured_headers:
            _add(item)

    return merged_headers


def create_app() -> Flask:
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    frontend_dist_dir = os.path.join(base_dir, 'src', 'api', 'static')

    app = Flask(__name__, static_folder=frontend_dist_dir, static_url_path='/')
    app.config['FRONTEND_DIST_DIR'] = frontend_dist_dir

    config = load_config()
    cors_config = config.get('cors', {})
    CORS(
        app,
        resources={r"/*": {"origins": _resolve_cors_origins(config)}},
        supports_credentials=bool(cors_config.get('supports_credentials', False)),
        allow_headers=_resolve_cors_allow_headers(config),
        methods=cors_config.get('methods', ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']),
    )

    app.extensions['rag_service'] = RAGService(logger=app.logger)
    conv_config = config.get('conversation', {})
    app.extensions['conversation_service'] = ConversationService(
        max_messages=conv_config.get('max_messages', 24),
        ttl_minutes=conv_config.get('ttl_minutes', 120),
    )

    storage_cfg = config.get('file_storage', {}) if isinstance(config.get('file_storage'), dict) else {}
    app.extensions['file_storage_service'] = UnifiedFileStorageService(
        config=storage_cfg,
        environment=str(config.get('environment', 'development')),
    )
    upload_temp_dir = str(
        storage_cfg.get('uploadTempDir')
        or storage_cfg.get('upload_temp_dir')
        or build_default_upload_temp_dir(storage_cfg.get('localRootDir') or storage_cfg.get('local_root_dir'))
    ).strip()
    app.extensions['file_upload_session_service'] = FileUploadSessionService(
        base_dir=upload_temp_dir,
        session_ttl_hours=int(storage_cfg.get('uploadSessionTtlHours') or storage_cfg.get('upload_session_ttl_hours') or 24),
        max_chunk_size_bytes=int(
            storage_cfg.get('chunkUploadSizeBytes')
            or storage_cfg.get('chunk_upload_size_bytes')
            or 8 * 1024 * 1024
        ),
    )

    audio_cfg = config.get('audio', {}) if isinstance(config.get('audio'), dict) else {}
    script_cfg = audio_cfg.get('script', {}) if isinstance(audio_cfg.get('script'), dict) else {}
    app.extensions['speech_script_service'] = SpeechScriptService(
        max_chars=script_cfg.get('max_chars', 1200),
    )

    tts_cfg = audio_cfg.get('tts', {}) if isinstance(audio_cfg.get('tts'), dict) else {}
    media_store = MediaStore(
        base_dir=tts_cfg.get('output_dir', './data/audio_cache'),
        public_base_path=tts_cfg.get('public_base_path', '/v1/audio/files'),
        ttl_hours=tts_cfg.get('cache_ttl_hours', 48),
        max_disk_mb=tts_cfg.get('cache_max_disk_mb', 2048),
    )
    tts_provider = RAGFactory.create_tts_provider(config)
    app.extensions['tts_service'] = TTSService(
        provider=tts_provider,
        media_store=media_store,
        provider_name=str(tts_cfg.get('provider', 'qwen')),
        default_model=str(tts_cfg.get('model', 'qwen3-tts-flash-2025-11-27')),
        default_voice=str(tts_cfg.get('default_voice', 'Cherry')),
        default_format=str(tts_cfg.get('default_format', 'mp3')),
        default_sample_rate=int(tts_cfg.get('default_sample_rate', 24000)),
        request_timeout=float(tts_cfg.get('request_timeout', 20.0)),
    )

    app.register_blueprint(system_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(storage_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(audio_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(ai_proxy_bp)

    return app
