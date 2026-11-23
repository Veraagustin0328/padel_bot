"""Horas y plata de los profes por mes. Solo lo usa el dueño (y después cada profe lo suyo).

Reglas:
- Se paga la hora si la clase se dictó (hay ClaseDictada) y vino al menos 1 presente.
- Se le paga al que la dio: ClaseDictada.profesor_id.
- Horas = duración de la clase / 60.
- La tarifa es la vigente en la fecha de cada clase (valores_hora, con historial).
- Dictada y todos marcados ausentes: no se paga, va aparte como "sin alumnos".
- Pendiente de confirmar: dictada sin presentes con gente todavía sin marcar, o clase
  de la grilla ya pasada que nadie marcó. No suma hasta que haya un presente.
- Los pendientes se cuentan desde config_academia 'horas_pendientes_desde' (AAAA-MM-DD).
  Lo anterior sin presentes no aparece como pendiente. Sin la clave, se cuenta todo.
- Titular de una clase con filas de apoyo: también marca "di la clase" y cobra aunque no venga
  nadie (TITULAR_CON_APOYO_COBRA_SIN_PRESENTES). Las clases sin apoyo siguen igual.
- Filas de apoyo (Clase.apoyo_de_clase_id): no tienen alumnos, el profe marca "di la clase"
  (ClaseDictada sin asistencias) y la hora depende de la titular de ese día (APOYO_SOLO_CON_PRESENTES).
  Si la titular todavía no se marcó, queda pendiente. Si pasó el día y no marcó "di la clase"
  (y la titular tenía alumnos), también es pendiente.
"""
import json
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_

from app import models_academia as m
from app.extensions import db
from app.models_plataforma import Profesor, ValorHora

CENTAVOS = Decimal("0.01")

TIPOS_TEXTO = {"grupal": "Grupal", "particular": "Particular", "particular_2": "Particular x2",
               "particular_3": "Particular x3/4", "otro": "Otro",
               "fisico": "Físico"}

# Fila de apoyo que marcó "di la clase":
# True = cobra solo si ese día la titular tuvo al menos un presente (misma regla que el titular).
# False = cobra siempre, aunque no haya venido ningún alumno (confirmado por Gabi el 20/11/2026).
APOYO_SOLO_CON_PRESENTES = False

# Titular de una clase CON filas de apoyo activas: también tiene "di la clase" y cobra aunque no venga
# ningún chico (regla de Gabi, 20/11/2026). False = cobra solo con al menos un presente, como siempre.
# Las clases sin apoyo no cambian: cobran solo con presentes.
TITULAR_CON_APOYO_COBRA_SIN_PRESENTES = True


def titulares_con_apoyo():
    """Ids de las clases que tienen al menos una fila de apoyo activa."""
    return {cid for (cid,) in db.session.query(m.Clase.apoyo_de_clase_id).filter(
        m.Clase.apoyo_de_clase_id.isnot(None), m.Clase.activa.is_(True)).distinct()}


def ahora_ar():
    # misma hora que el resto (Argentina, UTC-3)
    return datetime.now(timezone(timedelta(hours=-3))).replace(tzinfo=None)


def pendientes_desde():
    """Fecha de config_academia 'horas_pendientes_desde', o None si no está o está mal escrita."""
    cfg = db.session.get(m.ConfigAcademia, "horas_pendientes_desde")
    if not cfg or not cfg.valor:
        return None
    try:
        valor = json.loads(cfg.valor)
    except ValueError:
        valor = cfg.valor  # por si la cargaron sin comillas
    try:
        return date.fromisoformat(str(valor).strip()) if valor else None
    except ValueError:
        return None


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
    if clase.apoyo_de_clase_id:
        partes.append("(apoyo)")
    return " ".join(p for p in partes if p)


