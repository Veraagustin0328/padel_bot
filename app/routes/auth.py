"""
Login del panel. Devuelve un token (JWT) que el frontend manda en cada pedido:
    Authorization: Bearer <token>
Las rutas protegidas usan el decorador @requiere_login.
"""
import os
import datetime

import jwt
from flask import Blueprint, request, jsonify, g
from functools import wraps
from werkzeug.security import check_password_hash

from app.extensions import db
from app.models_plataforma import Usuario

auth_bp = Blueprint("auth", __name__)

HORAS_DE_SESION = 12


def _secreto():
    secreto = os.environ.get("JWT_SECRET", "")
    if not secreto:
        raise RuntimeError("Falta la variable de entorno JWT_SECRET")
    return secreto


def crear_token(usuario):
    ahora = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(usuario.id),
        "rol": usuario.rol,
        "iat": ahora,
        "exp": ahora + datetime.timedelta(hours=HORAS_DE_SESION),
    }
    return jwt.encode(payload, _secreto(), algorithm="HS256")


def _usuario_json(u):
    return {"id": u.id, "nombre": u.nombre, "email": u.email, "rol": u.rol}


def requiere_login(*roles):
    """
    @requiere_login()                -> cualquier usuario logueado
    @requiere_login("encargado")     -> encargado o admin (el admin entra siempre)
    """
    def decorador(f):
        @wraps(f)
        def envoltura(*args, **kwargs):
            cabecera = request.headers.get("Authorization", "")
            if not cabecera.startswith("Bearer "):
                return jsonify({"error": "Falta iniciar sesión"}), 401
            try:
                datos = jwt.decode(cabecera[7:], _secreto(), algorithms=["HS256"])
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "La sesión venció, entrá de nuevo"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "Sesión inválida"}), 401

            usuario = db.session.get(Usuario, int(datos["sub"]))
            if not usuario or not usuario.activo:
                return jsonify({"error": "Usuario inactivo"}), 401
            if roles and usuario.rol != "admin" and usuario.rol not in roles:
                return jsonify({"error": "No tenés permiso para esto"}), 403

            g.usuario = usuario
            return f(*args, **kwargs)
        return envoltura
    return decorador


@auth_bp.post("/api/auth/login")
def login():
    datos = request.get_json(silent=True) or {}
    email = (datos.get("email") or "").strip().lower()
    password = datos.get("password") or ""

    usuario = Usuario.query.filter_by(email=email).first()
    # mismo mensaje si falla el mail o la clave, así no se sabe cuál existe
    if not usuario or not usuario.activo or not check_password_hash(usuario.password_hash, password):
        return jsonify({"error": "Email o contraseña incorrectos"}), 401

    return jsonify({"token": crear_token(usuario), "usuario": _usuario_json(usuario)})


@auth_bp.get("/api/auth/me")
@requiere_login()
def yo():
    return jsonify(_usuario_json(g.usuario))