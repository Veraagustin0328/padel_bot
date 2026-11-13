"""Horas y plata de los profes por mes. Solo lo usa el dueño (y después cada profe lo suyo).

Reglas:
- Se paga la hora si la clase se dictó (hay ClaseDictada) y vino al menos 1 presente.
- Se le paga al que la dio: ClaseDictada.profesor_id.
- Horas = duración de la clase / 60.
- La tarifa es la vigente en la fecha de cada clase (valores_hora, con historial).
- Dictada y todos marcados ausentes: no se paga, va aparte como "sin alumnos".
- Pendiente de confirmar: dictada sin presentes con gente todavía sin marcar, o clase
  de la grilla ya pasada que nadie marcó. No suma hasta que haya un presente.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_

from app import models_academia as m
from app.extensions import db
from app.models_plataforma import Profesor, ValorHora

CENTAVOS = Decimal("0.01")

TIPOS_TEXTO = {"grupal": "Grupal", "particular": "Particular", "particular_2": "Particular x2", "otro": "Otro"}


def ahora_ar():
    # misma hora que el resto (Argentina, UTC-3)
    return datetime.now(timezone(timedelta(hours=-3))).replace(tzinfo=None)


def leer_mes(texto):
    """'AAAA-MM' -> (primer día, último día). Vacío = el mes de hoy. Mal escrito -> None."""
    if not texto:
        hoy = ahora_ar().date()
        anio, mes = hoy.year, hoy.month
    else:
        try:
            anio, mes = (int(x) for x in str(texto).split("-"))
            date(anio, mes, 1)
        except (TypeError, ValueError):
            return None
    return date(anio, mes, 1), date(anio, mes, monthrange(anio, mes)[1])


def _horas(clase):
    return (Decimal(clase.duracion_min or 60) / 60).quantize(CENTAVOS, ROUND_HALF_UP)


def _grupo(clase):
    partes = [TIPOS_TEXTO.get(clase.tipo, clase.tipo or "")]
    if clase.nivel:
        partes.append(clase.nivel)
    return " ".join(p for p in partes if p)


def _fechas_de(clase, desde, hasta):
    """Las fechas del rango en que cae la clase (por día de la semana)."""
    f = desde + timedelta(days=(clase.dia_semana - desde.weekday()) % 7)
    while f <= hasta:
        yield f
        f += timedelta(days=7)


# ---------- quiénes tenían que venir ----------

def _esperados(clases, desde, hasta):
    """{(clase_id, fecha): set(alumno_id)} de los que tenían que venir.
    Es la versión en bloque de recuperaciones.alumnos_del_dia (fijos - faltas - viajes
    + reemplazos + recuperan), con 4 consultas para todo el mes en vez de 4 por clase."""
    ids = [c.id for c in clases]
    if not ids:
        return {}

    insc = defaultdict(list)  # clase_id -> [(alumno, desde, hasta)]
    for i in m.Inscripcion.query.filter(
            m.Inscripcion.clase_id.in_(ids), m.Inscripcion.desde <= hasta,
            or_(m.Inscripcion.hasta.is_(None), m.Inscripcion.hasta > desde)):
        insc[i.clase_id].append((i.alumno_id, i.desde, i.hasta))

    lapsos = m.AusenciaLapso.query.filter(
        m.AusenciaLapso.estado == "confirmado", m.AusenciaLapso.desde <= hasta,
        m.AusenciaLapso.hasta >= desde,
        or_(m.AusenciaLapso.clase_id.is_(None), m.AusenciaLapso.clase_id.in_(ids))).all()

    faltas = defaultdict(set)
    for a in m.Ausencia.query.filter(m.Ausencia.clase_id.in_(ids), m.Ausencia.fecha.between(desde, hasta)):
        faltas[(a.clase_id, a.fecha)].add(a.alumno_id)

    recuperan = defaultdict(set)
    for r in m.RecuperacionClase.query.filter(
            m.RecuperacionClase.clase_id.in_(ids), m.RecuperacionClase.estado == "confirmada",
            m.RecuperacionClase.fecha.between(desde, hasta)):
        recuperan[(r.clase_id, r.fecha)].add(r.alumno_id)

    salida = {}
    for c in clases:
        for f in _fechas_de(c, desde, hasta):
            # 'hasta' de la inscripción es el primer día que ya no está
            fijos = {a for a, d, h in insc[c.id] if d <= f and (h is None or h > f)}
            no_vienen, reemplazos = set(), set()
            for lap in lapsos:
                if lap.alumno_id in fijos and lap.desde <= f <= lap.hasta and lap.clase_id in (None, c.id):
                    no_vienen.add(lap.alumno_id)
                    if lap.reemplazo_alumno_id:
                        reemplazos.add(lap.reemplazo_alumno_id)
            no_vienen |= faltas[(c.id, f)] & fijos
            salida[(c.id, f)] = (fijos - no_vienen) | reemplazos | recuperan[(c.id, f)]
    return salida


# ---------- tarifas ----------

def _tarifas(profesor_ids):
    """{profesor_id: [ValorHora...]} solo de esos profes (nunca la fila sin profe)."""
    salida = defaultdict(list)
    if profesor_ids:
        for v in ValorHora.query.filter(ValorHora.profesor_id.in_(profesor_ids)).order_by(
                ValorHora.vigente_desde.desc()):
            salida[v.profesor_id].append(v)
    return salida


def tarifa_en(filas, fecha):
    """La tarifa vigente en esa fecha, o None si no hay."""
    for v in filas:  # vienen de la más nueva a la más vieja
        if v.vigente_desde <= fecha and (v.vigente_hasta is None or v.vigente_hasta >= fecha):
            return Decimal(v.monto)
    return None


# ---------- el cálculo ----------

def resumen_mes(desde, hasta, profesor_id=None):
    """Todo el mes, por profe. profesor_id = solo ese profe (para la vista de cada uno)."""
    ahora = ahora_ar()

    # 1) clases dictadas del mes, con presentes y cuántos tienen marca
    q = (db.session.query(
            m.ClaseDictada, m.Clase,
            func.count(m.Asistencia.id).filter(m.Asistencia.estado == "presente"),
            func.count(m.Asistencia.id))
         .join(m.Clase, m.Clase.id == m.ClaseDictada.clase_id)
         .outerjoin(m.Asistencia, m.Asistencia.clase_dictada_id == m.ClaseDictada.id)
         .filter(m.ClaseDictada.fecha.between(desde, hasta))
         .group_by(m.ClaseDictada.id, m.Clase.id))
    if profesor_id is not None:
        q = q.filter(m.ClaseDictada.profesor_id == profesor_id)
    dictadas = q.all()

    # marcas de las dictadas sin presentes, para ver si falta marcar a alguien
    sin_presentes = [d.id for d, _, presentes, _ in dictadas if not presentes]
    marcados = defaultdict(set)
    if sin_presentes:
        for did, aid in db.session.query(m.Asistencia.clase_dictada_id, m.Asistencia.alumno_id).filter(
                m.Asistencia.clase_dictada_id.in_(sin_presentes)):
            marcados[did].add(aid)

    # 2) clases de la grilla que ya pasaron y nadie marcó
    qc = m.Clase.query.filter(m.Clase.activa.is_(True), m.Clase.profesor_id.isnot(None))
    if profesor_id is not None:
        qc = qc.filter(m.Clase.profesor_id == profesor_id)
    grilla = qc.all()

    clases_todas = {c.id: c for c in grilla}
    for _, c, _, _ in dictadas:
        clases_todas[c.id] = c
    esperados = _esperados(list(clases_todas.values()), desde, min(hasta, ahora.date()))

    profes = {}

    def profe(pid):
        if pid not in profes:
            profes[pid] = {"profesor_id": pid, "clases": [], "sin_alumnos": [], "pendientes": []}
        return profes[pid]

    # las ya marcadas, sin importar quién la dio (si la dio un reemplazo no es pendiente del titular)
    hechas = set(map(tuple, db.session.query(m.ClaseDictada.clase_id, m.ClaseDictada.fecha).filter(
        m.ClaseDictada.fecha.between(desde, hasta)).all()))

    for d, c, presentes, _ in dictadas:
        fila = {"fecha": d.fecha.isoformat(), "hora": c.hora_inicio.strftime("%H:%M"), "clase_id": c.id,
                "grupo": _grupo(c), "tipo": c.tipo, "presentes": presentes, "horas": _horas(c)}
        p = profe(d.profesor_id)
        if presentes:
            p["clases"].append(fila)
        elif esperados.get((c.id, d.fecha), set()) - marcados[d.id]:
            p["pendientes"].append({**fila, "motivo": "faltan marcar alumnos"})
        else:
            p["sin_alumnos"].append(fila)

    for c in grilla:
        for f in _fechas_de(c, desde, min(hasta, ahora.date())):
            if (c.id, f) in hechas or not esperados.get((c.id, f)):
                continue  # ya se marcó, o no tenía a nadie anotado ese día
            if f == ahora.date() and c.hora_inicio > ahora.time():
                continue  # todavía no empezó
            profe(c.profesor_id)["pendientes"].append({
                "fecha": f.isoformat(), "hora": c.hora_inicio.strftime("%H:%M"), "clase_id": c.id,
                "grupo": _grupo(c), "tipo": c.tipo, "presentes": 0, "horas": _horas(c),
                "motivo": "sin marcar"})

    # 3) plata: tarifa por fecha de cada clase
    nombres = dict(db.session.query(Profesor.id, Profesor.nombre).filter(
        Profesor.id.in_([pid for pid in profes if pid is not None])).all()) if profes else {}
    tarifas = _tarifas([pid for pid in profes if pid is not None])

    total_horas, total_monto = Decimal(0), Decimal(0)
    salida = []
    for pid, p in profes.items():
        horas, monto, sin_tarifa = Decimal(0), Decimal(0), False
        for fila in p["clases"]:
            t = tarifa_en(tarifas[pid], date.fromisoformat(fila["fecha"])) if pid else None
            fila["tarifa"] = t
            fila["monto"] = (fila["horas"] * t).quantize(CENTAVOS, ROUND_HALF_UP) if t is not None else None
            horas += fila["horas"]
            if t is None:
                sin_tarifa = True
            else:
                monto += fila["monto"]
        for lista in (p["clases"], p["sin_alumnos"], p["pendientes"]):
            lista.sort(key=lambda x: (x["fecha"], x["hora"]))
        total_horas += horas
        total_monto += monto
        salida.append({
            **p,
            "nombre": nombres.get(pid, "Sin profe asignado"),
            "horas": horas,
            "monto": monto,
            "sin_tarifa": sin_tarifa,  # hay horas que no se pudieron valorizar
            "tarifa": tarifa_en(tarifas[pid], hasta) if pid else None,  # la vigente al cierre del mes
            "horas_pendientes": sum((x["horas"] for x in p["pendientes"]), Decimal(0)),
        })
    salida.sort(key=lambda x: x["nombre"].lower())
    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "profes": salida,
        "total_horas": total_horas,
        "total_monto": total_monto,
        "total_pendientes": sum(len(p["pendientes"]) for p in salida),
    }
