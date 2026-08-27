from flask import Blueprint, request, jsonify
from app.llm.agent import procesar_mensaje

whatsapp_bp = Blueprint("whatsapp", __name__, url_prefix="/webhook")


@whatsapp_bp.route("/whatsapp", methods=["POST"])
def recibir_mensaje():
    data = request.get_json(silent=True) or {}

    telefono = data.get("telefono")
    texto = data.get("texto")

    if not telefono or not texto:
        return jsonify({"error": "Faltan 'telefono' o 'texto' en el body"}), 400

    respuesta = procesar_mensaje(telefono, texto)

    return jsonify({"respuesta": respuesta}), 200