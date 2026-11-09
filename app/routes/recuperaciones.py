"""Faltas, recuperaciones y viajes desde el panel. Todo para encargado (y admin).

La lógica de las reglas vive en app/recuperaciones.py; acá solo se lee el pedido,
se llama y se responde. Lo que se sale de la regla queda pendiente para aprobar.
"""
import json
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request

from app import models_academia as m
from app import recuperaciones as r
from app.extensions import db
from app.models import Alumno
from app.routes.auth import requiere_login

recuperaciones_bp = Blueprint("recuperaciones", __name__)

DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
ESTADOS_RECU = ("confirmada", "pendiente", "rechazada", "cancelada")


# ---------- helpers ----------

def _error(texto, codigo=400):
    return jsonify({"error": texto}), codigo


def _int(valor):
    try:
        return int(valor or 0) or None
    except (TypeError, ValueError):
        return None


def _fecha(valor, nombre="fecha"):
    try:
        return date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        raise r.ErrorRegla(f"La {nombre} tiene que ser AAAA-MM-DD")


def _mes_pedido():
    """?mes=AAAA-MM; por defecto el mes de hoy (hora argentina). Devuelve (desde, hasta exclusive)."""
    texto = request.args.get("mes")
    try:
        anio, mes = (int(x) for x in texto.split("-")) if texto else (r.hoy().year, r.hoy().month)
        desde = date(anio, mes, 1)
    except (TypeError, ValueError):
        raise r.ErrorRegla("El mes tiene que ser AAAA-MM")
    hasta = date(anio + (mes == 12), mes % 12 + 1, 1)
    return desde, hasta


def _nombres(ids):
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.session.query(Alumno.id, Alumno.nombre).filter(Alumno.id.in_(ids)).all())


def _clases(ids):
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {c.id: f"{DIAS[c.dia_semana]} {c.hora_inicio:%H:%M}" for c in m.Clase.query.filter(m.Clase.id.in_(ids))}


def _hora_utc(dt):
    return dt.isoformat() + "Z" if dt else None


def _auditar(entidad, entidad_id, accion, antes=None, despues=None):
    db.session.add(m.Auditoria(
        entidad=entidad, entidad_id=entidad_id, accion=accion, usuario_id=g.usuario.id,
        antes=json.dumps(antes, ensure_ascii=False) if antes is not None else None,
        despues=json.dumps(despues, ensure_ascii=False) if despues is not None else None,
    ))


def _json_ausencias(filas):
    recus = {}
    if filas:
        for x in m.RecuperacionClase.query.filter(
                m.RecuperacionClase.ausencia_id.in_([a.id for a in filas]),
                m.RecuperacionClase.estado.in_(r.ACTIVAS)):
            recus[x.ausencia_id] = x
    nombres = _nombres(a.alumno_id for a in filas)
    clases = _clases([a.clase_id for a in filas] + [x.clase_id for x in recus.values()])
    salida = []
    for a in filas:
        x = recus.get(a.id)
        salida.append({
            "id": a.id,
            "alumno_id": a.alumno_id,
            "alumno": nombres.get(a.alumno_id, "?"),
            "clase_id": a.clase_id,
            "clase": clases.get(a.clase_id, ""),
            "fecha": a.fecha.isoformat(),
            "origen": a.origen,
            "motivo": a.motivo or "",
            "avisada_en": _hora_utc(a.avisada_en),
            "a_tiempo": bool(a.a_tiempo),
            "recuperacion": {"id": x.id, "estado": x.estado, "fecha": x.fecha.isoformat(),
                             "clase": clases.get(x.clase_id, "")} if x else None,
        })
    return salida


def _json_recus(filas):
    nombres = _nombres(x.alumno_id for x in filas)
    clases = _clases(x.clase_id for x in filas)
    faltas = {}
    ids_aus = [x.ausencia_id for x in filas if x.ausencia_id]
    if ids_aus:
        faltas = {a.id: a for a in m.Ausencia.query.filter(m.Ausencia.id.in_(ids_aus))}
    salida = []
    for x in filas:
        a = faltas.get(x.ausencia_id)
        salida.append({
            "id": x.id,
            "alumno_id": x.alumno_id,
            "alumno": nombres.get(x.alumno_id, "?"),
            "clase_id": x.clase_id,
            "clase": clases.get(x.clase_id, ""),
            "fecha": x.fecha.isoformat(),
            "estado": x.estado,
            "fuera_de_regla": x.fuera_de_regla or "",
            "pedida_por": x.pedida_por,
            "falta": {"id": a.id, "fecha": a.fecha.isoformat(), "a_tiempo": bool(a.a_tiempo)} if a else None,
            "creada_en": _hora_utc(x.creada_en),
            "resuelta_en": _hora_utc(x.resuelta_en),
        })
    return salida


