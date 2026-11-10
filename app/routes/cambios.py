"""Cambios de días que esperan al encargado: listar, aprobar y rechazar (dueño y encargado).

La lógica está en app/cambios_dias.py. Acá además se le avisa al alumno por WhatsApp;
si el aviso falla, el cambio queda igual y el panel le dice al encargado que le escriba él.
"""
import logging

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from app import cambios_dias as cd
from app import recuperaciones
from app.extensions import db
from app.models import Alumno, CambioPendiente, Conversacion
from app.routes.auth import requiere_login
from app.whatsapp_client import enviar_mensaje_whatsapp

log = logging.getLogger(__name__)
cambios_bp = Blueprint("cambios_dias", __name__)


def _item(c: CambioPendiente, nombres: dict) -> dict:
    hoy = recuperaciones.hoy()
    actuales = cd.clases_del_alumno(c.alumno_id, hoy) if c.alumno_id else []
    cuota_actual, _ = cd.precio_de(actuales)
    return {
        "id": c.id,
        "alumno_id": c.alumno_id,
        "alumno": nombres.get(c.alumno_id) or c.alumno_telefono,
        "vigente_desde": c.vigente_desde.isoformat() if c.vigente_desde else None,
        "deja": [cd.texto_clase(x) for x in cd.clases_por_ids(cd.ids(c.clases_deja))],
        "nuevas": [cd.texto_clase(x) for x in cd.clases_por_ids(cd.ids(c.clases_nuevas))],
        "actuales": [cd.texto_clase(x) for x in actuales],
        "cuota_actual": cuota_actual,
        "cuota_nueva": c.precio_estimado,
        # si alguna clase nueva ya se llenó, aprobar va a fallar: lo mostramos antes
        "sin_lugar": [cd.texto_clase(x) for x in cd.sin_lugar(c)],
        "origen": c.origen,
        "espera": c.espera,
        "creado_en": c.creado_en.isoformat() + "Z" if c.creado_en else None,
    }


def _avisar_alumno(cambio: CambioPendiente, texto: str) -> bool:
    """Le escribe al alumno y lo deja en la charla, así el agente sabe qué se le dijo."""
    tel = cd.telefono_whatsapp(cambio)
    if not tel:
        return False
    try:
        r = enviar_mensaje_whatsapp(tel, texto)
    except Exception:
        log.exception("No pude avisarle por WhatsApp el cambio %s", cambio.id)
        return False
    if not isinstance(r, dict) or "error" in r:
        # fuera de las 24 hs desde su último mensaje Meta no deja mandar texto libre
        return False
    db.session.add(Conversacion(telefono=tel, rol="assistant", contenido=texto))
    db.session.commit()
    return True


@cambios_bp.get("/api/cambios-dias")
@requiere_login("encargado")
def listar():
    pendientes = (CambioPendiente.query.filter_by(tipo="cambio_dias", estado="pendiente")
                  .order_by(CambioPendiente.vigente_desde, CambioPendiente.creado_en).all())
    ids_ = {c.alumno_id for c in pendientes if c.alumno_id}
    nombres = {a.id: a.nombre for a in Alumno.query.filter(Alumno.id.in_(ids_))} if ids_ else {}
    items = [_item(c, nombres) for c in pendientes]
    para_mi = [x for x in items if x["espera"] != "alumno"]
    return jsonify({
        "pendientes": para_mi,
        "esperando_alumno": [x for x in items if x["espera"] == "alumno"],
        "total": len(para_mi),
    })


@cambios_bp.post("/api/cambios-dias/<int:cambio_id>/aprobar")
@requiere_login("encargado")
def aprobar(cambio_id):
    try:
        r = cd.aplicar(cambio_id, g.usuario.id)
    except cd.ErrorCambio as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 409
    except IntegrityError:  # otro lo anotó en esa clase justo ahora
        db.session.rollback()
        return jsonify({"error": "El alumno ya quedó anotado en esa clase recién: recargá y fijate"}), 409
    cambio = r["cambio"]
    alumno = db.session.get(Alumno, cambio.alumno_id)
    avisado = _avisar_alumno(cambio, cd.texto_aprobado(alumno, cambio, r["quedan"], r["cuota"]))
    avisos = [r["cuota"]["aviso"]] if r["cuota"].get("aviso") else []
    if not avisado:
        avisos.append("No le pude avisar por WhatsApp: escribile vos.")
    return jsonify({"ok": True, "cuota": r["cuota"], "avisado": avisado, "avisos": avisos})


@cambios_bp.post("/api/cambios-dias/<int:cambio_id>/rechazar")
@requiere_login("encargado")
def rechazar(cambio_id):
    datos = request.get_json(silent=True) or {}
    try:
        cambio = cd.rechazar(cambio_id, g.usuario.id, datos.get("motivo"))
    except cd.ErrorCambio as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 409
    alumno = db.session.get(Alumno, cambio.alumno_id) if cambio.alumno_id else None
    avisado = _avisar_alumno(cambio, cd.texto_rechazado(alumno, cambio))
    avisos = [] if avisado else ["No le pude avisar por WhatsApp: escribile vos."]
    return jsonify({"ok": True, "avisado": avisado, "avisos": avisos})
