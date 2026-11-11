"""Consultas que el agente le pasó al encargado: listar, contar y marcar resueltas (dueño y encargado).

Salen de la tabla notificaciones, solo de los tipos de TIPOS_CONSULTA.
Abierta = resuelta_en vacío. No hay reabrir: las resueltas quedan para consultar.
"""
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from app.extensions import db
from app.models import Alumno, Notificacion
from app.models_plataforma import Usuario
from app.routes.auth import requiere_login

consultas_bp = Blueprint("consultas", __name__)

# lo que el encargado tiene que contestar o hacer y no tiene otra solapa
TIPOS_CONSULTA = ("consulta_derivada", "comprobante")
MAX_RESUELTAS = 100  # las resueltas son para mirar, no hace falta traer todo el historial


def _abiertas():
    return Notificacion.query.filter(Notificacion.tipo.in_(TIPOS_CONSULTA),
                                     Notificacion.resuelta_en.is_(None))


def _contar() -> int:
    # count en la base, no trae filas (lo cubre el índice parcial de la migración)
    return _abiertas().count()


def _fecha(d):
    return d.isoformat() + "Z" if d else None


def _items(filas) -> list:
    tels = {n.telefono for n in filas if n.telefono}
    alumnos = {a.telefono: a.nombre for a in Alumno.query.filter(Alumno.telefono.in_(tels))} if tels else {}
    ids_ = {n.resuelta_por for n in filas if n.resuelta_por}
    usuarios = {u.id: u.nombre for u in Usuario.query.filter(Usuario.id.in_(ids_))} if ids_ else {}
    return [{
        "id": n.id,
        "tipo": n.tipo,
        "tema": n.tema,
        "mensaje": n.mensaje,
        "telefono": n.telefono,
        "alumno": alumnos.get(n.telefono),  # vacío si escribió alguien que no es alumno
        "creado_en": _fecha(n.creado_en),
        "resuelta_en": _fecha(n.resuelta_en),
        "resuelta_por": usuarios.get(n.resuelta_por),
    } for n in filas]


@consultas_bp.get("/api/consultas")
@requiere_login("encargado")
def listar():
    if request.args.get("estado") == "resueltas":
        filas = (Notificacion.query.filter(Notificacion.tipo.in_(TIPOS_CONSULTA),
                                           Notificacion.resuelta_en.isnot(None))
                 .order_by(Notificacion.resuelta_en.desc()).limit(MAX_RESUELTAS).all())
    else:
        # las abiertas de la más vieja a la más nueva: primero la que espera hace más
        filas = _abiertas().order_by(Notificacion.creado_en, Notificacion.id).all()
    return jsonify(_items(filas))


@consultas_bp.get("/api/consultas/pendientes")
@requiere_login("encargado")
def contar_pendientes():
    return jsonify({"total": _contar()})


@consultas_bp.post("/api/consultas/<int:id_>/resolver")
@requiere_login("encargado")
def resolver(id_):
    n = db.session.get(Notificacion, id_)
    if not n or n.tipo not in TIPOS_CONSULTA:
        return jsonify({"error": "No existe esa consulta"}), 404
    # si ya estaba resuelta (dos encargados a la vez) no la piso: queda quien la resolvió primero
    if n.resuelta_en is None:
        n.resuelta_en = datetime.utcnow()
        n.resuelta_por = g.usuario.id
        db.session.commit()
    return jsonify({"consulta": _items([n])[0], "total": _contar()})
