"""
Solicitudes de acceso al panel (gente que se registró por link). Solo el admin.
Aprobar = darle rol y vínculo (profe -> profesor_id, jugador/tutor -> alumno_usuario).
Rechazar = queda marcada en usuario_perfil y no entra.
"""
from datetime import datetime

from flask import Blueprint, request, jsonify, g

from app.extensions import db
from app.models import Alumno
from app.models_plataforma import Usuario, Profesor
from app.models_academia import UsuarioPerfil, AlumnoUsuario
from app.routes.auth import requiere_login

solicitudes_bp = Blueprint("solicitudes", __name__)

# roles que se pueden dar desde acá (admin no: eso queda para el script)
ROLES = ("encargado", "profe", "jugador", "tutor")
MAX_TUTORES = 2  # padre, madre o tutor por chico
RELACIONES_TUTOR = ("padre", "madre", "tutor")


def _pendiente(id_):
    """Devuelve (usuario, perfil) si la solicitud sigue pendiente, si no (None, None)."""
    perfil = db.session.get(UsuarioPerfil, id_)
    if not perfil or perfil.estado != "pendiente":
        return None, None
    return db.session.get(Usuario, id_), perfil


@solicitudes_bp.get("/api/solicitudes")
@requiere_login("admin")
def listar():
    filas = (
        db.session.query(Usuario)
        .join(UsuarioPerfil, UsuarioPerfil.usuario_id == Usuario.id)
        .filter(UsuarioPerfil.estado == "pendiente")
        .order_by(Usuario.creado_en)
        .all()
    )
    return jsonify([
        {"id": u.id, "nombre": u.nombre, "email": u.email,
         "creado_en": u.creado_en.isoformat() if u.creado_en else None}
        for u in filas
    ])


@solicitudes_bp.get("/api/solicitudes/opciones")
@requiere_login("admin")
def opciones():
    """Para los selects del panel: roles, profes y alumnos activos."""
    profes = Profesor.query.filter_by(activo=True).order_by(Profesor.nombre).all()
    alumnos = Alumno.query.filter(Alumno.estado != "baja").order_by(Alumno.nombre).all()
    return jsonify({
        "roles": list(ROLES),
        "profesores": [{"id": p.id, "nombre": p.nombre} for p in profes],
        "alumnos": [{"id": a.id, "nombre": a.nombre} for a in alumnos],
    })


def _entero(valor):
    if valor in (None, ""):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return "malo"


def _error(texto):
    return jsonify({"error": texto}), 400


@solicitudes_bp.post("/api/solicitudes/<int:id_>/aprobar")
@requiere_login("admin")
def aprobar(id_):
    u, perfil = _pendiente(id_)
    if not u:
        return jsonify({"error": "No encontré esa solicitud pendiente"}), 404

    datos = request.get_json(silent=True) or {}
    rol = (datos.get("rol") or "").strip()
    profesor_id = _entero(datos.get("profesor_id"))
    alumno_id = _entero(datos.get("alumno_id"))

    if rol not in ROLES:
        return _error("Elegí un rol válido")
    if "malo" in (profesor_id, alumno_id):
        return _error("El vínculo tiene que ser un id")

    if rol == "profe":
        if not profesor_id:
            return _error("Para un profe tenés que elegir a qué profesor corresponde")
        if alumno_id:
            return _error("Un profe no va vinculado a un alumno")
        if not db.session.get(Profesor, profesor_id):
            return _error("Ese profesor no existe")
    elif rol in ("jugador", "tutor"):
        if profesor_id:
            return _error("Ese rol no va vinculado a un profesor")
        if alumno_id:
            if not db.session.get(Alumno, alumno_id):
                return _error("Ese alumno no existe")
            vinculos = AlumnoUsuario.query.filter_by(alumno_id=alumno_id)
            if rol == "jugador" and vinculos.filter_by(relacion="jugador").first():
                return _error("Ese alumno ya tiene una cuenta de jugador vinculada")
            if rol == "tutor" and vinculos.filter(AlumnoUsuario.relacion.in_(RELACIONES_TUTOR)).count() >= MAX_TUTORES:
                return _error(f"Ese alumno ya tiene {MAX_TUTORES} tutores vinculados")
    elif profesor_id or alumno_id:  # encargado: sin vínculo
        return _error("El encargado no lleva vínculo")

    u.rol = rol
    u.profesor_id = profesor_id if rol == "profe" else None
    u.activo = True
    if alumno_id:
        db.session.add(AlumnoUsuario(alumno_id=alumno_id, usuario_id=u.id, relacion=rol))
    perfil.estado = "activo"
    perfil.aprobado_por = g.usuario.id
    perfil.aprobado_en = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "id": u.id, "rol": u.rol})


@solicitudes_bp.post("/api/solicitudes/<int:id_>/rechazar")
@requiere_login("admin")
def rechazar(id_):
    u, perfil = _pendiente(id_)
    if not u:
        return jsonify({"error": "No encontré esa solicitud pendiente"}), 404
    u.activo = False
    perfil.estado = "rechazado"
    perfil.aprobado_por = g.usuario.id  # quién la resolvió
    perfil.aprobado_en = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "id": u.id})
