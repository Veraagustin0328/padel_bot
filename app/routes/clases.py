"""Clases del horario fijo para el panel (por ahora solo lectura)."""
import json

from flask import Blueprint, jsonify

from app import models_academia as m
from app.extensions import db
from app.models import Alumno
from app.models_plataforma import Profesor
from app.routes.auth import requiere_login

clases_bp = Blueprint("clases_panel", __name__)


@clases_bp.get("/api/clases")
@requiere_login("encargado")
def listar():
    filas = (
        db.session.query(m.Clase, Profesor.nombre)
        .outerjoin(Profesor, m.Clase.profesor_id == Profesor.id)
        .filter(m.Clase.activa.is_(True))
        .all()
    )

    # alumnos anotados hoy en cada clase
    inscriptos = {}
    consulta = (
        db.session.query(m.Inscripcion.clase_id, Alumno.id, Alumno.nombre, m.Inscripcion.desde)
        .join(Alumno, Alumno.id == m.Inscripcion.alumno_id)
        .filter(m.Inscripcion.hasta.is_(None))
        .order_by(Alumno.nombre)
    )
    for clase_id, alumno_id, nombre, desde in consulta:
        inscriptos.setdefault(clase_id, []).append(
            {"id": alumno_id, "nombre": nombre, "desde": desde.isoformat() if desde else None}
        )

    # lo que dejó el importador: tipos que se adivinaron y notas de Gabi
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
            "estimado": c.id in estimada and c.id not in confirmada,
            "nota": notas.get(c.id, ""),
            "alumnos": inscriptos.get(c.id, []),
        })
    salida.sort(key=lambda x: (x["dia"], x["hora"], x["profe"]))

    cfg = db.session.get(m.ConfigAcademia, "colores_nivel")
    colores = json.loads(cfg.valor) if cfg else {}
    return jsonify({"clases": salida, "colores_nivel": colores})