def _json_lapsos(filas):
    nombres = _nombres([l.alumno_id for l in filas] + [l.reemplazo_alumno_id for l in filas])
    clases = _clases(l.clase_id for l in filas)
    return [{
        "id": l.id,
        "alumno_id": l.alumno_id,
        "alumno": nombres.get(l.alumno_id, "?"),
        "clase_id": l.clase_id,
        "clase": clases.get(l.clase_id, "Todas sus clases") if l.clase_id else "Todas sus clases",
        "desde": l.desde.isoformat(),
        "hasta": l.hasta.isoformat(),
        "motivo": l.motivo or "",
        "reemplazo_alumno_id": l.reemplazo_alumno_id,
        "reemplazo": nombres.get(l.reemplazo_alumno_id, "") if l.reemplazo_alumno_id else "",
        "estado": l.estado,
        "origen": l.origen,
    } for l in filas]


@recuperaciones_bp.errorhandler(r.ErrorRegla)
def _regla_rota(e):
    db.session.rollback()
    return _error(str(e))


# ---------- reglas ----------

@recuperaciones_bp.get("/api/recuperaciones/reglas")
@requiere_login("encargado")
def reglas():
    return jsonify({k: r.regla(k) for k in r.REGLAS_DEFAULT})


# ---------- faltas ----------

@recuperaciones_bp.get("/api/ausencias")
@requiere_login("encargado")
def listar_ausencias():
    desde, hasta = _mes_pedido()
    q = m.Ausencia.query.filter(m.Ausencia.fecha >= desde, m.Ausencia.fecha < hasta)
    alumno_id = _int(request.args.get("alumno_id"))
    if alumno_id:
        q = q.filter(m.Ausencia.alumno_id == alumno_id)
    return jsonify(_json_ausencias(q.order_by(m.Ausencia.fecha, m.Ausencia.id).all()))


@recuperaciones_bp.post("/api/ausencias")
@requiere_login("encargado")
def crear_ausencia():
    datos = request.get_json(silent=True) or {}
    avisada_en = None
    if datos.get("avisada_en"):
        try:
            # si viene sin zona se toma como hora argentina
            avisada_en = r.utc_naive(datetime.fromisoformat(str(datos["avisada_en"]).replace("Z", "+00:00")))
        except ValueError:
            return _error("La hora del aviso no es válida")
    a_tiempo = datos.get("a_tiempo")
    aus, nueva = r.avisar_ausencia(
        _int(datos.get("alumno_id")), _int(datos.get("clase_id")), _fecha(datos.get("fecha")),
        origen="encargado", motivo=datos.get("motivo"), avisada_en=avisada_en,
        a_tiempo=None if a_tiempo is None else bool(a_tiempo),
    )
    if not nueva:
        return _error("Esa falta ya estaba cargada", 409)
    db.session.commit()
    return jsonify(_json_ausencias([aus])[0]), 201


@recuperaciones_bp.patch("/api/ausencias/<int:id_>")
@requiere_login("encargado")
def editar_ausencia(id_):
    aus = db.session.get(m.Ausencia, id_)
    if not aus:
        return _error("No encontré esa falta", 404)
    datos = request.get_json(silent=True) or {}
    antes = {"a_tiempo": aus.a_tiempo, "motivo": aus.motivo}
    if "a_tiempo" in datos:
        aus.a_tiempo = bool(datos["a_tiempo"])
    if "motivo" in datos:
        aus.motivo = (str(datos["motivo"] or "").strip()[:255]) or None
    _auditar("ausencia", aus.id, "editar", antes, {"a_tiempo": aus.a_tiempo, "motivo": aus.motivo})
    db.session.commit()
    return jsonify(_json_ausencias([aus])[0])


@recuperaciones_bp.delete("/api/ausencias/<int:id_>")
@requiere_login("encargado")
def borrar_ausencia(id_):
    aus = db.session.get(m.Ausencia, id_)
    if not aus:
        return _error("No encontré esa falta", 404)
    if r.recuperacion_activa(aus.id):
        return _error("Esa falta tiene una recuperación activa. Cancelala primero")
    _auditar("ausencia", aus.id, "borrar", {"alumno_id": aus.alumno_id, "clase_id": aus.clase_id,
                                           "fecha": aus.fecha.isoformat(), "origen": aus.origen})
    db.session.delete(aus)
    db.session.commit()
    return jsonify({"ok": True, "id": id_})


