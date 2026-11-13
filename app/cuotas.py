"""Cálculo de la cuota mensual de un alumno a partir de sus clases fijas y la tabla de tarifas."""
from calendar import monthrange
from datetime import date

from sqlalchemy import or_

from app.models_academia import Clase, Inscripcion
from app.models_tarifas import Tarifa

FRANJA_POR_AMBITO = {
    "adultos": "manana",
    "adultos_tarde": "tarde",
    "sabados": "sabado",
    "kids": "kids",
    "kids_pro": "kids",
}

# Promo 2x1: solo en los horarios muertos que Gabi quiere llenar (lunes, miércoles y viernes de 9 a 12).
# dia_semana: 0 = lunes ... 5 = sábado
DIAS_PROMO_2X1 = (0, 2, 4)
HORA_PROMO_DESDE = 9
HORA_PROMO_HASTA = 12


def _es_promo(clase):
    return (
        clase.dia_semana in DIAS_PROMO_2X1
        and HORA_PROMO_DESDE <= clase.hora_inicio.hour < HORA_PROMO_HASTA
    )


def bucket_de(clase):
    """(franja, tipo de tarifa, personas) de una clase, o None si no sabemos cobrarla."""
    franja = FRANJA_POR_AMBITO.get(clase.ambito)
    if franja is None or clase.tipo == "otro":
        return None
    if clase.tipo == "grupal":
        if franja == "tarde":
            return (franja, "particular", 3)   # la tarde no tiene Modo Academia
        return (franja, "academia", 0)
    if clase.tipo == "particular_2":
        if franja == "manana" and _es_promo(clase):
            return (franja, "promo_2x1", 0)
        return (franja, "particular", 2)
    if clase.tipo == "particular":
        return (franja, "particular", 1)
    return None


def clases_del_mes(inicio: date, alumno_id: int | None = None) -> dict[int, list]:
    """{alumno_id: [clases activas en las que está anotado algún día de ese mes]}.
    'hasta' es el primer día que ya no va: si es el 1 del mes, ese mes ya no cuenta."""
    fin = date(inicio.year, inicio.month, monthrange(inicio.year, inicio.month)[1])
    clases = {c.id: c for c in Clase.query.filter(Clase.activa.is_(True)).all()}
    q = Inscripcion.query.filter(
        or_(Inscripcion.desde.is_(None), Inscripcion.desde <= fin),
        or_(Inscripcion.hasta.is_(None), Inscripcion.hasta > inicio),
    )
    if alumno_id is not None:
        q = q.filter(Inscripcion.alumno_id == alumno_id)
    por_alumno = {}
    for i in q.all():
        c = clases.get(i.clase_id)
        if c is not None and c not in por_alumno.setdefault(i.alumno_id, []):
            por_alumno[i.alumno_id].append(c)
    return por_alumno


def cargar_tarifas(fecha: date | None = None):
    """{(franja, tipo, personas, veces_por_semana): precio} que rige en esa fecha (por defecto hoy).
    Para una cuota se pasa el 1 del mes: un aumento posterior no toca los meses anteriores."""
    if fecha is None:
        from app.recuperaciones import hoy
        fecha = hoy()
    ultimas = {}
    filas = (Tarifa.query.filter(Tarifa.vigente_desde <= fecha)
             .order_by(Tarifa.vigente_desde, Tarifa.id))
    for t in filas:
        ultimas[(t.franja, t.tipo, t.personas, t.veces_por_semana)] = t  # la más nueva queda última
    return {k: t.precio for k, t in ultimas.items() if t.activa}


def precio_bucket(tarifas, franja, tipo, personas, veces):
    """(precio, nota). Si esa cantidad no figura en las placas, se arma sumando los precios que sí hay."""
    directo = tarifas.get((franja, tipo, personas, veces))
    if directo is not None:
        return directo, ""
    conocidos = sorted(v for (f, t, p, v) in tarifas if (f, t, p) == (franja, tipo, personas))
    if not conocidos:
        return None, "no hay tarifa para esta combinación"
    restante, total = veces, 0
    for v in sorted(conocidos, reverse=True):
        while restante >= v:
            total += tarifas[(franja, tipo, personas, v)]
            restante -= v
    return total, f"{veces} veces por semana no figura en las placas, se sumó con los precios que hay"


def cuota_de(clases, tarifas):
    """Cuota mensual de un alumno anotado en esas clases. Devuelve {total, lineas, avisos}."""
    grupos, avisos = {}, []
    for c in clases:
        b = bucket_de(c)
        if b is None:
            avisos.append(f"clase sin tarifa ({c.tipo}, {c.ambito})")
            continue
        grupos.setdefault(b, []).append(c)

    total, lineas = 0, []
    for (franja, tipo, personas), cs in sorted(grupos.items()):
        precio, nota = precio_bucket(tarifas, franja, tipo, personas, len(cs))
        nombre = f"{franja} {tipo}" + (f" de {personas}" if personas else "")
        if precio is None:
            avisos.append(f"{nombre} x{len(cs)}: {nota}")
            continue
        total += precio
        lineas.append(f"{nombre} x{len(cs)} = {precio}")
        if nota:
            avisos.append(f"{nombre} x{len(cs)}: {nota}")
    return {"total": total, "lineas": lineas, "avisos": avisos}