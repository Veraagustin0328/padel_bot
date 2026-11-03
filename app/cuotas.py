"""Cálculo de la cuota mensual de un alumno a partir de sus clases fijas y la tabla de tarifas."""
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


def cargar_tarifas():
    """{(franja, tipo, personas, veces_por_semana): precio}"""
    return {
        (t.franja, t.tipo, t.personas, t.veces_por_semana): t.precio
        for t in Tarifa.query.filter_by(activa=True)
    }


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