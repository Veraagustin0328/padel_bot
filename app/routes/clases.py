"""Clases del horario fijo para el panel: ver y editar.

Todo cambio queda en la tabla de auditoría con quién lo hizo.
"""
import json
from datetime import date

from flask import Blueprint, g, jsonify, request

from app import models_academia as m
from app import recuperaciones
from app.cambios_dias import vigente_en
from app.extensions import db
from app.models import Alumno
from app.models_plataforma import Profesor
from app.routes.auth import requiere_login

clases_bp = Blueprint("clases_panel", __name__)

# cupo habitual de cada tipo; si cambia el tipo y no se manda cupo, se ajusta solo
CUPO_POR_TIPO = {"particular": 1, "particular_2": 2, "grupal": 4}


def _auditar(clase_id, accion, antes=None, despues=None):
    db.session.add(m.Auditoria(
        entidad="clase",
        entidad_id=clase_id,
        accion=accion,
        antes=json.dumps(antes, ensure_ascii=False) if antes is not None else None,
        despues=json.dumps(despues, ensure_ascii=False) if despues is not None else None,
        usuario_id=g.usuario.id,
    ))


def _estados():
    """Qué clases tienen el tipo adivinado, cuáles ya se confirmaron y las notas de la planilla."""
    estimada, confirmada, notas = set(), set(), {}
    registros = m.Auditoria.query.filter(
        m.Auditoria.entidad == "clase",
        m.Auditoria.accion.in_(["tipo_estimado", "tipo_confirmado", "nota_planilla"]),
    )
    for a in registros:
        if a.accion == "tipo_estimado":
            estimada.add(a.entidad_id)
        elif a.accion == "tipo_confirmado":
            confirmada.add(a.entidad_id)
        else:
            notas[a.entidad_id] = a.despues
    return estimada, confirmada, notas


def _cantidad_inscriptos():
    cuentas = {}
    # solo los que están anotados hoy: una inscripción que arranca más adelante no cuenta todavía
    filas = db.session.query(m.Inscripcion.clase_id).filter(vigente_en(recuperaciones.hoy())).all()
    for (clase_id,) in filas:
        cuentas[clase_id] = cuentas.get(clase_id, 0) + 1
    return cuentas


@clases_bp.get("/api/clases")
@requiere_login("encargado")
def listar():
    filas = (
        db.session.query(m.Clase, Profesor.nombre)
        .outerjoin(Profesor, m.Clase.profesor_id == Profesor.id)
        .all()
    )

    # alumnos anotados hoy en cada clase
    inscriptos = {}
    consulta = (
        db.session.query(m.Inscripcion.clase_id, Alumno.id, Alumno.nombre, m.Inscripcion.desde)
        .join(Alumno, Alumno.id == m.Inscripcion.alumno_id)
        .filter(vigente_en(recuperaciones.hoy()))
        .order_by(Alumno.nombre)
    )
    for clase_id, alumno_id, nombre, desde in consulta:
        inscriptos.setdefault(clase_id, []).append(
            {"id": alumno_id, "nombre": nombre, "desde": desde.isoformat() if desde else None}
        )

    estimada, confirmada, notas = _estados()

    salida = []
    for c, profe in filas:
        salida.append({
            "id": c.id,
            "ambito": c.ambito,
            "dia": c.dia_semana,
            "hora": c.hora_inicio.strftime("%H:%M"),
            "profe": profe or "",
            "profe_id": c.profesor_id,
            "tipo": c.tipo,
            "nivel": c.nivel or "",
            "cupo": c.cupo,
            "activa": bool(c.activa),
            "estimado": c.id in estimada and c.id not in confirmada,
            "nota": notas.get(c.id, ""),
            "alumnos": inscriptos.get(c.id, []),
        })
    salida.sort(key=lambda x: (x["dia"], x["hora"], x["profe"]))

    cfg = db.session.get(m.ConfigAcademia, "colores_nivel")
    colores = json.loads(cfg.valor) if cfg else {}
    return jsonify({"clases": salida, "colores_nivel": colores})


@clases_bp.get("/api/clases/profes")
@requiere_login("encargado")
def profes():
    filas = Profesor.query.filter(Profesor.activo.is_(True)).order_by(Profesor.nombre).all()
    return jsonify([{"id": p.id, "nombre": p.nombre} for p in filas])


@clases_bp.get("/api/clases/buscar-alumnos")
@requiere_login("encargado")
def buscar_alumnos():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    filas = Alumno.query.filter(Alumno.nombre.ilike(f"%{q}%")).order_by(Alumno.nombre).limit(10).all()
    return jsonify([{"id": a.id, "nombre": a.nombre} for a in filas])


