"""
Login del panel. Devuelve un token (JWT) que el frontend manda en cada pedido:
    Authorization: Bearer <token>
Las rutas protegidas usan el decorador @requiere_login.

También está el registro por link: la cuenta queda pendiente hasta que el admin
la aprueba desde Solicitudes (app/routes/solicitudes.py). El estado va en
usuario_perfil, así la tabla usuarios no se toca.
"""
import os
import re
import logging
import secrets
import time
import datetime
import threading
from collections import deque

import jwt
from flask import Blueprint, request, jsonify, g
from functools import wraps
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models_plataforma import Usuario
from app.models_academia import UsuarioPerfil

auth_bp = Blueprint("auth", __name__)
log = logging.getLogger(__name__)

HORAS_DE_SESION = 12

# registro: largo mínimo de la clave y límites para que no lo llenen de basura
CLAVE_MINIMA = 8
REGISTROS_POR_IP = 5          # por IP...
REGISTROS_TOTALES = 30        # ...y en total, por si alguien rota IPs
VENTANA_SEGUNDOS = 60 * 60    # en una hora
# la columna rol no acepta vacío; este valor no coincide con ningún rol real
ROL_PENDIENTE = "pendiente"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# cambio de clave: cuántas veces puede errarle a la actual antes de frenarlo
FALLOS_CLAVE_POR_USUARIO = 5
VENTANA_FALLOS_SEGUNDOS = 15 * 60
# clave que genera el reset: sin letras que se confunden (0/O, 1/l/I)
ALFABETO_CLAVE = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LARGO_CLAVE_RESET = 12


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
    clave_ok = bool(usuario) and check_password_hash(usuario.password_hash, password)

    # solo con la clave correcta le contamos que está pendiente, así no se puede
    # averiguar qué mails se registraron. Los usuarios de siempre no tienen perfil: siguen igual
    if clave_ok and not usuario.activo:
        perfil = db.session.get(UsuarioPerfil, usuario.id)
        if perfil and perfil.estado == "pendiente":
            return jsonify({"error": "Tu cuenta está pendiente de aprobación"}), 403
        if perfil and perfil.estado == "rechazado":
            return jsonify({"error": "Tu solicitud de acceso no fue aprobada"}), 403

    # mismo mensaje si falla el mail o la clave, así no se sabe cuál existe
    if not clave_ok or not usuario.activo:
        return jsonify({"error": "Email o contraseña incorrectos"}), 401

    return jsonify({"token": crear_token(usuario), "usuario": _usuario_json(usuario)})


@auth_bp.get("/api/auth/me")
@requiere_login()
def yo():
    return jsonify(_usuario_json(g.usuario))


# ---------- registro por link ----------

# en memoria alcanza: Render free corre un solo proceso. Si se reinicia, se resetea y listo
_intentos_por_ip = {}
_intentos_totales = deque()
_candado = threading.Lock()


