"""Cálculo de la cuota mensual de un alumno a partir de sus clases fijas y la tabla de tarifas."""
from calendar import monthrange
from datetime import date, timedelta

from sqlalchemy import or_

from app.models import Alumno
from app.models_academia import Clase, Inscripcion
from app.models_plataforma import Profesor
from app.models_tarifas import FRANJA_HEAD_COACH, Tarifa

FRANJA_POR_AMBITO = {
    "adultos": "manana",
    "adultos_tarde": "tarde",
    "sabados": "sabado",
    "kids": "kids",
    "kids_pro": "kids",
}

# Clases que no suman a la cuota ni avisan "sin tarifa": el físico de Kids Pro va con la de pádel
# del mismo grupo, que es la que se cobra (una sola cuota). Al profe se le paga la hora igual.
TIPOS_SIN_CUOTA = ("fisico",)

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


# Head Coach: las particulares de mañana (7 a 12) del profe titular marcado es_head_coach tienen tarifa propia.
# Las grupales con él siguen como Modo Academia. Se mira el titular de la clase, no quién la dio ese día.
# Y solo si el alumno tiene Alumno.tarifa_head_coach (los nuevos que pidieron con él): el resto paga normal.
HORA_HEAD_COACH_DESDE = 7
HORA_HEAD_COACH_HASTA = 12
# PROVISORIO, falta confirmar con la dueña: particular de 2 con el head coach en horario de promo.
# True = paga Head Coach; False = paga promo 2x1.
HEAD_COACH_ANTES_QUE_PROMO = True


def _es_head_coach(clase, head_coach):
    return (
        clase.profesor_id in head_coach
        and HORA_HEAD_COACH_DESDE <= clase.hora_inicio.hour < HORA_HEAD_COACH_HASTA
    )


def bucket_de(clase, head_coach=frozenset()):
    """(franja, tipo de tarifa, personas) de una clase, o None si no sabemos cobrarla.
    head_coach: ids de los profes head coach con tarifa vigente (vacío = se cobra como siempre)."""
    franja = FRANJA_POR_AMBITO.get(clase.ambito)
    if franja is None or clase.tipo == "otro":
        return None
    if clase.tipo == "grupal":
        # si la franja no tiene tarifa de academia cargada (hoy la tarde), queda "sin tarifa": nunca se cobra como otra cosa
        return (franja, "academia", 0)
    hc = franja == "manana" and _es_head_coach(clase, head_coach)
    if clase.tipo == "particular_2":
        promo = franja == "manana" and _es_promo(clase)
        if hc and (HEAD_COACH_ANTES_QUE_PROMO or not promo):
            return (FRANJA_HEAD_COACH, "particular", 2)
        if promo:
            return (franja, "promo_2x1", 0)
        return (franja, "particular", 2)
    if clase.tipo == "particular":
        return (FRANJA_HEAD_COACH if hc else franja, "particular", 1)
    return None


def profes_head_coach() -> frozenset:
    """Ids de los profes marcados es_head_coach (sin mirar si su tarifa ya rige)."""
    return frozenset(pid for (pid,) in Profesor.query.with_entities(Profesor.id).filter(
        Profesor.es_head_coach.is_(True)))


def es_clase_head_coach(clase, head_coach) -> bool:
    """La clase se cobraría a precio Head Coach a un alumno con la casilla prendida."""
    b = bucket_de(clase, head_coach) if head_coach else None
    return bool(b) and b[0] == FRANJA_HEAD_COACH


def _tramo_en_mes(clase, inicio: date, fin: date):
    """(desde, hasta) inclusive de la temporada de la clase dentro del mes, o None si no se da ese mes."""
    desde = max(inicio, clase.vigente_desde) if clase.vigente_desde else inicio
    hasta = min(fin, clase.vigente_hasta - timedelta(days=1)) if clase.vigente_hasta else fin
    return (desde, hasta) if desde <= hasta else None


def temporada_del_mes(clases: list, inicio: date, fin: date) -> list:
    """Mes con cambio de temporada (ej. kids: tarde hasta el 07/12, mañana desde el 07/12):
    se cobra solo la temporada que rige la mayor parte del mes, para no sumar las dos.
    - Las clases que cubren todo el mes (las de siempre) quedan.
    - Las que no se dan ese mes salen.
    - Las de temporada parcial se agrupan por su tramo y queda el tramo con más días
      (empate: el más nuevo, que es el que sigue)."""
    enteras, tramos = [], {}
    for c in clases:
        t = _tramo_en_mes(c, inicio, fin)
        if t is None:
            continue
        if t == (inicio, fin):
            enteras.append(c)
        else:
            tramos.setdefault(t, []).append(c)
    if not tramos:
        return enteras
    elegido = max(tramos, key=lambda t: ((t[1] - t[0]).days, t[0]))
    return enteras + tramos[elegido]


