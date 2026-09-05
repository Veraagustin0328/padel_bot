import os
from flask import Blueprint, request, jsonify
from app.llm.agent import procesar_mensaje

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
    tipo = data.get("tipo", "texto")  # "texto" o "audio", simulado por ahora

    if not telefono:
        return jsonify({"error": "Falta 'telefono' en el body"}), 400

    if tipo == "audio":
        return jsonify({"respuesta": MENSAJE_NO_AUDIO}), 200

    if not texto:
        return jsonify({"error": "Falta 'texto' en el body"}), 400

    es_jefe = telefono == os.environ.get("ENCARGADO_TELEFONO")
    respuesta = procesar_mensaje(telefono, texto, es_jefe)

    return jsonify({"respuesta": respuesta}), 200