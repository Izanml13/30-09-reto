"""Fabrica de la aplicacion Flask (patron Application Factory)."""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from app.config import BASE_DIR, config

WEB_DIR = BASE_DIR / "web"


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["STT_CONFIG"] = config
    app.config["MAX_CONTENT_LENGTH"] = config.max_upload_bytes
    if overrides:
        app.config.update(overrides)

    logging.basicConfig(
        level=logging.DEBUG if config.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    # -- Blueprints -------------------------------------------------------
    from app.routes.api import api

    app.register_blueprint(api)

    # -- Interfaz web -----------------------------------------------------
    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        if not Path(WEB_DIR, filename).is_file():
            return jsonify({"error": "no_encontrado", "ruta": filename}), 404
        return send_from_directory(WEB_DIR, filename)

    # -- Manejadores de error --------------------------------------------
    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "no_encontrado"}), 404

    @app.errorhandler(413)
    def too_large(_):
        return (
            jsonify(
                {
                    "error": "peticion_demasiado_grande",
                    "detalle": f"El fichero supera el limite de {config.max_upload_mb} MB.",
                }
            ),
            413,
        )

    @app.errorhandler(500)
    def server_error(exc):  # pragma: no cover
        return jsonify({"error": "error_interno", "detalle": str(exc)}), 500

    return app
