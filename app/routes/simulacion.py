"""Rutas que existen SOLO en simulacion. create_app ni registra este blueprint en produccion."""
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from app import contactos, sim_registro
from app.extensions import db
from app.models import Alumno, ContactoAlumno, Conversacion
from app.routes.auth import requiere_login

simulacion_bp = Blueprint("simulacion", __name__)

# un numero que no es de nadie, para probar al desconocido
TEL_DESCONOCIDO = "5490000009999"


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


# ---------- simulador del agente (solo el dueño) ----------

def _encargado():
    return os.environ.get("ENCARGADO_TELEFONO", "").strip()


def _con_549(t10):
    # asi lo manda WhatsApp
    return "549" + t10 if len(t10) == 10 else t10


@simulacion_bp.get("/api/simulacion/telefonos")
@requiere_login("dueno")
def telefonos():
    """Los numeros para elegir: cada telefono con sus alumnos, mas el encargado y un desconocido."""
    por_tel = {}
    for c in ContactoAlumno.query.all():
        if len(c.tel10 or "") == 10:
            por_tel.setdefault(c.tel10, set()).add(c.alumno_id)
    for a in Alumno.query.all():
        t = contactos.tel10(a.telefono)
        if len(t) == 10:
            por_tel.setdefault(t, set()).add(a.id)
    nombres = {a.id: a.nombre for a in Alumno.query.all()}
    lista = []
    for t, ids in sorted(por_tel.items(), key=lambda x: (-len(x[1]), sorted(nombres.get(i, "") for i in x[1]))):
        quienes = sorted(nombres.get(i, "?") for i in ids)
        tipo = f"familia con {len(ids)} hijos" if len(ids) > 1 else "alumno"
        lista.append({"telefono": _con_549(t), "etiqueta": f"{', '.join(quienes)} ({tipo})",
                      "pausado": contactos.esta_pausado(t)})
    extra = [{"telefono": TEL_DESCONOCIDO, "etiqueta": "Desconocido (no es de nadie)", "pausado": False}]
    if _encargado():
        extra.insert(0, {"telefono": _encargado(), "etiqueta": "Encargado (modo jefe)", "pausado": False})
    return jsonify(extra + lista)


@simulacion_bp.get("/api/simulacion/charla")
@requiere_login("dueno")
def charla():
    tel = request.args.get("telefono", "")
    filas = (Conversacion.query.filter(Conversacion.telefono == tel)
             .order_by(Conversacion.id.desc()).limit(60).all())
    return jsonify({
        "mensajes": [{"rol": f.rol, "contenido": f.contenido,
                      "hora": f.creado_en.isoformat() + "Z" if f.creado_en else None} for f in reversed(filas)],
        "pausado": tel != _encargado() and contactos.esta_pausado(tel),
        "ultimo_envio": sim_registro.ultimo_id(),
    })


def _payload_meta(telefono, tipo, texto):
    """Lo que mandaria Meta al webhook. El id es unico para que no lo tome como repetido."""
    mensaje = {"from": telefono, "id": f"wamid.sim-{uuid.uuid4().hex}", "type": tipo}
    if tipo == "text":
        mensaje["text"] = {"body": texto}
    elif tipo in ("image", "document"):
        mensaje[tipo] = {"id": f"media-sim-{uuid.uuid4().hex[:8]}", "caption": texto,
                         **({"filename": "comprobante.pdf"} if tipo == "document" else {})}
    elif tipo == "audio":
        mensaje["audio"] = {"id": f"media-sim-{uuid.uuid4().hex[:8]}"}
    return {"entry": [{"changes": [{"value": {"messages": [mensaje]}}]}]}


@simulacion_bp.post("/api/simulacion/mensaje")
@requiere_login("dueno")
def mensaje():
    """Le habla al agente como si fuera WhatsApp: mismo camino que el webhook, sin pasar por Meta."""
    from app.routes.whatsapp import procesar_payload

    datos = request.get_json(silent=True) or {}
    tel = str(datos.get("telefono") or "").strip()
    tipo = datos.get("tipo") or "text"
    texto = str(datos.get("texto") or "")
    if not tel or tipo not in ("text", "image", "document", "audio"):
        return jsonify({"error": "Falta el teléfono o el tipo no existe"}), 400
    if tipo == "text" and not texto.strip():
        return jsonify({"error": "Escribí algo"}), 400

    desde = sim_registro.ultimo_id()
    sim_registro.empezar_traza()
    inicio = datetime.now(timezone.utc)
    try:
        resp = procesar_payload(_payload_meta(tel, tipo, texto))
        cuerpo = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
        error = None
    except Exception as e:  # que el simulador muestre el error en vez de un 500 mudo
        db.session.rollback()
        cuerpo, error = {}, f"{type(e).__name__}: {e}"
    traza = sim_registro.terminar_traza()
    enviados = sim_registro.bandeja(desde)
    return jsonify({
        "estado": cuerpo.get("status"),
        "error": error,
        "segundos": round((datetime.now(timezone.utc) - inicio).total_seconds(), 1),
        "respuestas": [m for m in enviados if m["telefono"] == tel],
        "otros_envios": [m for m in enviados if m["telefono"] != tel],
        "herramientas": traza,
        "pausado": tel != _encargado() and contactos.esta_pausado(tel),
    })


@simulacion_bp.post("/api/simulacion/pausa")
@requiere_login("dueno")
def pausa():
    """Pausar o reanudar el agente para un numero, como lo haria el encargado."""
    datos = request.get_json(silent=True) or {}
    tel = str(datos.get("telefono") or "")
    contactos.poner_modo(tel, "humano" if datos.get("pausar") else "bot")
    db.session.commit()
    return jsonify({"pausado": contactos.esta_pausado(tel)})


@simulacion_bp.get("/api/simulacion/bandeja")
@requiere_login("dueno")
def ver_bandeja():
    """WhatsApp que salieron por otro lado (ej: aprobar un cambio de dias desde el panel)."""
    return jsonify(sim_registro.bandeja(int(request.args.get("desde") or 0))[-50:])


@simulacion_bp.post("/api/simulacion/borrar-charla")
@requiere_login("dueno")
def borrar_charla():
    tel = str((request.get_json(silent=True) or {}).get("telefono") or "")
    Conversacion.query.filter(Conversacion.telefono == tel).delete()
    db.session.commit()
    return jsonify({"ok": True})