def clases_del_mes(inicio: date, alumno_id: int | None = None) -> dict[int, list]:
    """{alumno_id: [clases activas en las que está anotado algún día de ese mes]}.
    'hasta' es el primer día que ya no va: si es el 1 del mes, ese mes ya no cuenta.
    Si el mes tiene cambio de temporada, quedan solo las de la que rige más días (temporada_del_mes)."""
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
    # lista vacía igual que antes (queda en "sin precio" al generar el mes)
    return {aid: temporada_del_mes(cs, inicio, fin) for aid, cs in por_alumno.items()}


class Tarifas(dict):
    """{(franja, tipo, personas, veces_por_semana): precio}, más los ids de los profes head coach.
    head_coach queda vacío si en esa fecha no rige ninguna tarifa de head coach: así se cobra como antes."""
    head_coach = frozenset()


def cargar_tarifas(fecha: date | None = None):
    """Tarifas que rigen en esa fecha (por defecto hoy).
    Para una cuota se pasa el 1 del mes: un aumento posterior no toca los meses anteriores."""
    if fecha is None:
        from app.recuperaciones import hoy
        fecha = hoy()
    ultimas = {}
    filas = (Tarifa.query.filter(Tarifa.vigente_desde <= fecha)
             .order_by(Tarifa.vigente_desde, Tarifa.id))
    for t in filas:
        ultimas[(t.franja, t.tipo, t.personas, t.veces_por_semana)] = t  # la más nueva queda última
    tarifas = Tarifas({k: t.precio for k, t in ultimas.items() if t.activa})
    if any(k[0] == FRANJA_HEAD_COACH for k in tarifas):
        tarifas.head_coach = profes_head_coach()
    return tarifas


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


SIN_TARIFA = "SIN TARIFA"  # marca en el detalle de la cuota, el panel la resalta


def con_tarifa_head_coach(alumno_ids) -> set:
    """De esos alumnos, los que tienen la casilla Tarifa Head Coach prendida (una sola consulta)."""
    ids = [a for a in alumno_ids if a is not None]
    if not ids:
        return set()
    return {aid for (aid,) in Alumno.query.with_entities(Alumno.id).filter(
        Alumno.id.in_(ids), Alumno.tarifa_head_coach.is_(True))}


def cuota_de(clases, tarifas, tarifa_head_coach=False):
    """Cuota mensual de un alumno anotado en esas clases. Devuelve {total, lineas, avisos, sin_tarifa}.
    sin_tarifa = True si alguna clase no tiene precio: esa parte no se cobra y lo tiene que ver el encargado.
    tarifa_head_coach: la casilla del alumno. Apagada = se cobra sin Head Coach (particular normal o 2x1)."""
    grupos, avisos, sin_tarifa = {}, [], False
    head_coach = getattr(tarifas, "head_coach", frozenset()) if tarifa_head_coach else frozenset()
    for c in clases:
        if c.tipo in TIPOS_SIN_CUOTA:
            continue
        b = bucket_de(c, head_coach)
        if b is None:
            avisos.append(f"{SIN_TARIFA}: clase {c.tipo} de {c.ambito}, no se cobró")
            sin_tarifa = True
            continue
        grupos.setdefault(b, []).append(c)

    total, lineas = 0, []
    for (franja, tipo, personas), cs in sorted(grupos.items()):
        precio, nota = precio_bucket(tarifas, franja, tipo, personas, len(cs))
        nombre = f"{franja} {tipo}" + (f" de {personas}" if personas else "")
        if precio is None:
            avisos.append(f"{SIN_TARIFA}: {nombre} x{len(cs)}, no se cobró")
            sin_tarifa = True
            continue
        total += precio
        lineas.append(f"{nombre} x{len(cs)} = {precio}")
        if nota:
            avisos.append(f"{nombre} x{len(cs)}: {nota}")
    return {"total": total, "lineas": lineas, "avisos": avisos, "sin_tarifa": sin_tarifa}