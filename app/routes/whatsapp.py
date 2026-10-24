import os
from flask import Blueprint, request, jsonify
from app.llm.agent import procesar_mensaje, esta_pausado, _guardar_mensaje
from app.models import Notificacion
from app.whatsapp_client import enviar_mensaje_whatsapp, reenviar_archivo_whatsapp
from app import planilla
from app.extensions import db
from sqlalchemy import text

whatsapp_bp = Blueprint("whatsapp", __name__, url_prefix="/webhook")

MENSAJE_NO_AUDIO = (
    "Perdón amigo, todavía no puedo escuchar audios 😅 ¿me lo podés escribir? "
    "Así te ayudo al toque."
)


@whatsapp_bp.route("/whatsapp", methods=["GET"])
def verificar_webhook():
    modo = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if modo == "subscribe" and token == os.environ.get("WHATSAPP_VERIFY_TOKEN"):
        return challenge, 200
    return "Token inválido", 403


@whatsapp_bp.route("/whatsapp", methods=["POST"])
def recibir_mensaje():
    data = request.get_json(silent=True) or {}

    telefono, texto, tipo = _parsear_mensaje_meta(data)

    if not telefono:
        return jsonify({"status": "ignorado"}), 200

    # Meta reenvía el mismo mensaje si tardamos en contestar: lo procesamos una sola vez
    if not _primera_vez(_id_mensaje(data)):
        print("[webhook] mensaje repetido, lo ignoro", flush=True)
        return jsonify({"status": "duplicado"}), 200

    es_jefe = telefono == os.environ.get("ENCARGADO_TELEFONO")

    if tipo == "audio":
        enviar_mensaje_whatsapp(telefono, MENSAJE_NO_AUDIO)
        return jsonify({"status": "ok"}), 200

    if tipo in ("image", "document"):
        if es_jefe:
            return jsonify({"status": "ignorado"}), 200
        return _recibir_comprobante(telefono, data, tipo)

    if not texto:
        return jsonify({"status": "ignorado"}), 200

    if not es_jefe and esta_pausado(telefono):
        _guardar_mensaje(telefono, "user", texto)
        return jsonify({"status": "bot_pausado_esperando_encargado"}), 200

    respuesta = procesar_mensaje(telefono, texto, es_jefe)
    enviar_mensaje_whatsapp(telefono, respuesta)

    return jsonify({"status": "ok"}), 200


def _recibir_comprobante(telefono: str, data: dict, tipo: str):
    """Foto o PDF del comprobante: lo anota como pendiente y se lo reenvía al encargado."""
    mensaje = data["entry"][0]["changes"][0]["value"]["messages"][0]
    archivo = mensaje.get(tipo, {})
    media_id = archivo.get("id")

    nombre = ""
    sin_monto = True
    try:
        vinculo = planilla._vinculo(telefono)
        nombre = (vinculo or {}).get("ALUMNO", "")
        r = planilla.avisar_comprobante(telefono, None)  # si no había uno pendiente, lo deja creado
        sin_monto = r.get("monto_anotado") is None
    except Exception as e:
        print(f"[comprobante] error con la planilla: {e!r}", flush=True)

    encargado = os.environ.get("ENCARGADO_TELEFONO", "").strip()
    if encargado and media_id:
        try:
            reenviar_archivo_whatsapp(
                encargado, tipo, media_id,
                f"Comprobante de {nombre or telefono}", archivo.get("filename"))
        except Exception as e:
            print(f"[comprobante] no pude reenviar al encargado: {e!r}", flush=True)

    respuesta = "Recibí tu comprobante, gracias. El encargado lo revisa y te confirma el pago."
    if sin_monto:
        respuesta += " Decime también cuánto fue así lo anoto."
    _guardar_mensaje(telefono, "user", "[envió el comprobante de pago]")
    _guardar_mensaje(telefono, "assistant", respuesta)
    enviar_mensaje_whatsapp(telefono, respuesta)
    return jsonify({"status": "ok"}), 200


_tabla_lista = False


def _id_mensaje(data: dict):
    try:
        return data["entry"][0]["changes"][0]["value"]["messages"][0].get("id")
    except (KeyError, IndexError):
        return None


def _primera_vez(wamid) -> bool:
    """True si es la primera vez que vemos este mensaje de WhatsApp."""
    global _tabla_lista
    if not wamid:
        return True
    try:
        if not _tabla_lista:
            db.session.execute(text(
                "CREATE TABLE IF NOT EXISTS mensajes_procesados ("
                "wamid TEXT PRIMARY KEY, creado_en TIMESTAMP DEFAULT NOW())"))
            db.session.commit()
            _tabla_lista = True
        r = db.session.execute(
            text("INSERT INTO mensajes_procesados (wamid) VALUES (:w) "
                 "ON CONFLICT (wamid) DO NOTHING"),
            {"w": wamid})
        db.session.commit()
        return r.rowcount == 1
    except Exception as e:
        db.session.rollback()
        print(f"[webhook] no pude chequear duplicados: {e!r}", flush=True)
        return True


def _parsear_mensaje_meta(data: dict):
    """Devuelve (telefono, texto, tipo) o (None, None, None) si no es un mensaje real."""
    try:
        mensaje = data["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError):
        return None, None, None

    telefono = mensaje.get("from")
    tipo = mensaje.get("type")

    if tipo == "text":
        texto = mensaje.get("text", {}).get("body")
        return telefono, texto, tipo
    elif tipo == "audio":
        return telefono, None, "audio"

    return telefono, None, tipo


@whatsapp_bp.route("/notificaciones", methods=["GET"])
def ver_notificaciones():
    notifs = Notificacion.query.order_by(Notificacion.creado_en.desc()).limit(20).all()
    return jsonify([
        {"id": n.id, "tipo": n.tipo, "mensaje": n.mensaje, "creado_en": n.creado_en.isoformat()}
        for n in notifs
    ])