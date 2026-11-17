"""Estadística de horas de los profes: las horas del mes por semana, día y profe. SOLO el dueño.

Sin plata: sale de horas_profes.resumen_mes (misma regla que Profes y horas, así los totales
dan igual) y acá se tira todo lo que sea tarifa o monto.
- Cuenta la dictada con al menos un presente; horas = duración / 60; el profe es el que la dio.
- Las "sin alumnos" y las "pendientes de confirmar" no suman: van aparte, solo la cantidad.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app import horas_profes
from app import models_academia as m

UN_DECIMAL = Decimal("0.1")
SIN_PROFE = "Sin profe asignado"


def redondear(valor):
    """Decimal -> número con 1 decimal como máximo (None si no hay nada)."""
    if valor is None:
        return None
    return float(Decimal(valor).quantize(UN_DECIMAL, ROUND_HALF_UP))


def calcular(desde, hasta):
    resumen = horas_profes.resumen_mes(desde, hasta)

    # columnas: los profes con horas en el mes, por nombre
    con_horas = [p for p in resumen["profes"] if p["clases"]]
    con_horas.sort(key=lambda p: (p["profesor_id"] is None, p["nombre"].lower()))
    columnas = [{"id": p["profesor_id"], "nombre": p["nombre"] or SIN_PROFE} for p in con_horas]
    col = {p["profesor_id"]: i for i, p in enumerate(con_horas)}

    # horas por (fecha, columna) y datos de cada clase para las franjas
    por_dia = defaultdict(lambda: defaultdict(Decimal))
    ids_clase = {c["clase_id"] for p in con_horas for c in p["clases"]}
    clases = {c.id: c for c in m.Clase.query.filter(m.Clase.id.in_(ids_clase or [0]))}
    franjas = defaultdict(lambda: {"horas": Decimal(0), "clases": 0, "por_tipo": defaultdict(Decimal)})
    for p in con_horas:
        i = col[p["profesor_id"]]
        for c in p["clases"]:
            f = date.fromisoformat(c["fecha"])
            por_dia[f][i] += c["horas"]
            clase = clases.get(c["clase_id"])
            fr = franjas[clase.ambito if clase else "otro"]
            fr["horas"] += c["horas"]
            fr["clases"] += 1
            fr["por_tipo"][c["tipo"] or "otro"] += c["horas"]

    # sábado y domingo solo si ese mes hubo horas esos días
    dias_semana = [0, 1, 2, 3, 4] + [d for d in (5, 6) if any(f.weekday() == d for f in por_dia)]

    n = len(columnas)
    total_profe = [Decimal(0)] * n
    semanas = []
    lunes = desde - timedelta(days=desde.weekday())
    while lunes <= hasta:
        subtotal = [Decimal(0)] * n
        filas = []
        for d in dias_semana:
            f = lunes + timedelta(days=d)
            en_mes = desde <= f <= hasta
            celdas = por_dia.get(f, {}) if en_mes else {}
            horas = [redondear(celdas[i]) if celdas.get(i) else None for i in range(n)]  # vacío, no 0
            for i, h in celdas.items():
                subtotal[i] += h
            filas.append({
                "fecha": f.isoformat(),
                "dia": d,
                "en_mes": en_mes,
                "horas": horas,
                "total": redondear(sum(celdas.values(), Decimal(0))) if celdas else None,
            })
        for i in range(n):
            total_profe[i] += subtotal[i]
        semanas.append({
            "lunes": lunes.isoformat(),
            "dias": filas,
            "subtotal": [redondear(s) if s else None for s in subtotal],
            "total": redondear(sum(subtotal, Decimal(0))),
        })
        lunes += timedelta(days=7)

    # lo que no suma, para que se entienda por qué un número no cuadra
    no_suman = [{
        "id": p["profesor_id"],
        "nombre": p["nombre"] or SIN_PROFE,
        "sin_alumnos": len(p["sin_alumnos"]),
        "pendientes": len(p["pendientes"]),
    } for p in resumen["profes"] if p["sin_alumnos"] or p["pendientes"]]
    no_suman.sort(key=lambda x: x["nombre"].lower())

    return {
        "mes": desde.isoformat()[:7],
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "profes": columnas,
        "semanas": semanas,
        "total_profes": [redondear(t) for t in total_profe],
        "total": redondear(sum(total_profe, Decimal(0))),
        "franjas": sorted(({
            "ambito": a,
            "horas": redondear(fr["horas"]),
            "clases": fr["clases"],
            "por_tipo": {t: redondear(h) for t, h in sorted(fr["por_tipo"].items())},
        } for a, fr in franjas.items()), key=lambda x: -x["horas"]),
        "no_suman": no_suman,
    }
