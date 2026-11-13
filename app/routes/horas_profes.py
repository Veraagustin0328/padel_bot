"""Profes y horas: cuánto se le paga a cada profe en el mes. SOLO el dueño.

Acá hay plata y tarifas: todo con @requiere_login("dueno"). El encargado y los profes
reciben 403. La vista de cada profe con lo suyo va aparte (sin tarifas ajenas).
"""
import csv
import io
from decimal import Decimal

from flask import Blueprint, Response, jsonify, request

from app import horas_profes
from app.routes.auth import requiere_login

horas_profes_bp = Blueprint("horas_profes", __name__)


def _json(valor):
    """Decimal -> número para el panel (Flask los manda como texto)."""
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_json(v) for v in valor]
    return valor


def _mes_o_error():
    rango = horas_profes.leer_mes(request.args.get("mes"))
    if not rango:
        return None, (jsonify({"error": "El mes tiene que ser AAAA-MM"}), 400)
    return rango, None


@horas_profes_bp.get("/api/profes-horas")
@requiere_login("dueno")
def resumen():
    rango, error = _mes_o_error()
    if error:
        return error
    return jsonify(_json(horas_profes.resumen_mes(*rango)))


def _num(valor):
    # para Excel en castellano: coma decimal y sin ".00" de más
    if valor is None:
        return ""
    texto = f"{Decimal(valor):.2f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


@horas_profes_bp.get("/api/profes-horas/csv")
@requiere_login("dueno")
def exportar_csv():
    rango, error = _mes_o_error()
    if error:
        return error
    datos = horas_profes.resumen_mes(*rango)

    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";")
    w.writerow(["Profe", "Estado", "Fecha", "Hora", "Grupo", "Presentes", "Horas", "Tarifa", "Monto"])
    estados = (("clases", "Pagada"), ("sin_alumnos", "Sin alumnos (no se paga)"),
               ("pendientes", "Pendiente de confirmar"))
    for p in datos["profes"]:
        for clave, texto in estados:
            for c in p[clave]:
                w.writerow([p["nombre"], texto, c["fecha"], c["hora"], c["grupo"], c["presentes"],
                            _num(c["horas"]), _num(c.get("tarifa")), _num(c.get("monto"))])
    w.writerow([])
    w.writerow(["Profe", "Horas pagas", "Tarifa vigente", "Monto", "Horas pendientes", "Sin tarifa"])
    for p in datos["profes"]:
        w.writerow([p["nombre"], _num(p["horas"]), _num(p["tarifa"]), _num(p["monto"]),
                    _num(p["horas_pendientes"]), "si" if p["sin_tarifa"] else ""])
    w.writerow(["TOTAL", _num(datos["total_horas"]), "", _num(datos["total_monto"]), "", ""])

    mes = datos["desde"][:7]
    # BOM para que Excel lea bien las tildes
    return Response("﻿" + salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="horas_profes_{mes}.csv"'})
