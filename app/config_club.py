"""config_academia leída una sola vez por pedido.

Antes cada niveles() o regla() hacía su propia consulta: el identity map de SQLAlchemy
no guarda las filas que nadie retiene, así que db.session.get volvía a la base cada vez
(/api/clases llegaba a 47 consultas solo de config). Ahora se trae la tabla entera
la primera vez y queda en flask.g hasta que termina el pedido.

Ojo: si algún día una ruta escribe config_academia, que llame a olvidar() después.
"""
from flask import g

from app.extensions import db
from app.models_academia import ConfigAcademia


def _todas() -> dict:
    cache = getattr(g, "_config_club", None)
    if cache is None:
        cache = {clave: valor for clave, valor in db.session.query(ConfigAcademia.clave, ConfigAcademia.valor)}
        g._config_club = cache
    return cache


def valor(clave):
    """El texto guardado (JSON) de esa clave, o None si no está cargada."""
    return _todas().get(clave)


def olvidar():
    """Tira la copia del pedido, por si se escribió config en el medio."""
    g.pop("_config_club", None)
