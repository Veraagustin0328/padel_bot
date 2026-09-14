import os
from flask import Blueprint, request, jsonify
from app.llm.agent import procesar_mensaje, esta_pausado, _guardar_mensaje
from app.models import Notificacion

whatsapp_bp = Blueprint("whatsapp", __name__, url_prefix="/webhook")

MENSAJE_NO_AUDIO = (
    "Perdón amigo, todavía no puedo escuchar audios 😅 ¿me lo podés escribir? "
    "Así te ayudo al toque."
)


@whatsapp_bp.route("/whatsapp", methods=["POST"])
def recibir_mensaje():
    data = request.get_json(silent=True) or {}

    telefono = data.get("telefono")
    texto = data.get("texto")
    tipo = data.get("tipo", "texto")

    if not telefono:
        return jsonify({"error": "Falta 'telefono' en el body"}), 400

    if tipo == "audio":
        return jsonify({"respuesta": MENSAJE_NO_AUDIO}), 200

    if not texto:
        return jsonify({"error": "Falta 'texto' en el body"}), 400

    es_jefe = telefono == os.environ.get("ENCARGADO_TELEFONO")

    if not es_jefe and esta_pausado(telefono):
        _guardar_mensaje(telefono, "user", texto)
        return jsonify({"respuesta": None, "status": "bot_pausado_esperando_encargado"}), 200

    respuesta = procesar_mensaje(telefono, texto, es_jefe)

    return jsonify({"respuesta": respuesta}), 200


@whatsapp_bp.route("/notificaciones", methods=["GET"])
def ver_notificaciones():
    notifs = Notificacion.query.order_by(Notificacion.creado_en.desc()).limit(20).all()
    return jsonify([
        {"id": n.id, "tipo": n.tipo, "mensaje": n.mensaje, "creado_en": n.creado_en.isoformat()}
        for n in notifs
    ])