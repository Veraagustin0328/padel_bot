"""Alumnos para el panel.
Por ahora lee la pestaña "listado alumnos" de la planilla de Gabi (solo lectura).
Cuando los alumnos pasen a Neon, cambia esta función y la pantalla queda igual.
"""
import re

from flask import Blueprint, jsonify

from app import planilla
from app.routes.auth import requiere_login
from app.sheets_client import pestana

alumnos_bp = Blueprint("alumnos_panel", __name__)


def _dinero(txt):
    """' $150.000,00' -> 150000. Si no hay número devuelve None."""
    s = str(txt or "").replace(".", "")
    s = re.sub(r"[^\d,]", "", s)
    if not re.search(r"\d", s):
        return None
    n = float(s.replace(",", "."))
    return int(n) if n == int(n) else n


@alumnos_bp.get("/api/alumnos")
@requiere_login("encargado")
def listar():
    try:
        filas = pestana(planilla.TAB_ALUMNOS).get_all_values()
    except Exception as e:
        return jsonify({"error": f"No pude leer la planilla: {e}"}), 502
    if not filas:
        return jsonify([])

    enc = [str(h).strip().upper() for h in filas[0]]

    def col(nombre):
        return enc.index(nombre) if nombre in enc else None

    def val(fila, nombre):
        i = col(nombre)
        return str(fila[i]).strip() if i is not None and i < len(fila) else ""

    salida = []
    for n, fila in enumerate(filas[1:], start=2):
        nombre = val(fila, "NOMBRE")
        if not nombre:
            continue
        meses = {}
        for m in planilla.MESES:
            texto = val(fila, m)
            meses[m] = {"texto": texto, "monto": _dinero(texto)}
        salida.append({
            "id": n,
            "numero": val(fila, "N°"),
            "nombre": nombre,
            "edad": val(fila, "EDAD"),
            "cat": val(fila, "CAT"),
            "al_dia": val(fila, "AL DIA"),
            "mes_inicio": val(fila, "MES DE INICIO"),
            "nuevo": val(fila, "NUEVO"),
            "planilla": val(fila, "PLANILLA"),
            "estado": val(fila, "ESTADO"),
            "mes_baja": val(fila, "MES DE BAJA"),
            "motivo": val(fila, "MOTIVO"),
            "meses": meses,
        })
    return jsonify(salida)