# ---------- recuperaciones ----------

@recuperaciones_bp.get("/api/recuperaciones")
@requiere_login("encargado")
def listar_recuperaciones():
    q = m.RecuperacionClase.query
    estado = request.args.get("estado")
    if estado:
        if estado not in ESTADOS_RECU:
            return _error("Estado inválido")
        q = q.filter(m.RecuperacionClase.estado == estado)
    # las pendientes se ven todas; el resto, por mes
    if estado != "pendiente" or request.args.get("mes"):
        desde, hasta = _mes_pedido()
        q = q.filter(m.RecuperacionClase.fecha >= desde, m.RecuperacionClase.fecha < hasta)
    filas = q.order_by(m.RecuperacionClase.fecha, m.RecuperacionClase.id).all()
    return jsonify(_json_recus(filas))


@recuperaciones_bp.post("/api/recuperaciones")
@requiere_login("encargado")
def crear_recuperacion():
    datos = request.get_json(silent=True) or {}
    recu = r.pedir_recuperacion(
        _int(datos.get("alumno_id")), _int(datos.get("clase_id")), _fecha(datos.get("fecha")),
        ausencia_id=_int(datos.get("ausencia_id")), pedida_por="encargado",
        forzar=bool(datos.get("forzar")), usuario_id=g.usuario.id,
    )
    db.session.commit()
    return jsonify(_json_recus([recu])[0]), 201


@recuperaciones_bp.post("/api/recuperaciones/<int:id_>/resolver")
@requiere_login("encargado")
def resolver_recuperacion(id_):
    datos = request.get_json(silent=True) or {}
    if "aprobar" not in datos:
        return _error("Decime si la aprobás o la rechazás")
    recu = r.resolver_recuperacion(id_, bool(datos["aprobar"]), g.usuario.id, forzar=bool(datos.get("forzar")))
    _auditar("recuperacion", recu.id, "aprobar" if recu.estado == "confirmada" else "rechazar")
    db.session.commit()
    return jsonify(_json_recus([recu])[0])


@recuperaciones_bp.post("/api/recuperaciones/<int:id_>/cancelar")
@requiere_login("encargado")
def cancelar_recuperacion(id_):
    recu = r.cancelar_recuperacion(id_, g.usuario.id)
    _auditar("recuperacion", recu.id, "cancelar")
    db.session.commit()
    return jsonify(_json_recus([recu])[0])


# ---------- viajes ----------

@recuperaciones_bp.get("/api/lapsos")
@requiere_login("encargado")
def listar_lapsos():
    q = m.AusenciaLapso.query.filter(m.AusenciaLapso.estado != "cancelado")
    # por defecto los que siguen vigentes o están por venir
    if request.args.get("todos") != "1":
        q = q.filter(m.AusenciaLapso.hasta >= r.hoy())
    return jsonify(_json_lapsos(q.order_by(m.AusenciaLapso.desde, m.AusenciaLapso.id).all()))


@recuperaciones_bp.post("/api/lapsos")
@requiere_login("encargado")
def crear_lapso():
    datos = request.get_json(silent=True) or {}
    lap = r.crear_lapso(
        _int(datos.get("alumno_id")), _fecha(datos.get("desde"), "fecha de ida"),
        _fecha(datos.get("hasta"), "fecha de vuelta"), motivo=datos.get("motivo"),
        reemplazo_alumno_id=_int(datos.get("reemplazo_alumno_id")), clase_id=_int(datos.get("clase_id")),
        origen="encargado", usuario_id=g.usuario.id,
    )
    db.session.commit()
    return jsonify(_json_lapsos([lap])[0]), 201


@recuperaciones_bp.post("/api/lapsos/<int:id_>/confirmar")
@requiere_login("encargado")
def confirmar_lapso(id_):
    lap = r.confirmar_lapso(id_)
    _auditar("lapso", lap.id, "confirmar")
    db.session.commit()
    return jsonify(_json_lapsos([lap])[0])


@recuperaciones_bp.delete("/api/lapsos/<int:id_>")
@requiere_login("encargado")
def cancelar_lapso(id_):
    lap = r.cancelar_lapso(id_)
    _auditar("lapso", lap.id, "cancelar")
    db.session.commit()
    return jsonify({"ok": True, "id": id_})
