"""Plata del club: solo la ve el dueño. Helpers para filtrar en el backend lo que le llega al encargado."""
import re

from flask import g

ROL_DUENO = "dueno"
# "$25.000", "$ 1500", "$12,5": cualquier monto escrito en un texto
_PESOS = re.compile(r"\$\s?\d+(?:[.,]\d+)*")  # sin comerse el punto final de la oración
TAPADO = "$ (solo dueño)"


def es_dueno() -> bool:
    return getattr(g.get("usuario"), "rol", None) == ROL_DUENO


def sin_pesos(texto):
    """Tapa los montos de un texto (notificaciones, consultas) si quien mira no es el dueño."""
    if not texto or es_dueno():
        return texto
    return _PESOS.sub(TAPADO, texto)