@clases_bp.patch("/api/clases/<int:clase_id>")
@requiere_login("encargado")
def editar(clase_id):
    c = db.session.get(m.Clase, clase_id)
    if not c:
        return jsonify({"error": "No encontré la clase"}), 404
    datos = request.get_json(silent=True) or {}
    antes, despues = {}, {}

    def cambiar(campo, nuevo):
        actual = getattr(c, campo)
        if nuevo != actual:
            antes[campo] = actual
            despues[campo] = nuevo
            setattr(c, campo, nuevo)

    if "tipo" in datos:
        if datos["tipo"] not in m.TIPOS_CLASE:
            return jsonify({"error": "Tipo de clase inválido"}), 400
        cambiar("tipo", datos["tipo"])
        if "cupo" not in datos and datos["tipo"] in CUPO_POR_TIPO:
            cambiar("cupo", CUPO_POR_TIPO[datos["tipo"]])
    if "nivel" in datos:
        cambiar("nivel", str(datos["nivel"] or "").strip().upper() or None)
    if "cupo" in datos:
        try:
            cupo = int(datos["cupo"])
        except (TypeError, ValueError):
            return jsonify({"error": "El cupo tiene que ser un número"}), 400
        if not 1 <= cupo <= 20:
            return jsonify({"error": "El cupo tiene que estar entre 1 y 20"}), 400
        cambiar("cupo", cupo)
    if "profesor_id" in datos:
        pid = datos["profesor_id"] or None
        if pid is not None:
            pid = int(pid)
            if not db.session.get(Profesor, pid):
                return jsonify({"error": "No encontré ese profe"}), 400
        cambiar("profesor_id", pid)
    if "activa" in datos:
        cambiar("activa", bool(datos["activa"]))

    if despues:
        _auditar(c.id, "editar", antes, despues)
    if "tipo" in datos or datos.get("confirmar_tipo"):
        _auditar(c.id, "tipo_confirmado", None, c.tipo)
    db.session.commit()
    return jsonify({"ok": True})


@clases_bp.post("/api/clases/<int:clase_id>/alumnos")
@requiere_login("encargado")
def anotar(clase_id):
    c = db.session.get(m.Clase, clase_id)
    if not c:
        return jsonify({"error": "No encontré la clase"}), 404
    datos = request.get_json(silent=True) or {}
    alumno = db.session.get(Alumno, int(datos.get("alumno_id") or 0))
    if not alumno:
        return jsonify({"error": "No encontré el alumno"}), 400
    ya = m.Inscripcion.query.filter_by(clase_id=c.id, alumno_id=alumno.id, hasta=None).first()
    if ya:
        return jsonify({"error": f"{alumno.nombre} ya está en esta clase"}), 409
    db.session.add(m.Inscripcion(clase_id=c.id, alumno_id=alumno.id, desde=date.today()))
    _auditar(c.id, "anotar_alumno", None, {"alumno_id": alumno.id, "nombre": alumno.nombre})
    db.session.commit()
    return jsonify({"ok": True})


@clases_bp.delete("/api/clases/<int:clase_id>/alumnos/<int:alumno_id>")
@requiere_login("encargado")
def sacar(clase_id, alumno_id):
    ins = m.Inscripcion.query.filter_by(clase_id=clase_id, alumno_id=alumno_id, hasta=None).first()
    if not ins:
        return jsonify({"error": "Ese alumno no está en la clase"}), 404
    alumno = db.session.get(Alumno, alumno_id)
    ins.hasta = date.today()
    _auditar(clase_id, "sacar_alumno", {"alumno_id": alumno_id, "nombre": alumno.nombre if alumno else ""}, None)
    db.session.commit()
    return jsonify({"ok": True})


@clases_bp.post("/api/clases/confirmar-grupales")
@requiere_login("encargado")
def confirmar_grupales():
    """Confirma de una sola vez las clases que el importador dejó como grupales con 3 o más alumnos."""
    estimada, confirmada, _ = _estados()
    pendientes = list(estimada - confirmada)
    if not pendientes:
        return jsonify({"confirmadas": 0})
    cuentas = _cantidad_inscriptos()
    n = 0
    clases = m.Clase.query.filter(m.Clase.id.in_(pendientes), m.Clase.activa.is_(True), m.Clase.tipo == "grupal")
    for c in clases:
        if cuentas.get(c.id, 0) >= 3:
            _auditar(c.id, "tipo_confirmado", None, c.tipo)
            n += 1
    db.session.commit()
    return jsonify({"confirmadas": n})