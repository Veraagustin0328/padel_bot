"""Mis clases: el profe ve sus clases y marca asistencia. Encargado y admin ven todas.

La asistencia cuelga de ClaseDictada (una por clase + fecha), así que marcar
un alumno deja registrada la clase de ese día.
"""
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app import models_academia as m
from app import recuperaciones
from app.extensions import db
from app.models import Alumno
from app.models_plataforma import Profesor
from app.routes.auth import requiere_login

asistencia_bp = Blueprint("asistencia", __name__)

GESTION = ("admin", "encargado")


def _hoy():
    # misma hora que usa planilla.py (Argentina, UTC-3)
    return datetime.now(timezone(timedelta(hours=-3))).date()


def _sin_profe():
    """Un profe sin profesor_id no tiene clases propias: no ve nada."""
    return g.usuario.rol not in GESTION and not g.usuario.profesor_id


def _puede(clase):
    if g.usuario.rol in GESTION:
        return True
    return bool(g.usuario.profesor_id) and clase.profesor_id == g.usuario.profesor_id


def _clase_o_error(clase_id):
    """Devuelve (clase, None) o (None, respuesta de error)."""
    if _sin_profe():
        return None, (jsonify({"error": "Tu usuario no está vinculado a un profe"}), 403)
    clase = db.session.get(m.Clase, clase_id)
    if not clase:
        return None, (jsonify({"error": "No encontré la clase"}), 404)
    if not _puede(clase):
        return None, (jsonify({"error": "Esa clase no es tuya"}), 403)
    return clase, None


def _leer_fecha(texto, clase):
    """Devuelve (fecha, None) o (None, mensaje de error)."""
    if texto:
        try:
            fecha = date.fromisoformat(str(texto))
        except ValueError:
            return None, "La fecha tiene que ser AAAA-MM-DD"
    else:
        fecha = _hoy()
    if fecha.weekday() != clase.dia_semana:
        return None, "Esa clase no se da ese día"
    if fecha > _hoy():
        return None, "Todavía no llegó esa fecha"
    return fecha, None


def _alumnos_del_dia(clase, fecha):
    """Anotados ese día + los que recuperan ahí. {alumno_id: recupera}"""
    ids = {}
    anotados = db.session.query(m.Inscripcion.alumno_id).filter(
        m.Inscripcion.clase_id == clase.id,
        m.Inscripcion.desde <= fecha,
        or_(m.Inscripcion.hasta.is_(None), m.Inscripcion.hasta > fecha),
    )
    for (aid,) in anotados:
        ids[aid] = False
    recuperan = db.session.query(m.RecuperacionClase.alumno_id).filter_by(
        clase_id=clase.id, fecha=fecha, estado="confirmada"
    )
    for (aid,) in recuperan:
        ids.setdefault(aid, True)
    return ids


def _dictada(clase, fecha):
    return m.ClaseDictada.query.filter_by(clase_id=clase.id, fecha=fecha).first()


@asistencia_bp.get("/api/mis-clases")
@requiere_login("profe", "encargado")
def mis_clases():
    if _sin_profe():
        return jsonify({"error": "Tu usuario no está vinculado a un profe"}), 403

    consulta = (
        db.session.query(m.Clase, Profesor.nombre)
        .outerjoin(Profesor, m.Clase.profesor_id == Profesor.id)
        .filter(m.Clase.activa.is_(True))
    )
    if g.usuario.rol not in GESTION:
        consulta = consulta.filter(m.Clase.profesor_id == g.usuario.profesor_id)

    cuentas = {}
    for (cid,) in db.session.query(m.Inscripcion.clase_id).filter(m.Inscripcion.hasta.is_(None)):
        cuentas[cid] = cuentas.get(cid, 0) + 1

    # recuperaciones confirmadas de la última semana (lo que muestra el panel), por clase y fecha
    hoy = _hoy()
    recuperan = {}
    filas = db.session.query(m.RecuperacionClase.clase_id, m.RecuperacionClase.fecha).filter(
        m.RecuperacionClase.estado == "confirmada",
        m.RecuperacionClase.fecha >= hoy - timedelta(days=6),
        m.RecuperacionClase.fecha <= hoy,
    )
    for cid, fecha in filas:
        dia = recuperan.setdefault(cid, {})
        dia[fecha.isoformat()] = dia.get(fecha.isoformat(), 0) + 1

    salida = [{
        "id": c.id,
        "dia": c.dia_semana,
        "hora": c.hora_inicio.strftime("%H:%M"),
        "duracion": c.duracion_min,
        "profe": profe or "",
        "tipo": c.tipo,
        "nivel": c.nivel or "",
        "ambito": c.ambito,
        "alumnos": cuentas.get(c.id, 0),
        "recuperan": recuperan.get(c.id, {}),
    } for c, profe in consulta]
    salida.sort(key=lambda x: (x["dia"], x["hora"], x["profe"]))
    return jsonify({"hoy": hoy.isoformat(), "clases": salida})


