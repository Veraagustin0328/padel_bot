"""
Notas internas del panel: solo dueño y encargado (el profe y los demás, 403).
Una nota puede ir atada a un alumno o quedar suelta. Las fijadas salen primero.
Cualquiera de los dos puede editar o borrar cualquier nota.
"""
from flask import Blueprint, request, jsonify, g

from app.extensions import db
from app.models import Alumno
from app.models_academia import Nota
from app.models_plataforma import Usuario
from app.routes.auth import requiere_login

notas_bp = Blueprint("notas", __name__)

TITULO_MAX = 120
TEXTO_MAX = 4000
BUSQUEDA_MAX = 100


def _fecha(d):
    return d.isoformat() + "Z" if d else None


def _json(n, alumnos, autores):
    return {
        "id": n.id,
        "titulo": n.titulo,
        "texto": n.texto or "",
        "alumno_id": n.alumno_id,
        "alumno_nombre": alumnos.get(n.alumno_id),
        "creada_por": n.creada_por,
        "creada_por_nombre": autores.get(n.creada_por),
        "fijada": bool(n.fijada),
        "creada_en": _fecha(n.creada_en),
        "actualizada_en": _fecha(n.actualizada_en),
    }


def _json_varias(notas):
    """Trae los nombres de alumnos y autores de una sola vez, no uno por nota."""
    ids_alu = {n.alumno_id for n in notas if n.alumno_id}
    ids_usu = {n.creada_por for n in notas if n.creada_por}
    alumnos = dict(db.session.query(Alumno.id, Alumno.nombre).filter(Alumno.id.in_(ids_alu)).all()) if ids_alu else {}
    autores = dict(db.session.query(Usuario.id, Usuario.nombre).filter(Usuario.id.in_(ids_usu)).all()) if ids_usu else {}
    return [_json(n, alumnos, autores) for n in notas]


def _error(texto, codigo=400):
    return jsonify({"error": texto}), codigo


def _validar(datos, parcial):
    """Devuelve (campos, error). En PATCH (parcial) solo valida lo que vino."""
    campos = {}

    if not parcial or "titulo" in datos:
        titulo = (datos.get("titulo") or "").strip()
        if not titulo or len(titulo) > TITULO_MAX:
            return None, f"Poné un título (hasta {TITULO_MAX} letras)"
        campos["titulo"] = titulo

    if not parcial or "texto" in datos:
        texto = (datos.get("texto") or "").strip()
        if len(texto) > TEXTO_MAX:
            return None, f"El texto es muy largo (hasta {TEXTO_MAX} letras)"
        campos["texto"] = texto or None

    if "alumno_id" in datos:
        valor = datos.get("alumno_id")
        if valor in (None, ""):
            campos["alumno_id"] = None
        else:
            try:
                alumno_id = int(valor)
            except (TypeError, ValueError):
                return None, "El alumno tiene que ser un id"
            if not db.session.get(Alumno, alumno_id):
                return None, "Ese alumno no existe"
            campos["alumno_id"] = alumno_id

    if "fijada" in datos:
        campos["fijada"] = bool(datos.get("fijada"))

    return campos, None


@notas_bp.get("/api/notas")
@requiere_login("encargado")
def listar():
    consulta = Nota.query
    alumno_id = request.args.get("alumno_id", type=int)
    if alumno_id:
        consulta = consulta.filter(Nota.alumno_id == alumno_id)
    q = (request.args.get("q") or "").strip()[:BUSQUEDA_MAX]
    if q:
        patron = f"%{q}%"
        consulta = consulta.filter(db.or_(Nota.titulo.ilike(patron), Nota.texto.ilike(patron)))
    filas = consulta.order_by(Nota.fijada.desc(), Nota.actualizada_en.desc(), Nota.id.desc()).all()
    return jsonify(_json_varias(filas))


@notas_bp.get("/api/notas/alumnos")
@requiere_login("encargado")
def alumnos():
    """Para el select de la pantalla: alumnos que no están de baja."""
    lista = Alumno.query.filter(Alumno.estado != "baja").order_by(Alumno.nombre).all()
    return jsonify([{"id": a.id, "nombre": a.nombre} for a in lista])


@notas_bp.post("/api/notas")
@requiere_login("encargado")
def crear():
    campos, error = _validar(request.get_json(silent=True) or {}, parcial=False)
    if error:
        return _error(error)
    n = Nota(creada_por=g.usuario.id, **campos)
    db.session.add(n)
    db.session.commit()
    return jsonify(_json_varias([n])[0]), 201


@notas_bp.patch("/api/notas/<int:id_>")
@requiere_login("encargado")
def editar(id_):
    n = db.session.get(Nota, id_)
    if not n:
        return _error("No encontré esa nota", 404)
    campos, error = _validar(request.get_json(silent=True) or {}, parcial=True)
    if error:
        return _error(error)
    for clave, valor in campos.items():
        setattr(n, clave, valor)
    db.session.commit()
    return jsonify(_json_varias([n])[0])


@notas_bp.delete("/api/notas/<int:id_>")
@requiere_login("encargado")
def borrar(id_):
    n = db.session.get(Nota, id_)
    if not n:
        return _error("No encontré esa nota", 404)
    db.session.delete(n)
    db.session.commit()
    return jsonify({"ok": True, "id": id_})
