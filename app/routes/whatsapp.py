import os
from flask import Blueprint, request, jsonify
from app.llm.agent import (
    procesar_mensaje, esta_pausado, _guardar_mensaje, _montos_en, _pesos, _notificar,
    _alumno_del_pago, _nombres, _pregunta_de_quien,
)
from app.models import Notificacion
from app.whatsapp_client import enviar_mensaje_whatsapp, reenviar_archivo_whatsapp
from app import planilla
from app.extensions import db
from app.routes.auth import requiere_login
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


def _monto_del_texto(texto: str):
    """El monto que vino escrito con la foto o el PDF. Si hay más de uno no elijo: queda vacío."""
    montos = _montos_en(texto)
    return montos[0] if len(montos) == 1 else None


def _recibir_comprobante(telefono: str, data: dict, tipo: str):
    """Foto o PDF del comprobante: lo anota como PENDIENTE en la pestaña comprobantes
    (avisar_comprobante no duplica si ya hay uno pendiente del mes) y se lo reenvía al encargado."""
    mensaje = data["entry"][0]["changes"][0]["value"]["messages"][0]
    archivo = mensaje.get(tipo, {})
    media_id = archivo.get("id")
    texto = (archivo.get("caption") or "").strip()
    monto = _monto_del_texto(texto)
    varios_montos = monto is None and bool(_montos_en(texto))

    # si el número es de varios hijos, cada uno tiene su comprobante (nombre None = falta saber de quién)
    alumnos, de_quien = _alumno_del_pago(telefono, texto)
    varios = len(alumnos) > 1
    if varios:
        nombre = de_quien or ""
    else:
        nombre = alumnos[0].nombre if alumnos else ""
    anotado = None  # monto que quedó en la planilla
    planilla_ok = False
    try:
        # como texto entero, igual que _responder_pago: _a_numero lee "45000.0" como 450000
        monto_txt = str(int(monto)) if monto else None
        if varios:
            r = planilla.avisar_comprobante(telefono, monto_txt, alumno=de_quien, por_alumno=True, es_foto=True)
            nombre = r.get("alumno") or ""  # puede ser el de un aviso de recién
        else:
            vinculo = planilla._vinculo(telefono)
            nombre = (vinculo or {}).get("ALUMNO", "") or nombre
            r = planilla.avisar_comprobante(telefono, monto_txt)
        anotado = r.get("monto_anotado")
        planilla_ok = bool(r.get("ok"))
    except Exception as e:
        print(f"[comprobante] error con la planilla: {e!r}", flush=True)
    falta_quien = varios and not nombre
    if falta_quien:
        nombre = f"{_nombres(alumnos)} (falta saber de quién)"

    if not planilla_ok:
        # que no se pierda: le queda el aviso al encargado en el panel
        mes = planilla.MESES[planilla._ahora().month - 1].capitalize()
        _notificar(f"Comprobante de {nombre or telefono} ({telefono}), {mes}, monto: "
                   f"{_pesos(monto) if monto else 'sin detectar'}. No se pudo anotar en la "
                   "planilla: cargalo a mano en la pestaña comprobantes.", tipo="comprobante",
                   telefono=telefono, tema="comprobante")

    encargado = os.environ.get("ENCARGADO_TELEFONO", "").strip()
    if encargado and media_id:
        try:
            reenviar_archivo_whatsapp(
                encargado, tipo, media_id,
                f"Comprobante de {nombre or telefono}", archivo.get("filename"))
        except Exception as e:
            print(f"[comprobante] no pude reenviar al encargado: {e!r}", flush=True)

    respuesta = "Recibí tu comprobante, gracias. El encargado lo revisa y te confirma el pago."
    if varios_montos:
        respuesta += " Vi más de un monto en tu mensaje: decime cuánto fue lo que transferiste así lo anoto."
    elif planilla_ok and anotado is not None:
        respuesta = (f"Recibí tu comprobante, gracias. Anoté {_pesos(anotado)}. "
                     "El encargado lo revisa y te confirma el pago.")
    elif planilla_ok:
        respuesta += " Decime también cuánto fue así lo anoto."
    if planilla_ok and falta_quien:
        respuesta += " " + _pregunta_de_quien(alumnos)
    _guardar_mensaje(telefono, "user", "[envió el comprobante de pago]" + (f" {texto}" if texto else ""))
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
@requiere_login("encargado")
def ver_notificaciones():
    notifs = Notificacion.query.order_by(Notificacion.creado_en.desc()).limit(20).all()
    return jsonify([
        {"id": n.id, "tipo": n.tipo, "mensaje": n.mensaje, "creado_en": n.creado_en.isoformat()}
        for n in notifs
    ])