@asistencia_bp.get("/api/mis-clases/<int:clase_id>/asistencia")
@requiere_login("profe", "encargado")
def ver_asistencia(clase_id):
    clase, error = _clase_o_error(clase_id)
    if error:
        return error
    fecha, msg = _leer_fecha(request.args.get("fecha"), clase)
    if msg:
        return jsonify({"error": msg}), 400

    ids = _alumnos_del_dia(clase, fecha)
    dictada = _dictada(clase, fecha)
    marcas = {}
    if dictada:
        for a in m.Asistencia.query.filter_by(clase_dictada_id=dictada.id):
            marcas[a.alumno_id] = a
            ids.setdefault(a.alumno_id, False)  # por si lo sacaron de la clase después

    nombres = dict(db.session.query(Alumno.id, Alumno.nombre).filter(Alumno.id.in_(ids)).all()) if ids else {}
    alumnos = [{
        "id": aid,
        "nombre": nombres.get(aid, "?"),
        "recupera": recupera,
        "estado": marcas[aid].estado if aid in marcas else None,
        "nota": (marcas[aid].nota or "") if aid in marcas else "",
    } for aid, recupera in ids.items()]
    alumnos.sort(key=lambda x: x["nombre"].lower())
    return jsonify({"clase_id": clase.id, "fecha": fecha.isoformat(), "dictada": bool(dictada), "alumnos": alumnos})


@asistencia_bp.post("/api/mis-clases/<int:clase_id>/asistencia")
@requiere_login("profe", "encargado")
def marcar(clase_id):
    clase, error = _clase_o_error(clase_id)
    if error:
        return error
    datos = request.get_json(silent=True) or {}
    fecha, msg = _leer_fecha(datos.get("fecha"), clase)
    if msg:
        return jsonify({"error": msg}), 400
    estado = datos.get("estado")
    if estado not in m.ESTADOS_ASISTENCIA:
        return jsonify({"error": "Estado inválido"}), 400
    try:
        alumno_id = int(datos.get("alumno_id") or 0)
    except (TypeError, ValueError):
        alumno_id = 0

    # dos marcas a la vez pueden chocar con el único: se reintenta una vez
    for intento in range(2):
        try:
            resp = _guardar(clase, fecha, alumno_id, estado, datos)
            db.session.commit()
            return resp
        except IntegrityError:
            db.session.rollback()
            if intento:
                raise


def _guardar(clase, fecha, alumno_id, estado, datos):
    dictada = _dictada(clase, fecha)
    ya_marcado = dictada and m.Asistencia.query.filter_by(
        clase_dictada_id=dictada.id, alumno_id=alumno_id).first()
    if not ya_marcado and alumno_id not in _alumnos_del_dia(clase, fecha):
        return jsonify({"error": "Ese alumno no está en la clase ese día"}), 400

    if not dictada:
        # quien la dio es el profe de la clase, no el que marca; si ya existe no se toca
        dictada = m.ClaseDictada(clase_id=clase.id, fecha=fecha,
                                 profesor_id=clase.profesor_id, marcada_por=g.usuario.id)
        db.session.add(dictada)
        db.session.flush()

    fila = ya_marcado or m.Asistencia(clase_dictada_id=dictada.id, alumno_id=alumno_id)
    fila.estado = estado
    fila.origen = "panel"
    fila.marcado_en = datetime.utcnow()
    if "nota" in datos:
        fila.nota = (str(datos["nota"] or "").strip()[:255]) or None
    if not ya_marcado:
        db.session.add(fila)
    db.session.flush()
    # 'Avisó' / 'Ausente' deja la falta cargada para recuperar (solo alumnos fijos)
    recuperaciones.sincronizar_asistencia(clase, fecha, alumno_id, estado)
    return jsonify({"ok": True, "alumno_id": alumno_id, "estado": fila.estado, "nota": fila.nota or ""})
