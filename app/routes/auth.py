"""
Login del panel. Devuelve un token (JWT) que el frontend manda en cada pedido:
    Authorization: Bearer <token>
Las rutas protegidas usan el decorador @requiere_login.

También está el registro por link: la cuenta queda pendiente hasta que el dueño o un encargado
la aprueba desde Solicitudes (app/routes/solicitudes.py). El estado va en
usuario_perfil, así la tabla usuarios no se toca.
"""
import os
import re
import logging
import secrets
import datetime

import jwt
from flask import Blueprint, request, jsonify, g
from functools import wraps
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.limites import Ventana, numero_de_entorno
from app.models_plataforma import Profesor, Usuario
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
# el dueño entra a todo; el encargado (en el panel se ve como "Admin") a casi todo menos la plata
ROL_DUENO = "dueno"
ROLES_ALTOS = ("dueno", "encargado")  # estos solo los da o los toca el dueño
# "Ver como profe": el dueño mira la pantalla de un profe. Va en este header en cada pedido
HEADER_VER_COMO = "X-Ver-Como"
METODOS_LECTURA = ("GET", "HEAD", "OPTIONS")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# cambio de clave: cuántas veces puede errarle a la actual antes de frenarlo
FALLOS_CLAVE_POR_USUARIO = 5
VENTANA_FALLOS_SEGUNDOS = 15 * 60
# login: fallos por email y por IP en la ventana; se cambian con variables de entorno
LOGIN_FALLOS_POR_EMAIL = numero_de_entorno("LOGIN_FALLOS_POR_EMAIL", 5)
LOGIN_FALLOS_POR_IP = numero_de_entorno("LOGIN_FALLOS_POR_IP", 20)
LOGIN_VENTANA_SEGUNDOS = numero_de_entorno("LOGIN_VENTANA_MINUTOS", 15) * 60
MENSAJE_DEMASIADOS = "Demasiados intentos. Probá de nuevo en unos minutos."
# clave que genera el reset: sin letras que se confunden (0/O, 1/l/I)
ALFABETO_CLAVE = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LARGO_CLAVE_RESET = 12


# todos en memoria (ver app/limites.py): con un solo proceso alcanza
_registros_por_ip = Ventana(REGISTROS_POR_IP, VENTANA_SEGUNDOS)
_registros_totales = Ventana(REGISTROS_TOTALES, VENTANA_SEGUNDOS)
_fallos_clave = Ventana(FALLOS_CLAVE_POR_USUARIO, VENTANA_FALLOS_SEGUNDOS)
_login_por_email = Ventana(LOGIN_FALLOS_POR_EMAIL, LOGIN_VENTANA_SEGUNDOS)
_login_por_ip = Ventana(LOGIN_FALLOS_POR_IP, LOGIN_VENTANA_SEGUNDOS)

# headers que pone Cloudflare (adelante de Render) con la IP real; el cliente no los puede pisar
HEADERS_IP = [h.strip() for h in os.environ.get(
    "IP_HEADERS", "True-Client-IP,CF-Connecting-IP").split(",") if h.strip()]
_avise_sin_header_ip = False


def _ip_cliente():
    """IP del que pega. En Render el primer valor de X-Forwarded-For lo puede inventar el cliente
    (el proxy agrega, no reemplaza), así que primero miro los headers de Cloudflare."""
    global _avise_sin_header_ip
    if not os.environ.get("RENDER"):
        return request.remote_addr or "?"  # en la PC no hay proxy
    for nombre in HEADERS_IP:
        valor = request.headers.get(nombre, "").strip()
        if valor:
            return valor
    if not _avise_sin_header_ip:
        _avise_sin_header_ip = True
        log.warning("No llegó ningún header de IP (%s): uso X-Forwarded-For", ", ".join(HEADERS_IP))
    reenviada = request.headers.get("X-Forwarded-For", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.remote_addr or "?"


def _demasiados(segundos):
    resp = jsonify({"error": MENSAJE_DEMASIADOS})
    resp.headers["Retry-After"] = str(segundos)
    return resp, 429


_hash_de_relleno = None


def _clave_de_relleno(password):
    """Con un email que no existe igual se chequea un hash, así tarda lo mismo y no se nota."""
    global _hash_de_relleno
    if _hash_de_relleno is None:
        _hash_de_relleno = generate_password_hash(secrets.token_hex(16))
    check_password_hash(_hash_de_relleno, password)
    return False


def _email_clave(u):
    return (u.email or "").strip().lower()  # igual que lo arma el login


def _secreto():
    secreto = os.environ.get("JWT_SECRET", "")
    if not secreto:
        raise RuntimeError("Falta la variable de entorno JWT_SECRET")
    return secreto


# con la clave temporal solo puede ver quién es y cambiarla (lo demás da 403)
RUTAS_CON_CLAVE_TEMPORAL = {"auth.yo", "auth.cambiar_password"}


def _perfil(u, crear=False):
    perfil = db.session.get(UsuarioPerfil, u.id)
    if not perfil and crear:  # los usuarios de antes no tienen perfil
        perfil = UsuarioPerfil(usuario_id=u.id, estado="activo", creado_via="panel")
        db.session.add(perfil)
    return perfil


def _debe_cambiar(u):
    perfil = _perfil(u)
    return bool(perfil and perfil.debe_cambiar_clave)


def crear_token(usuario, cambiar=False):
    ahora = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(usuario.id),
        "rol": usuario.rol,
        "iat": ahora,
        "exp": ahora + datetime.timedelta(hours=HORAS_DE_SESION),
    }
    if cambiar:
        payload["cambiar"] = True  # va en el token: así no consulto la base en cada pedido
    return jwt.encode(payload, _secreto(), algorithm="HS256")


