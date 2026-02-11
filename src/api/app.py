import os
from flask import Flask

from src.api.routes.chat import chat_bp
from src.api.routes.documents import documents_bp
from src.api.routes.storage import storage_bp
from src.api.routes.system import system_bp
from src.api.services.rag_service import RAGService


def create_app() -> Flask:
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    frontend_dist_dir = os.path.join(base_dir, 'frontend', 'dist')

    app = Flask(__name__, static_folder=frontend_dist_dir, static_url_path='/')
    app.config['FRONTEND_DIST_DIR'] = frontend_dist_dir

    app.extensions['rag_service'] = RAGService(logger=app.logger)

    app.register_blueprint(system_bp)
    app.register_blueprint(storage_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(documents_bp)

    return app
