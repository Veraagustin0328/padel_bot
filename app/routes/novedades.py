"""
Novedades del panel: avisos que se ven en el Inicio.
GET lo puede pedir cualquiera logueado y trae solo las vigentes.
Crear, editar y borrar: dueño y encargado.
Las vencidas no se muestran pero no se borran solas (quedan de historial).
"""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, request, jsonify, g

from app.extensions import db
from app.models_academia import Novedad, TIPOS_NOVEDAD
from app.routes.auth import requiere_login

novedades_bp = Blueprint("novedades", __name__)

GESTION = ("dueno", "encargado")
TITULO_MAX = 120
TEXTO_MAX = 2000
# configurable por club; por defecto hora argentina
ZONA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Argentina/Buenos_Aires"))


def _hoy():
    # en Render el server está en UTC: a las 22 hs de acá ya sería mañana
    return datetime.now(ZONA).date()


def _json(n):
    hoy = _hoy()
    return {
        "id": n.id,
        "titulo": n.titulo,
        "texto": n.texto,
        "tipo": n.tipo,
        "publicada_desde": n.publicada_desde.isoformat() + "Z" if n.publicada_desde else None,
        "visible_hasta": n.visible_hasta.isoformat() if n.visible_hasta else None,
        "vigente": n.visible_hasta is None or n.visible_hasta >= hoy,
        "creada_por": n.creada_por,
    }


def _vigentes(consulta):
    hoy = _hoy()
    return consulta.filter(
        Novedad.publicada_desde <= datetime.utcnow(),
        db.or_(Novedad.visible_hasta.is_(None), Novedad.visible_hasta >= hoy),
    )


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
        if not texto or len(texto) > TEXTO_MAX:
            return None, f"Poné el texto (hasta {TEXTO_MAX} letras)"
        campos["texto"] = texto

    if not parcial or "tipo" in datos:
        tipo = (datos.get("tipo") or "aviso").strip()
        if tipo not in TIPOS_NOVEDAD:
            return None, "Elegí un tipo válido"
        campos["tipo"] = tipo

    if "visible_hasta" in datos:
        valor = datos.get("visible_hasta")
        if valor in (None, ""):
            campos["visible_hasta"] = None
        else:
            try:
                hasta = date.fromisoformat(str(valor))
            except ValueError:
                return None, "La fecha de \"se muestra hasta\" no es válida"
            if hasta < _hoy():
                return None, "La fecha de \"se muestra hasta\" ya pasó"
            campos["visible_hasta"] = hasta

    return campos, None


@novedades_bp.get("/api/novedades")
@requiere_login()
def listar():
    consulta = Novedad.query
    # ?todas=1 es para la pantalla de gestión: ve también las vencidas, para borrarlas
    todas = request.args.get("todas") == "1" and g.usuario.rol in GESTION
    if not todas:
        consulta = _vigentes(consulta)
    filas = consulta.order_by(Novedad.publicada_desde.desc(), Novedad.id.desc()).all()
    return jsonify([_json(n) for n in filas])


@novedades_bp.get("/api/novedades/tipos")
@requiere_login()
def tipos():
    return jsonify(list(TIPOS_NOVEDAD))


@novedades_bp.post("/api/novedades")
@requiere_login("encargado")
def crear():
    campos, error = _validar(request.get_json(silent=True) or {}, parcial=False)
    if error:
        return _error(error)
    n = Novedad(creada_por=g.usuario.id, **campos)
    db.session.add(n)
    db.session.commit()
    return jsonify(_json(n)), 201


@novedades_bp.patch("/api/novedades/<int:id_>")
@requiere_login("encargado")
def editar(id_):
    n = db.session.get(Novedad, id_)
    if not n:
        return _error("No encontré esa novedad", 404)
    campos, error = _validar(request.get_json(silent=True) or {}, parcial=True)
    if error:
        return _error(error)
    for clave, valor in campos.items():
        setattr(n, clave, valor)
    db.session.commit()
    return jsonify(_json(n))


@novedades_bp.delete("/api/novedades/<int:id_>")
@requiere_login("encargado")
def borrar(id_):
    n = db.session.get(Novedad, id_)
    if not n:
        return _error("No encontré esa novedad", 404)
    db.session.delete(n)
    db.session.commit()
    return jsonify({"ok": True, "id": id_})