def _usuario_json(u, cambiar=False):
    # profesor_id: el panel muestra "Mis clases" solo si la cuenta está vinculada a un profe
    return {"id": u.id, "nombre": u.nombre, "email": u.email, "rol": u.rol,
            "profesor_id": u.profesor_id, "debe_cambiar_clave": cambiar}


def _ver_como(usuario):
    """Lee el header de "Ver como". Devuelve (profesor o None, respuesta de error o None).
    Solo el dueño, y solo lectura: cualquier escritura en ese modo se rechaza acá, para todas las rutas."""
    valor = (request.headers.get(HEADER_VER_COMO) or "").strip()
    if not valor:
        return None, None
    if usuario.rol != ROL_DUENO:
        return None, (jsonify({"error": "Solo el dueño puede ver como otro profe"}), 403)
    if request.method not in METODOS_LECTURA:
        return None, (jsonify({"error": "Estás viendo como otro profe: es solo lectura"}), 403)
    try:
        profe = db.session.get(Profesor, int(valor))
    except ValueError:
        profe = None
    if not profe:
        return None, (jsonify({"error": "No encontré ese profe"}), 404)
    return profe, None


def requiere_login(*roles):
    """
    @requiere_login()                -> cualquier usuario logueado
    @requiere_login("encargado")     -> encargado o dueño (el dueño entra siempre)
    @requiere_login("dueno")         -> solo el dueño (plata)
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
            if datos.get("cambiar") and request.endpoint not in RUTAS_CON_CLAVE_TEMPORAL:
                return jsonify({"error": "Antes de seguir tenés que cambiar la contraseña", "cambiar_clave": True}), 403
            if roles and usuario.rol != ROL_DUENO and usuario.rol not in roles:
                return jsonify({"error": "No tenés permiso para esto"}), 403

            profe, error = _ver_como(usuario)
            if error:
                return error
            g.usuario = usuario
            g.ver_como = profe  # None = el usuario se ve a sí mismo
            return f(*args, **kwargs)
        # queda anotado quien entra, para la prueba de humo (no cambia nada del permiso)
        envoltura.roles_permitidos = roles
        return envoltura
    return decorador


def puede_tocar_rol(actor, rol):
    """El encargado solo maneja profe, jugador y tutor. Dueño y encargado los asigna el dueño."""
    return actor.rol == ROL_DUENO or rol not in ROLES_ALTOS


@auth_bp.post("/api/auth/login")
def login():
    datos = request.get_json(silent=True) or {}
    email = (datos.get("email") or "").strip().lower()
    password = datos.get("password") or ""
    ip = _ip_cliente()

    # se frena antes de mirar la clave, y el mensaje es el mismo exista o no el email
    espera = max(_login_por_email.espera(email), _login_por_ip.espera(ip))
    if espera:
        log.warning("Login frenado por demasiados intentos desde %s", ip)
        return _demasiados(espera)

    usuario = Usuario.query.filter_by(email=email).first()
    if usuario:
        clave_ok = check_password_hash(usuario.password_hash, password)
    else:
        clave_ok = _clave_de_relleno(password)

    # solo con la clave correcta le contamos que está pendiente, así no se puede
    # averiguar qué mails se registraron. Los usuarios de siempre no tienen perfil: siguen igual
    if clave_ok and not usuario.activo:
        perfil = db.session.get(UsuarioPerfil, usuario.id)
        if perfil and perfil.estado == "pendiente":
            return jsonify({"error": "Tu cuenta está pendiente de aprobación"}), 403
        if perfil and perfil.estado == "rechazado":
            return jsonify({"error": "Tu solicitud de acceso no fue aprobada"}), 403

    # mismo mensaje si falla el mail o la clave, así no se sabe cuál existe
    if not clave_ok:
        _login_por_email.anotar(email)
        _login_por_ip.anotar(ip)
        return jsonify({"error": "Email o contraseña incorrectos"}), 401
    if not usuario.activo:  # clave bien pero dado de baja: no cuenta como fallo
        return jsonify({"error": "Email o contraseña incorrectos"}), 401

    _login_por_email.borrar(email)  # entró bien: arranca de cero
    cambiar = _debe_cambiar(usuario)
    return jsonify({"token": crear_token(usuario, cambiar), "usuario": _usuario_json(usuario, cambiar)})


@auth_bp.get("/api/auth/me")
@requiere_login()
def yo():
    return jsonify(_usuario_json(g.usuario, _debe_cambiar(g.usuario)))


# ---------- registro por link ----------

@auth_bp.post("/api/auth/registro")
def registro():
    # acá cuenta cada intento, no solo los fallidos: por IP y en total, por si rotan IPs
    ip = _ip_cliente()
    espera = max(_registros_por_ip.espera(ip), _registros_totales.espera("todos"))
    if espera:
        return _demasiados(espera)
    _registros_por_ip.anotar(ip)
    _registros_totales.anotar("todos")

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

    # aviso al dueño/encargado con el mismo sistema de notificaciones del agente
    # el usuario ya quedó guardado: si el aviso falla, solo se loguea
    try:
        from app.llm.agent import _notificar
        _notificar(f"Nueva solicitud de acceso al panel: {nombre} ({email})", tipo="solicitud_acceso")
    except Exception:
        db.session.rollback()
        log.exception("No pude avisar la solicitud de %s", email)

    return jsonify({"ok": True, "mensaje": "Listo, tu solicitud quedó pendiente de aprobación"}), 201


# ---------- cambio y reset de contraseña ----------

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
    espera = _fallos_clave.espera(u.id)
    if espera:
        return _demasiados(espera)

    datos = request.get_json(silent=True) or {}
    actual = datos.get("actual") or ""
    nueva = datos.get("nueva") or ""

    # 400 y no 401: el panel cierra la sesión con cualquier 401
    if not actual or not check_password_hash(u.password_hash, actual):
        _fallos_clave.anotar(u.id)
        return jsonify({"error": "La contraseña actual no es correcta"}), 400

    error = _validar_clave_nueva(nueva)
    if error:
        return jsonify({"error": error}), 400
    if nueva == actual:
        return jsonify({"error": "La contraseña nueva tiene que ser distinta a la actual"}), 400

    u.password_hash = generate_password_hash(nueva)
    perfil = _perfil(u)
    if perfil:
        perfil.debe_cambiar_clave = False
    db.session.commit()
    _fallos_clave.borrar(u.id)
    # token nuevo sin la marca de clave temporal, así sigue sin volver a entrar
    return jsonify({"ok": True, "mensaje": "Listo, cambiaste tu contraseña",
                    "token": crear_token(u), "usuario": _usuario_json(u)})


@auth_bp.get("/api/auth/usuarios")
@requiere_login("encargado")
def listar_usuarios():
    """Para la pantalla de Usuarios: los que ya tienen rol (sin solicitudes pendientes)."""
    filas = (Usuario.query.filter(Usuario.rol != ROL_PENDIENTE)
             .order_by(Usuario.nombre).all())
    yo = g.usuario
    return jsonify([
        {**_usuario_json(u), "activo": bool(u.activo),
         "puede_resetear": u.id != yo.id and puede_tocar_rol(yo, u.rol),
         # solo se lo muestro a quien lo puede destrabar
         "bloqueado": puede_tocar_rol(yo, u.rol) and _login_por_email.bloqueado(_email_clave(u))}
        for u in filas
    ])


@auth_bp.post("/api/auth/usuarios/<int:id_>/resetear-password")
@requiere_login("encargado")
def resetear_password(id_):
    u = db.session.get(Usuario, id_)
    if not u or u.rol == ROL_PENDIENTE:
        return jsonify({"error": "No encontré ese usuario"}), 404
    if u.id == g.usuario.id:
        return jsonify({"error": "Para tu propia cuenta usá Cambiar contraseña"}), 400
    if not puede_tocar_rol(g.usuario, u.rol):
        return jsonify({"error": "La contraseña de un dueño o un admin solo la resetea el dueño"}), 403

    clave = "".join(secrets.choice(ALFABETO_CLAVE) for _ in range(LARGO_CLAVE_RESET))
    u.password_hash = generate_password_hash(clave)
    _perfil(u, crear=True).debe_cambiar_clave = True  # la clave del reset es temporal
    db.session.commit()
    _fallos_clave.borrar(u.id)
    _login_por_email.borrar(_email_clave(u))  # con la clave nueva tiene que poder entrar ya
    log.info("El usuario %s reseteó la contraseña del usuario %s", g.usuario.id, u.id)
    # se devuelve una sola vez; no queda guardada en ningún lado
    return jsonify({"ok": True, "id": u.id, "password": clave})


@auth_bp.post("/api/auth/usuarios/<int:id_>/desbloquear")
@requiere_login("encargado")
def desbloquear(id_):
    """Destraba el login de alguien que se pasó de intentos, sin tocarle la clave."""
    u = db.session.get(Usuario, id_)
    if not u or u.rol == ROL_PENDIENTE:
        return jsonify({"error": "No encontré ese usuario"}), 404
    if not puede_tocar_rol(g.usuario, u.rol):
        return jsonify({"error": "A un dueño o un admin solo lo destraba el dueño"}), 403
    _login_por_email.borrar(_email_clave(u))
    log.info("El usuario %s destrabó el login del usuario %s", g.usuario.id, u.id)
    return jsonify({"ok": True, "id": u.id})
