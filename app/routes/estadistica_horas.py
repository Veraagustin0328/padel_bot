"""Estadística de horas: las horas de los profes por semana, día y franja. SOLO el dueño.

Sin plata: ni tarifas ni montos (eso está en Profes y horas). El encargado y los profes reciben 403.
"""
import csv
import io
from datetime import date

from flask import Blueprint, Response, jsonify, request

from app import estadistica_horas, horas_profes
from app.routes.auth import requiere_login

estadistica_horas_bp = Blueprint("estadistica_horas", __name__)

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
AMBITOS = {"adultos": "Adultos mañana", "adultos_tarde": "Adultos tarde", "sabados": "Sábados",
           "kids": "Kids", "kids_pro": "Kids Pro"}


def _datos():
    """(datos, None) o (None, respuesta de error)."""
    rango = horas_profes.leer_mes(request.args.get("mes"))
    if not rango:
        return None, (jsonify({"error": "El mes tiene que ser AAAA-MM"}), 400)
    return estadistica_horas.calcular(*rango), None


@estadistica_horas_bp.get("/api/estadistica-horas")
@requiere_login("dueno")
def ver():
    datos, error = _datos()
    return error or jsonify(datos)


def _num(valor):
    # para Excel en castellano: coma decimal; vacío si no hubo horas
    if valor is None:
        return ""
    return f"{valor:g}".replace(".", ",")


@estadistica_horas_bp.get("/api/estadistica-horas/csv")
@requiere_login("dueno")
def exportar_csv():
    datos, error = _datos()
    if error:
        return error
    nombres = [p["nombre"] for p in datos["profes"]]
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";")
    w.writerow([f"Horas de los profes - {datos['mes']}"])
    for s in datos["semanas"]:
        w.writerow([])
        lunes = date.fromisoformat(s["lunes"])
        w.writerow([f"Semana del {lunes.day:02d}/{lunes.month:02d}"])
        w.writerow(["Día", "Fecha", *nombres, "Total"])
        for d in s["dias"]:
            f = date.fromisoformat(d["fecha"])
            if not d["en_mes"]:
                w.writerow([DIAS[d["dia"]], f"{f.day:02d}/{f.month:02d}", *([""] * len(nombres)), "fuera del mes"])
                continue
            w.writerow([DIAS[d["dia"]], f"{f.day:02d}/{f.month:02d}", *map(_num, d["horas"]), _num(d["total"])])
        w.writerow(["Subtotal", "", *map(_num, s["subtotal"]), _num(s["total"])])
    w.writerow([])
    w.writerow(["Total del mes", "", *map(_num, datos["total_profes"]), _num(datos["total"])])

    w.writerow([])
    w.writerow(["Por franja", "Horas", "Clases", "Detalle por tipo"])
    for fr in datos["franjas"]:
        detalle = ", ".join(f"{t} {_num(h)}" for t, h in fr["por_tipo"].items())
        w.writerow([AMBITOS.get(fr["ambito"], fr["ambito"]), _num(fr["horas"]), fr["clases"], detalle])

    if datos["no_suman"]:
        w.writerow([])
        w.writerow(["No suman (informativo)", "Sin alumnos", "Pendientes de confirmar"])
        for p in datos["no_suman"]:
            w.writerow([p["nombre"], p["sin_alumnos"], p["pendientes"]])

    # BOM para que Excel lea bien las tildes
    return Response("﻿" + salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="estadistica_horas_{datos["mes"]}.csv"'})
