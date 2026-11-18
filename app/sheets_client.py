"""Conexión con la planilla de Google de la academia (service account + gspread)."""
import os
import threading
import time

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_gc = None
_planilla = None

# copia en memoria de lo leído, por proceso. Solo la usan las pantallas del panel que la piden
# (cache=True): el agente y todo lo que escribe sigue leyendo fresco. Cualquier escritura por
# pestana() borra la copia de esa pestaña, así después de una acción nunca se ve lo de antes.
# Lo que Gabi cambia a mano en la planilla tarda como mucho VIDA_CACHE en verse (o "Actualizar").
VIDA_CACHE = int(os.environ.get("PLANILLA_CACHE_SEG", "90"))
_copias = {}  # nombre -> (cuando, version, valores)
_hojas = {}   # nombre -> Worksheet, para no pedir la metadata de la planilla en cada lectura
_version = {}  # nombre -> cuántas veces se escribió; una lectura vieja no pisa una escritura nueva
_candado = threading.Lock()


def _cliente():
    global _gc
    if _gc is None:
        creds = Credentials.from_service_account_file(
            os.environ["GOOGLE_CREDENTIALS_FILE"], scopes=SCOPES
        )
        _gc = gspread.authorize(creds)
    return _gc


def abrir_planilla():
    global _planilla
    if _planilla is None:
        _planilla = _cliente().open_by_key(os.environ["GOOGLE_SHEET_ID"])
    return _planilla


def invalidar(nombre=None):
    """Borra la copia en memoria de esa pestaña (o de todas)."""
    with _candado:
        for n in [nombre] if nombre else list(_copias):
            _copias.pop(n, None)
            _version[n] = _version.get(n, 0) + 1


class _PestanaQueAvisa:
    """La pestaña de gspread tal cual, pero cada cosa que se le hace borra la copia en memoria
    (antes y después: si otro pedido leyó en el medio, tampoco queda lo viejo)."""

    def __init__(self, ws, nombre):
        self._ws, self._nombre = ws, nombre

    def __getattr__(self, attr):
        valor = getattr(self._ws, attr)
        if not callable(valor):
            return valor

        def envuelto(*args, **kwargs):
            invalidar(self._nombre)
            try:
                return valor(*args, **kwargs)
            finally:
                invalidar(self._nombre)
        return envuelto


def pestana(nombre, encabezados=None):
    """Devuelve la pestaña. Si no existe y le pasás encabezados, la crea.
    Es la puerta para escribir: todo lo que se haga con ella borra la copia en memoria."""
    planilla = abrir_planilla()
    invalidar(nombre)
    try:
        return _PestanaQueAvisa(planilla.worksheet(nombre), nombre)
    except gspread.WorksheetNotFound:
        if not encabezados:
            raise
        ws = planilla.add_worksheet(title=nombre, rows=1000, cols=len(encabezados))
        ws.append_row(encabezados)
        ws.freeze(rows=1)
        return _PestanaQueAvisa(ws, nombre)


def _leer_valores(nombre):
    """get_all_values con la hoja guardada (un pedido HTTP en vez de dos). Si la hoja guardada
    falla (la borraron o renombraron), se busca de nuevo una vez."""
    ws = _hojas.get(nombre)
    if ws is not None:
        try:
            return ws.get_all_values()
        except Exception:
            _hojas.pop(nombre, None)
    ws = abrir_planilla().worksheet(nombre)
    _hojas[nombre] = ws
    return ws.get_all_values()


def valores_pestana(nombre, cache=False):
    """Todas las celdas de la pestaña (lista de filas). cache=True: si hay una copia de hace menos de
    VIDA_CACHE segundos la usa. Siempre devuelve una copia, así nadie toca lo guardado."""
    if cache:
        with _candado:
            guardada = _copias.get(nombre)
        if guardada and time.monotonic() - guardada[0] < VIDA_CACHE:
            return [list(f) for f in guardada[2]]
    with _candado:
        version = _version.get(nombre, 0)
    valores = _leer_valores(nombre)
    with _candado:
        if _version.get(nombre, 0) == version:  # si se escribió mientras leía, no se guarda
            _copias[nombre] = (time.monotonic(), version, valores)
    return [list(f) for f in valores]


def leer_pestana(nombre, cache=False):
    """Lista de dicts con los encabezados de la fila 1. `_fila` = nº de fila en la hoja.
    cache=True solo para pantallas del panel que se pueden refrescar (ver valores_pestana)."""
    valores = valores_pestana(nombre, cache=cache)
    if not valores:
        return []
    encabezados = valores[0]
    filas = []
    for i, fila in enumerate(valores[1:], start=2):
        d = {"_fila": i}
        for col, enc in enumerate(encabezados):
            if enc.strip():
                d[enc.strip()] = fila[col] if col < len(fila) else ""
        filas.append(d)
    return filas
