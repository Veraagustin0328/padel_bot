"""
Panel del alumno / padre: /api/yo/... Solo jugador, tutor y jugador_tutor.

Regla única de acceso: un usuario ve solo los alumnos vinculados a él en alumno_usuario,
y el vínculo se cruza con el rol (si a un tutor le cambian el rol a jugador, deja de ver
a los hijos aunque quede la fila vieja). Todo lo que reciba un alumno_id pasa por
@con_alumno, que da 404 (no 403) si no es suyo: así no se puede averiguar qué ids existen.

Las respuestas se arman a mano con lista blanca de campos: nada de teléfonos, montos
del club ni datos de otros alumnos o tutores.

Quién entra:
- jugador / tutor / jugador_tutor: lo suyo.
- encargado y profe: 403 (tienen su propio panel).
- dueño: pasa, como en todo requiere_login, pero no tiene vínculos de alumno por su rol,
  así que ve lista vacía y cualquier alumno le da 404.
"""
from functools import wraps

from flask import Blueprint, jsonify, g

from app import recuperaciones as rec
from app.extensions import db
from app.models import Alumno
from app.models_academia import AlumnoUsuario, AlumnoPerfil
from app.routes.auth import requiere_login

yo_bp = Blueprint("yo", __name__)

ROLES_ALUMNO = ("jugador", "tutor", "jugador_tutor")
RELACIONES_TUTOR = ("padre", "madre", "tutor")
# qué relaciones habilita cada rol
VE_PROPIO = ("jugador", "jugador_tutor")
VE_HIJOS = ("tutor", "jugador_tutor")

NO_ENCONTRADO = "No encontré ese alumno"


def alumnos_mios(usuario):
    """{alumno_id: "propio" | "hijo"} de este usuario, según sus filas y su rol."""
    mios = {}
    filas = db.session.query(AlumnoUsuario.alumno_id, AlumnoUsuario.relacion).filter(
        AlumnoUsuario.usuario_id == usuario.id).all()
    for alumno_id, relacion in filas:
        if relacion == "jugador" and usuario.rol in VE_PROPIO:
            mios[alumno_id] = "propio"
        elif relacion in RELACIONES_TUTOR and usuario.rol in VE_HIJOS:
            mios.setdefault(alumno_id, "hijo")  # si fuera las dos cosas, gana propio
    return mios


def alumno_mio(alumno_id):
    """El Alumno si está vinculado al usuario logueado; si no, None (la ruta da 404)."""
    if alumno_id not in alumnos_mios(g.usuario):
        return None
    return db.session.get(Alumno, alumno_id)


def con_alumno(f):
    """Para rutas /api/yo/alumnos/<alumno_id>/...: chequea pertenencia y pasa el Alumno.
    Va DEBAJO de @requiere_login (necesita g.usuario)."""
    @wraps(f)
    def envoltura(alumno_id, *args, **kwargs):
        alumno = alumno_mio(alumno_id)
        if not alumno:
            return jsonify({"error": NO_ENCONTRADO}), 404
        return f(alumno, *args, **kwargs)
    envoltura.chequea_alumno = True  # lo mira la prueba: toda ruta con alumno_id lo tiene que tener
    return envoltura


def _texto(clave):
    valor = rec.regla(clave)
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


# ---------- rutas ----------

@yo_bp.get("/api/yo/alumnos")
@requiere_login(*ROLES_ALUMNO)
def mis_alumnos():
    mios = alumnos_mios(g.usuario)
    if not mios:
        return jsonify([])
    filas = (db.session.query(Alumno.id, Alumno.nombre, AlumnoPerfil.es_menor)
             .outerjoin(AlumnoPerfil, AlumnoPerfil.alumno_id == Alumno.id)
             .filter(Alumno.id.in_(list(mios)))
             .all())
    salida = [{"id": id_, "nombre": nombre, "es_menor": bool(es_menor), "vinculo": mios[id_]}
              for id_, nombre, es_menor in filas]
    salida.sort(key=lambda a: (a["vinculo"] != "propio", a["nombre"].lower()))  # propio primero
    return jsonify(salida)


@yo_bp.get("/api/yo/datos-pago")
@requiere_login(*ROLES_ALUMNO)
def datos_pago():
    # de config_academia; si falta, None y el panel dice que se lo pida al encargado
    return jsonify({"nombre_academia": _texto("nombre_academia"), "datos_pago": _texto("datos_pago")})
