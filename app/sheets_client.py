"""Conexión con la planilla de Google de la academia (service account + gspread)."""
import os

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_gc = None
_planilla = None


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


def pestana(nombre, encabezados=None):
    """Devuelve la pestaña. Si no existe y le pasás encabezados, la crea."""
    planilla = abrir_planilla()
    try:
        return planilla.worksheet(nombre)
    except gspread.WorksheetNotFound:
        if not encabezados:
            raise
        ws = planilla.add_worksheet(title=nombre, rows=1000, cols=len(encabezados))
        ws.append_row(encabezados)
        ws.freeze(rows=1)
        return ws


def leer_pestana(nombre):
    """Lista de dicts con los encabezados de la fila 1. `_fila` = nº de fila en la hoja."""
    ws = pestana(nombre)
    valores = ws.get_all_values()
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