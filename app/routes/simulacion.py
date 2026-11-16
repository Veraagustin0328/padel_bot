"""Rutas que existen SOLO en simulacion. create_app ni registra este blueprint en produccion."""
from datetime import datetime, timezone
from urllib.parse import urlparse
import os

from flask import Blueprint, jsonify

simulacion_bp = Blueprint("simulacion", __name__)


@simulacion_bp.get("/api/simulacion/estado")
def estado():
    # sin login: el cartel se ve tambien en la pantalla de entrada
    host = urlparse(os.environ.get("DATABASE_URL", "")).hostname or "local"
    return jsonify({
        "simulacion": True,
        # con el reloj simulado esta hora es la de mentira; el panel la usa para "hoy"
        "ahora": datetime.now(timezone.utc).isoformat(),
        "base": host.split(".")[0],
    })
