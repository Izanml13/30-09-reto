#!/usr/bin/env python
"""
Punto de entrada del servidor.

    python run.py                -> arranca en 127.0.0.1:5000
    STT_PORT=8000 python run.py  -> cambia el puerto
"""
from app.config import config
from app.main import create_app

app = create_app()

if __name__ == "__main__":
    print("=" * 62)
    print(" ASIX Speech-to-Text API")
    print(f" Interfaz  : http://{config.host}:{config.port}/")
    print(f" Salud     : http://{config.host}:{config.port}/api/health")
    print(f" Gemini    : {'configurado' if config.has_gemini_key else 'SIN API KEY -> fallback mock'}")
    print("=" * 62)
    app.run(host=config.host, port=config.port, debug=config.debug)
