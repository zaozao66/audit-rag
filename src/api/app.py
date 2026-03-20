import os
from typing import Any, Dict, List, Union
from flask import Flask
from flask_cors import CORS

from src.api.routes.chat import chat_bp
from src.api.routes.documents import documents_bp
from src.api.routes.storage import storage_bp
from src.api.routes.system import system_bp
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
    frontend_dist_dir = os.path.join(base_dir, 'frontend', 'dist')

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

    app.register_blueprint(system_bp)
    app.register_blueprint(storage_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(documents_bp)

    return app
