from flask import Blueprint, request, jsonify

whatsapp_bp = Blueprint("whatsapp", __name__, url_prefix="/webhook")


@whatsapp_bp.route("/whatsapp", methods=["POST"])
def recibir_mensaje():
    data = request.get_json(silent=True) or {}

    telefono = data.get("telefono")
    texto = data.get("texto")

    if not telefono or not texto:
        return jsonify({"error": "Faltan 'telefono' o 'texto' en el body"}), 400

    # Por ahora, respuesta fija -- después acá va la lógica del LLM
    respuesta = f"Recibí tu mensaje: '{texto}'. Todavía no tengo el agente conectado."

    return jsonify({"respuesta": respuesta}), 200