"""
Solicitudes de acceso al panel (gente que se registró por link). Dueño y encargado.
El encargado solo aprueba profe, jugador y tutor; dueño y encargado los da el dueño.
Aprobar = darle rol y vínculo (profe -> profesor_id, jugador/tutor -> alumno_usuario).
Rol "jugador_tutor" (ambos): un papá o mamá de Kids que también juega. Lleva su alumno propio
(relación jugador) y uno o más hijos (padre / madre / tutor), todo en alumno_usuario.
Rechazar = queda marcada en usuario_perfil y no entra.
"""
from datetime import datetime

from flask import Blueprint, request, jsonify, g

from app.contactos import tel10, tiene_telefono
from app.extensions import db
from app.models import Alumno, ContactoAlumno
from app.models_plataforma import Usuario, Profesor
from app.models_academia import UsuarioPerfil, AlumnoUsuario
from app.routes.auth import requiere_login, puede_tocar_rol

solicitudes_bp = Blueprint("solicitudes", __name__)

# roles que se pueden dar desde acá (cuáles puede cada uno lo decide puede_tocar_rol)
ROLES = ("dueno", "encargado", "profe", "jugador", "tutor", "jugador_tutor")
MAX_TUTORES = 2  # padre, madre o tutor por chico
RELACIONES_TUTOR = ("padre", "madre", "tutor")
CON_PROPIO = ("jugador", "jugador_tutor")  # roles que pueden tener su alumno propio
CON_HIJOS = ("tutor", "jugador_tutor")     # roles que pueden tener hijos


def _pendiente(id_):
    """Devuelve (usuario, perfil) si la solicitud sigue pendiente, si no (None, None)."""
    perfil = db.session.get(UsuarioPerfil, id_)
    if not perfil or perfil.estado != "pendiente":
        return None, None
    return db.session.get(Usuario, id_), perfil


@solicitudes_bp.get("/api/solicitudes")
@requiere_login("encargado")
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
@requiere_login("encargado")
def opciones():
    """Para los selects del panel: roles, profes y alumnos activos."""
    profes = Profesor.query.filter_by(activo=True).order_by(Profesor.nombre).all()
    alumnos = Alumno.query.filter(Alumno.estado != "baja").order_by(Alumno.nombre).all()
    con_contacto = {i for i, t in db.session.query(ContactoAlumno.alumno_id, ContactoAlumno.tel10) if len(t or "") == 10}
    return jsonify({
        "roles": [r for r in ROLES if puede_tocar_rol(g.usuario, r)],
        "parentescos": list(RELACIONES_TUTOR),
        "profesores": [{"id": p.id, "nombre": p.nombre} for p in profes],
        # sin teléfono no se puede vincular: el panel lo muestra apagado
        "alumnos": [{"id": a.id, "nombre": a.nombre,
                     "sin_telefono": a.id not in con_contacto and len(tel10(a.telefono)) < 10} for a in alumnos],
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


def _ids_hijos(datos, rol):
    """Lista de ids de hijos sin repetir. Para 'tutor' acepta también el alumno_id de antes."""
    crudo = datos.get("hijos") or []
    if not isinstance(crudo, list):
        return "malo"
    if rol == "tutor" and datos.get("alumno_id") not in (None, ""):
        crudo = [datos.get("alumno_id")] + crudo
    ids = []
    for v in crudo:
        n = _entero(v)
        if n in (None, "malo"):
            return "malo"
        if n not in ids:
            ids.append(n)
    return ids


@solicitudes_bp.post("/api/solicitudes/<int:id_>/aprobar")
@requiere_login("encargado")
def aprobar(id_):
    u, perfil = _pendiente(id_)
    if not u:
        return jsonify({"error": "No encontré esa solicitud pendiente"}), 404

    datos = request.get_json(silent=True) or {}
    rol = (datos.get("rol") or "").strip()
    profesor_id = _entero(datos.get("profesor_id"))
    # alumno_id = el alumno propio (jugador / ambos); hijos = los que ve como padre o tutor
    alumno_id = _entero(datos.get("alumno_id")) if rol != "tutor" else None
    hijos = _ids_hijos(datos, rol)
    parentesco = (datos.get("parentesco") or "tutor").strip()

    if rol not in ROLES:
        return _error("Elegí un rol válido")
    if not puede_tocar_rol(g.usuario, rol):
        return jsonify({"error": "Solo el dueño puede dar el rol de dueño o de admin"}), 403
    if "malo" in (profesor_id, alumno_id) or hijos == "malo":
        return _error("El vínculo tiene que ser un id")
    if hijos and rol not in CON_HIJOS:
        return _error("Solo un padre/tutor (o ambos) lleva hijos vinculados")

    if rol == "profe":
        if not profesor_id:
            return _error("Para un profe tenés que elegir a qué profesor corresponde")
        if alumno_id or hijos:
            return _error("Un profe no va vinculado a un alumno")
        if not db.session.get(Profesor, profesor_id):
            return _error("Ese profesor no existe")
    elif rol in CON_PROPIO + CON_HIJOS:
        if profesor_id:
            return _error("Ese rol no va vinculado a un profesor")
        if parentesco not in RELACIONES_TUTOR:
            return _error("El parentesco tiene que ser padre, madre o tutor")
        if alumno_id:
            propio = db.session.get(Alumno, alumno_id)
            if not propio:
                return _error("Ese alumno no existe")
            if not tiene_telefono(propio):
                return _error(f"{propio.nombre} no tiene teléfono cargado: cargalo en Fichas antes de vincularlo")
            if AlumnoUsuario.query.filter_by(alumno_id=alumno_id, relacion="jugador").first():
                return _error("Ese alumno ya tiene una cuenta de jugador vinculada")
        if alumno_id and alumno_id in hijos:
            return _error("El alumno propio no puede ser también su hijo")
        for h in hijos:
            hijo = db.session.get(Alumno, h)
            if not hijo:
                return _error("Ese alumno no existe")
            if not tiene_telefono(hijo):
                return _error(f"{hijo.nombre} no tiene teléfono cargado (ni del chico ni de un tutor): "
                              "cargalo en Fichas antes de vincularlo")
            tutores = AlumnoUsuario.query.filter(AlumnoUsuario.alumno_id == h,
                                                 AlumnoUsuario.relacion.in_(RELACIONES_TUTOR)).count()
            if tutores >= MAX_TUTORES:
                return _error(f"{hijo.nombre} ya tiene {MAX_TUTORES} tutores vinculados")
    elif profesor_id or alumno_id or hijos:  # dueño y encargado: sin vínculo
        return _error("Ese rol no lleva vínculo")

    u.rol = rol
    u.profesor_id = profesor_id if rol == "profe" else None
    u.activo = True
    if alumno_id:
        db.session.add(AlumnoUsuario(alumno_id=alumno_id, usuario_id=u.id, relacion="jugador"))
    for h in hijos:
        db.session.add(AlumnoUsuario(alumno_id=h, usuario_id=u.id, relacion=parentesco))
    perfil.estado = "activo"
    perfil.aprobado_por = g.usuario.id
    perfil.aprobado_en = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "id": u.id, "rol": u.rol})


@solicitudes_bp.post("/api/solicitudes/<int:id_>/rechazar")
@requiere_login("encargado")
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