def _ip_cliente():
    # detrás del proxy de Render la IP real viene en X-Forwarded-For (la primera)
    reenviada = request.headers.get("X-Forwarded-For", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.remote_addr or "?"


def _limpiar(cola, ahora):
    while cola and ahora - cola[0] > VENTANA_SEGUNDOS:
        cola.popleft()


def _pasa_limite(ip):
    """Anota el intento y dice si todavía está dentro del límite."""
    ahora = time.monotonic()
    with _candado:
        _limpiar(_intentos_totales, ahora)
        cola = _intentos_por_ip.setdefault(ip, deque())
        _limpiar(cola, ahora)
        if len(cola) >= REGISTROS_POR_IP or len(_intentos_totales) >= REGISTROS_TOTALES:
            return False
        cola.append(ahora)
        _intentos_totales.append(ahora)
        # que el dict no crezca para siempre
        for otra in [k for k, v in _intentos_por_ip.items() if not v]:
            del _intentos_por_ip[otra]
        return True


@auth_bp.post("/api/auth/registro")
def registro():
    if not _pasa_limite(_ip_cliente()):
        return jsonify({"error": "Demasiados intentos, probá de nuevo en un rato"}), 429

    datos = request.get_json(silent=True) or {}
    nombre = (datos.get("nombre") or "").strip()
    email = (datos.get("email") or "").strip().lower()
    password = datos.get("password") or datos.get("contraseña") or ""

    if not nombre or len(nombre) > 120:
        return jsonify({"error": "Poné tu nombre (hasta 120 letras)"}), 400
    if len(email) > 160 or not EMAIL_RE.match(email):
        return jsonify({"error": "El email no es válido"}), 400
    if len(password) < CLAVE_MINIMA:
        return jsonify({"error": f"La contraseña tiene que tener al menos {CLAVE_MINIMA} caracteres"}), 400
    if len(password) > 200:
        return jsonify({"error": "La contraseña es demasiado larga"}), 400
    if Usuario.query.filter_by(email=email).first():
        return jsonify({"error": "Ya hay una cuenta con ese email"}), 409

    # sin acceso hasta que lo aprueben: inactivo y con un rol que no abre nada
    u = Usuario(nombre=nombre, email=email, rol=ROL_PENDIENTE, activo=False,
                password_hash=generate_password_hash(password))
    db.session.add(u)
    try:
        db.session.flush()
        db.session.add(UsuarioPerfil(usuario_id=u.id, estado="pendiente", creado_via="registro"))
        db.session.commit()
    except IntegrityError:  # dos registros iguales al mismo tiempo
        db.session.rollback()
        return jsonify({"error": "Ya hay una cuenta con ese email"}), 409

    # aviso al admin con el mismo sistema de notificaciones del agente
    # el usuario ya quedó guardado: si el aviso falla, solo se loguea
    try:
        from app.llm.agent import _notificar
        _notificar(f"Nueva solicitud de acceso al panel: {nombre} ({email})", tipo="solicitud_acceso")
    except Exception:
        db.session.rollback()
        log.exception("No pude avisar la solicitud de %s", email)

    return jsonify({"ok": True, "mensaje": "Listo, tu solicitud quedó pendiente de aprobación"}), 201


# ---------- cambio y reset de contraseña ----------

# mismo esquema que el registro: en memoria, se resetea si reinicia el proceso
_fallos_clave = {}


def _bloqueado_por_fallos(usuario_id):
    ahora = time.monotonic()
    with _candado:
        cola = _fallos_clave.get(usuario_id)
        if not cola:
            return False
        while cola and ahora - cola[0] > VENTANA_FALLOS_SEGUNDOS:
            cola.popleft()
        if not cola:
            del _fallos_clave[usuario_id]
            return False
        return len(cola) >= FALLOS_CLAVE_POR_USUARIO


def _anotar_fallo(usuario_id):
    with _candado:
        _fallos_clave.setdefault(usuario_id, deque()).append(time.monotonic())


def _validar_clave_nueva(clave):
    """Devuelve el texto del error o None si está bien."""
    if len(clave) < CLAVE_MINIMA:
        return f"La contraseña nueva tiene que tener al menos {CLAVE_MINIMA} caracteres"
    if len(clave) > 200:
        return "La contraseña es demasiado larga"
    return None


@auth_bp.post("/api/auth/cambiar-password")
@requiere_login()
def cambiar_password():
    u = g.usuario
    if _bloqueado_por_fallos(u.id):
        return jsonify({"error": "Demasiados intentos, probá de nuevo en un rato"}), 429

    datos = request.get_json(silent=True) or {}
    actual = datos.get("actual") or ""
    nueva = datos.get("nueva") or ""

    # 400 y no 401: el panel cierra la sesión con cualquier 401
    if not actual or not check_password_hash(u.password_hash, actual):
        _anotar_fallo(u.id)
        return jsonify({"error": "La contraseña actual no es correcta"}), 400

    error = _validar_clave_nueva(nueva)
    if error:
        return jsonify({"error": error}), 400
    if nueva == actual:
        return jsonify({"error": "La contraseña nueva tiene que ser distinta a la actual"}), 400

    u.password_hash = generate_password_hash(nueva)
    db.session.commit()
    with _candado:
        _fallos_clave.pop(u.id, None)
    return jsonify({"ok": True, "mensaje": "Listo, cambiaste tu contraseña"})


@auth_bp.get("/api/auth/usuarios")
@requiere_login("admin")
def listar_usuarios():
    """Para la pantalla de Usuarios: los que ya tienen rol (sin solicitudes pendientes)."""
    filas = (Usuario.query.filter(Usuario.rol != ROL_PENDIENTE)
             .order_by(Usuario.nombre).all())
    return jsonify([{**_usuario_json(u), "activo": bool(u.activo)} for u in filas])


@auth_bp.post("/api/auth/usuarios/<int:id_>/resetear-password")
@requiere_login("admin")
def resetear_password(id_):
    u = db.session.get(Usuario, id_)
    if not u or u.rol == ROL_PENDIENTE:
        return jsonify({"error": "No encontré ese usuario"}), 404
    if u.id == g.usuario.id:
        return jsonify({"error": "Para tu propia cuenta usá Cambiar contraseña"}), 400

    clave = "".join(secrets.choice(ALFABETO_CLAVE) for _ in range(LARGO_CLAVE_RESET))
    u.password_hash = generate_password_hash(clave)
    db.session.commit()
    with _candado:
        _fallos_clave.pop(u.id, None)
    log.info("El admin %s reseteó la contraseña del usuario %s", g.usuario.id, u.id)
    # se devuelve una sola vez; no queda guardada en ningún lado
    return jsonify({"ok": True, "id": u.id, "password": clave})