def _fechas_de(clase, desde, hasta):
    """Las fechas del rango en que cae la clase (por día de la semana), dentro de su temporada."""
    if clase.vigente_desde:
        desde = max(desde, clase.vigente_desde)
    if clase.vigente_hasta:
        hasta = min(hasta, clase.vigente_hasta - timedelta(days=1))  # vigente_hasta ya no se da
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
    corte = pendientes_desde()  # antes de esta fecha no hay pendientes

    def cuenta_pendiente(fecha):
        return corte is None or fecha >= corte

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

    # filas de apoyo: se traen sus titulares (aunque sean de otro profe) para saber cómo les fue ese día
    titular_ids = {c.apoyo_de_clase_id for c in clases_todas.values() if c.apoyo_de_clase_id}
    titulares = {c.id: c for c in m.Clase.query.filter(m.Clase.id.in_(titular_ids))} if titular_ids else {}
    for c in titulares.values():
        clases_todas.setdefault(c.id, c)
    esperados = _esperados(list(clases_todas.values()), desde, min(hasta, ahora.date()))

    # dictadas de las titulares: presentes y quiénes tienen marca
    dictada_titular, marcas_titular = {}, defaultdict(set)  # (clase_id, fecha) -> (dictada_id, presentes)
    if titulares:
        for did, cid, f, pres in (db.session.query(
                m.ClaseDictada.id, m.ClaseDictada.clase_id, m.ClaseDictada.fecha,
                func.count(m.Asistencia.id).filter(m.Asistencia.estado == "presente"))
                .outerjoin(m.Asistencia, m.Asistencia.clase_dictada_id == m.ClaseDictada.id)
                .filter(m.ClaseDictada.clase_id.in_(list(titulares)), m.ClaseDictada.fecha.between(desde, hasta))
                .group_by(m.ClaseDictada.id)):
            dictada_titular[(cid, f)] = (did, pres)
        ids = [did for did, _ in dictada_titular.values()]
        if ids:
            for did, aid in db.session.query(m.Asistencia.clase_dictada_id, m.Asistencia.alumno_id).filter(
                    m.Asistencia.clase_dictada_id.in_(ids)):
                marcas_titular[did].add(aid)

    def como_le_fue_a_la_titular(titular_id, fecha):
        """(estado, presentes): 'presentes', 'pendiente' (falta marcar alguien) o 'sin_alumnos'."""
        did, pres = dictada_titular.get((titular_id, fecha), (None, 0))
        if pres:
            return "presentes", pres
        falta = esperados.get((titular_id, fecha), set()) - (marcas_titular[did] if did else set())
        return ("pendiente" if falta else "sin_alumnos"), 0

    def es_apoyo(c):
        return c.apoyo_de_clase_id in titulares

    # titulares con apoyo que cobran con "di la clase" aunque no haya presentes
    con_apoyo = titulares_con_apoyo() if TITULAR_CON_APOYO_COBRA_SIN_PRESENTES else set()

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
        if es_apoyo(c):
            # marcó "di la clase": la hora depende de la titular de ese día
            estado, pres = como_le_fue_a_la_titular(c.apoyo_de_clase_id, d.fecha)
            fila.update(presentes=pres, apoyo_de=c.apoyo_de_clase_id)
            p = profe(d.profesor_id)
            if estado == "presentes" or not APOYO_SOLO_CON_PRESENTES:
                p["clases"].append(fila)
            elif estado == "pendiente":
                if cuenta_pendiente(d.fecha):
                    p["pendientes"].append({**fila, "motivo": "falta marcar la titular"})
            else:
                p["sin_alumnos"].append(fila)
            continue
        if c.id in con_apoyo and not presentes:
            # titular de una clase con apoyo: la dictada ("di la clase" o alguna marca) alcanza para cobrar
            profe(d.profesor_id)["clases"].append(fila)
            continue
        falta_marcar = not presentes and esperados.get((c.id, d.fecha), set()) - marcados[d.id]
        if falta_marcar and not cuenta_pendiente(d.fecha):
            continue  # antes del corte: no se muestra como pendiente
        p = profe(d.profesor_id)
        if presentes:
            p["clases"].append(fila)
        elif falta_marcar:
            p["pendientes"].append({**fila, "motivo": "faltan marcar alumnos"})
        else:
            p["sin_alumnos"].append(fila)

    for c in grilla:
        apoyo = es_apoyo(c)
        for f in _fechas_de(c, max(desde, corte or desde), min(hasta, ahora.date())):
            # la de apoyo no tiene alumnos propios: se mira si la titular tenía a alguien ese día
            if (c.id, f) in hechas or not esperados.get((c.apoyo_de_clase_id if apoyo else c.id, f)):
                continue  # ya se marcó, o no tenía a nadie anotado ese día
            if f == ahora.date() and c.hora_inicio > ahora.time():
                continue  # todavía no empezó
            fila = {"fecha": f.isoformat(), "hora": c.hora_inicio.strftime("%H:%M"), "clase_id": c.id,
                    "grupo": _grupo(c), "tipo": c.tipo, "presentes": 0, "horas": _horas(c),
                    "motivo": "falta marcar di la clase" if apoyo else "sin marcar"}
            if apoyo:
                fila["apoyo_de"] = c.apoyo_de_clase_id
            elif c.id in con_apoyo:
                fila["di_la_clase"] = True  # la titular con apoyo también se resuelve con "di la clase"
            profe(c.profesor_id)["pendientes"].append(fila)

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
