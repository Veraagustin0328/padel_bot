"""Inicio del panel: un tablero distinto por rol. El back decide qué viaja a cada uno.

- dueño: plata del mes (cobrado, a cobrar, falta, vencido), clases de hoy, alertas y alumnos.
- encargado: deudores (nombre y qué cuota, sin montos, como en Cuotas), faltas y viajes,
  clases de hoy y alumnos con datos incompletos. Ninguna cifra de plata.
- profe: sus horas y lo que gana (solo lo suyo), comparado con el mes y la semana anterior,
  y sus próximas clases. Las de hoy las arma el panel con /api/mis-clases (lo mismo de Mis clases).

Los pendientes (comprobantes, solicitudes, etc.) no van acá: el panel ya los cuenta para el menú.
Todo reutiliza las consultas de Cuotas, Clases, Faltas y viajes y Mis horas.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify
from sqlalchemy import func, or_

from app import alumnos_alta, horas_profes
from app import models_academia as m
from app import recuperaciones as rec
from app.cambios_dias import vigente_en
from app.contactos import tel10
from app.extensions import db
from app.models import Alumno, ContactoAlumno
from app.models_cuotas import CuotaMes, PagoCuota
from app.models_plataforma import Profesor
from app.routes.auth import ROL_DUENO, requiere_login
from app.routes.horas_profes import _json
from app.routes.recuperaciones import _json_ausencias, _json_lapsos

inicio_bp = Blueprint("inicio", __name__)

TIPOS = {"grupal": "Grupal", "particular": "Particular", "particular_2": "Particular de 2",
         "particular_3": "3 o 4 personas", "otro": "Otra", "fisico": "Físico"}
DIAS_PROXIMAS = 7  # próximas clases del profe: de mañana a una semana (incluye el mismo día que viene)
MAX_PROXIMAS = 8
MAX_LISTA = 30  # tope de filas en las listas del encargado (el resto está en su pantalla)


def _mes_anterior(inicio):
    return (inicio - timedelta(days=1)).replace(day=1)


def _nombre_clase(c, profe=""):
    partes = [c.hora_inicio.strftime("%H:%M"), TIPOS.get(c.tipo, c.tipo or "")]
    if c.nivel:
        partes.append(c.nivel)
    return " · ".join(p for p in partes if p) + (f" · {profe}" if profe else "")


# ---------- clases de hoy (dueño y encargado) ----------

def _clases_de_hoy(hoy):
    """Las de la grilla que se dan hoy, con cuántos se esperan y si ya se marcó que se dio.
    Las filas de apoyo no cuentan aparte: son la misma clase."""
    filas = (db.session.query(m.Clase, Profesor.nombre)
             .outerjoin(Profesor, m.Clase.profesor_id == Profesor.id)
             .filter(m.Clase.activa.is_(True), m.Clase.dia_semana == hoy.weekday(),
                     m.Clase.apoyo_de_clase_id.is_(None), m.clase_vigente_en(hoy))
             .all())
    clases = [c for c, _ in filas]
    del_dia = rec.alumnos_del_dia_en_lote(clases, hoy) if clases else {}
    dadas = {cid for (cid,) in db.session.query(m.ClaseDictada.clase_id).filter(
        m.ClaseDictada.fecha == hoy, m.ClaseDictada.clase_id.in_([c.id for c in clases] or [0]))}
    lista = []
    for c, profe in filas:
        vienen, _ = del_dia.get(c.id, ({}, {}))
        lista.append({"id": c.id, "hora": c.hora_inicio.strftime("%H:%M"), "tipo": TIPOS.get(c.tipo, c.tipo),
                      "nivel": c.nivel or "", "profe": profe or "", "esperados": len(vienen),
                      "dada": c.id in dadas})
    lista.sort(key=lambda x: (x["hora"], x["profe"]))
    # las que no tienen a nadie hoy no suman (la grilla tiene filas vacías)
    con_gente = [x for x in lista if x["esperados"] or x["dada"]]
    return {"total": len(con_gente), "dadas": sum(1 for x in con_gente if x["dada"]), "clases": con_gente}


# ---------- dueño ----------

def _deuda_por_mes(hasta_mes=None, mes=None):
    """{(alumno, mes): (cuota, pagado)} de las cuotas, con un filtro de mes (igual o anterior)."""
    qc = db.session.query(CuotaMes.alumno_id, CuotaMes.mes, func.sum(CuotaMes.monto))
    qp = db.session.query(PagoCuota.alumno_id, PagoCuota.mes, func.sum(PagoCuota.monto))
    if mes is not None:
        qc, qp = qc.filter(CuotaMes.mes == mes), qp.filter(PagoCuota.mes == mes)
    if hasta_mes is not None:
        qc, qp = qc.filter(CuotaMes.mes < hasta_mes), qp.filter(PagoCuota.mes < hasta_mes)
    cuenta = defaultdict(lambda: [0, 0])
    for a, ms, s in qc.group_by(CuotaMes.alumno_id, CuotaMes.mes):
        cuenta[(a, ms)][0] += int(s or 0)
    for a, ms, s in qp.group_by(PagoCuota.alumno_id, PagoCuota.mes):
        cuenta[(a, ms)][1] += int(s or 0)
    return cuenta


def _plata(inicio):
    """Lo mismo que los totales de Cuotas para el mes, más lo que quedó sin pagar de antes."""
    del_mes = _deuda_por_mes(mes=inicio)
    a_cobrar = sum(c for c, _ in del_mes.values())
    cobrado = sum(p for _, p in del_mes.values())
    falta = sum(max(c - p, 0) for c, p in del_mes.values())
    deben = sum(1 for c, p in del_mes.values() if c > p)
    viejo = _deuda_por_mes(hasta_mes=inicio)
    vencido = sum(max(c - p, 0) for c, p in viejo.values())
    deben_vencido = len({a for (a, _), (c, p) in viejo.items() if c > p})
    return {"mes": inicio.strftime("%Y-%m"), "generadas": a_cobrar > 0 or bool(del_mes),
            "cobrado": cobrado, "a_cobrar": a_cobrar, "falta": falta, "deben": deben,
            "vencido": vencido, "deben_vencido": deben_vencido}


def _alertas(hoy):
    """Clases sin profe y clases con más anotados que el cupo (las que siguen vigentes)."""
    clases = (m.Clase.query.filter(m.Clase.activa.is_(True), m.Clase.apoyo_de_clase_id.is_(None),
                                   m.clase_no_terminada(hoy)).all())
    anotados = defaultdict(int)
    for (cid,) in db.session.query(m.Inscripcion.clase_id).filter(vigente_en(hoy)):
        anotados[cid] += 1
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    sin_profe = [{"id": c.id, "clase": f"{dias[c.dia_semana]} {_nombre_clase(c)}", "anotados": anotados[c.id]}
                 for c in clases if not c.profesor_id]
    profes = dict(db.session.query(Profesor.id, Profesor.nombre))
    sobre_cupo = [{"id": c.id, "clase": f"{dias[c.dia_semana]} {_nombre_clase(c, profes.get(c.profesor_id, ''))}",
                   "anotados": anotados[c.id], "cupo": c.cupo}
                  for c in clases if c.cupo and anotados[c.id] > c.cupo]
    orden = lambda x: x["clase"]  # noqa: E731
    return {"sin_profe": sorted(sin_profe, key=orden), "sobre_cupo": sorted(sobre_cupo, key=orden)}


def _alumnos(inicio):
    activos = Alumno.query.filter(or_(Alumno.estado.is_(None), Alumno.estado != "baja")).count()
    fin = (inicio + timedelta(days=32)).replace(day=1)
    altas = Alumno.query.filter(Alumno.fecha_inscripcion >= datetime.combine(inicio, datetime.min.time()),
                                Alumno.fecha_inscripcion < datetime.combine(fin, datetime.min.time())).count()
    # las bajas que quedaron en la auditoría (las del panel)
    bajas = db.session.query(func.count(func.distinct(m.Auditoria.entidad_id))).filter(
        m.Auditoria.entidad == "alumno", m.Auditoria.accion == "baja",
        m.Auditoria.en >= datetime.combine(inicio, datetime.min.time()),
        m.Auditoria.en < datetime.combine(fin, datetime.min.time())).scalar() or 0
    return {"activos": activos, "altas_mes": altas, "bajas_mes": bajas}


def _dueno(hoy):
    inicio = hoy.replace(day=1)
    return {"rol": "dueno", "hoy": hoy.isoformat(), "plata": _plata(inicio), "clases_hoy": _clases_de_hoy(hoy),
            "alertas": _alertas(hoy), "alumnos": _alumnos(inicio)}


# ---------- encargado ----------

def _deudores(hoy):
    """Los que no tienen paga la cuota de este mes o del anterior: nombre y mes, sin montos.
    Es lo mismo que le muestra Cuotas (pago / no pago); el parcial cuenta como no pago."""
    inicio = hoy.replace(day=1)
    meses = [_mes_anterior(inicio), inicio]
    filas = []
    for ms in meses:
        for (a, _), (c, p) in _deuda_por_mes(mes=ms).items():
            if c > 0 and p < c:
                filas.append((a, ms))
    nombres = dict(db.session.query(Alumno.id, Alumno.nombre).filter(
        Alumno.id.in_({a for a, _ in filas}))) if filas else {}
    salida = [{"alumno_id": a, "alumno": nombres.get(a, f"#{a}"), "mes": ms.strftime("%Y-%m"),
               "vencida": ms < inicio} for a, ms in filas]
    salida.sort(key=lambda x: (not x["vencida"], x["alumno"].lower()))
    generadas = db.session.query(CuotaMes.id).filter(CuotaMes.mes == inicio).first() is not None
    return {"mes": inicio.strftime("%Y-%m"), "generadas": generadas, "total": len(salida),
            "items": salida[:MAX_LISTA]}


def _faltas_y_viajes(hoy):
    faltas = m.Ausencia.query.filter(m.Ausencia.fecha == hoy).order_by(m.Ausencia.id).all()
    viajes = m.AusenciaLapso.query.filter(m.AusenciaLapso.estado == "confirmado", m.AusenciaLapso.desde <= hoy,
                                          m.AusenciaLapso.hasta >= hoy).order_by(m.AusenciaLapso.hasta).all()
    f, v = _json_ausencias(faltas), _json_lapsos(viajes)
    return {"faltas_hoy": len(f), "viajes_hoy": len(v),
            "faltas": [{k: x[k] for k in ("id", "alumno", "clase", "a_tiempo")} for x in f[:MAX_LISTA]],
            "viajes": [{k: x[k] for k in ("id", "alumno", "clase", "hasta")} for x in v[:MAX_LISTA]]}


def _incompletos():
    """Igual que los filtros de Fichas: sin teléfono (ni contactos) y adultos sin categoría. Sin las bajas."""
    alumnos = Alumno.query.filter(or_(Alumno.estado.is_(None), Alumno.estado != "baja")).all()
    con_contacto = {a for (a,) in db.session.query(ContactoAlumno.alumno_id).distinct()}
    sin_tel = sum(1 for a in alumnos if a.id not in con_contacto and len(tel10(a.telefono)) < 10)
    sin_cat = sum(1 for a in alumnos if not (a.categoria or "").strip() and not alumnos_alta.es_menor(a.planilla))
    return {"sin_telefono": sin_tel, "sin_categoria": sin_cat}


def _encargado(hoy):
    return {"rol": "encargado", "hoy": hoy.isoformat(), "deudores": _deudores(hoy),
            "faltas_viajes": _faltas_y_viajes(hoy), "clases_hoy": _clases_de_hoy(hoy),
            "incompletos": _incompletos()}


# ---------- profe ----------

def _horas_en(profesor_id, desde, hasta):
    """Horas y monto de ese profe en el rango (el mismo cálculo de Mis horas)."""
    if hasta < desde:
        return {"horas": 0, "monto": 0, "sin_tarifa": False}
    datos = horas_profes.resumen_mes(desde, hasta, profesor_id=profesor_id)
    p = next((x for x in datos["profes"] if x["profesor_id"] == profesor_id), None)
    if not p:
        return {"horas": 0, "monto": 0, "sin_tarifa": False}
    return {"horas": p["horas"], "monto": p["monto"], "sin_tarifa": p["sin_tarifa"]}


def _comparar(actual, antes, con_plata):
    """más / igual / menos por horas (y por plata si tiene tarifa)."""
    def signo(a, b):
        return "mas" if a > b else "menos" if a < b else "igual"
    salida = {"actual": {"horas": actual["horas"]}, "antes": {"horas": antes["horas"]},
              "horas": signo(actual["horas"], antes["horas"])}
    if con_plata:
        salida["actual"]["monto"], salida["antes"]["monto"] = actual["monto"], antes["monto"]
        salida["monto"] = signo(actual["monto"], antes["monto"])
    return salida


def _horas_profe(profesor_id, hoy):
    """Lo que va del mes contra el mismo tramo del mes anterior, y lo que va de la semana contra
    los mismos días de la anterior. Sin tarifa vigente: no se manda ningún monto."""
    tarifa = horas_profes.tarifa_en(horas_profes._tarifas([profesor_id])[profesor_id], hoy)
    con_plata = tarifa is not None
    inicio = hoy.replace(day=1)
    ant = _mes_anterior(inicio)
    fin_ant = ant + timedelta(days=min(hoy.day, (inicio - ant).days) - 1)
    lunes = hoy - timedelta(days=hoy.weekday())
    mes = _comparar(_horas_en(profesor_id, inicio, hoy), _horas_en(profesor_id, ant, fin_ant), con_plata)
    semana = _comparar(_horas_en(profesor_id, lunes, hoy),
                       _horas_en(profesor_id, lunes - timedelta(days=7), hoy - timedelta(days=7)), con_plata)
    return {"sin_tarifa": not con_plata, "tarifa": tarifa if con_plata else None,
            "mes": {**mes, "desde": inicio.isoformat(), "hasta": hoy.isoformat(),
                    "antes_desde": ant.isoformat(), "antes_hasta": fin_ant.isoformat()},
            "semana": {**semana, "desde": lunes.isoformat(), "hasta": hoy.isoformat()}}


def _proximas(profesor_id, hoy):
    desde, hasta = hoy + timedelta(days=1), hoy + timedelta(days=DIAS_PROXIMAS)
    clases = m.Clase.query.filter(m.Clase.activa.is_(True), m.Clase.profesor_id == profesor_id).all()
    # las de apoyo: se esperan los de la titular
    titulares = {c.id: c for c in m.Clase.query.filter(
        m.Clase.id.in_({c.apoyo_de_clase_id for c in clases if c.apoyo_de_clase_id} or {0}))}
    lote = rec.alumnos_en_rango(clases + list(titulares.values()), desde, hasta)
    salida = []
    for c in clases:
        fuente = titulares.get(c.apoyo_de_clase_id, c)
        for f in rec.fechas_de_clase(c, desde, hasta):
            vienen, _ = lote.get((fuente.id, f), ({}, {}))
            if not vienen:
                continue  # sin nadie anotado ese día no es una clase para avisar
            salida.append({"clase_id": c.id, "fecha": f.isoformat(), "hora": c.hora_inicio.strftime("%H:%M"),
                           "tipo": TIPOS.get(c.tipo, c.tipo), "nivel": c.nivel or "",
                           "apoyo": bool(c.apoyo_de_clase_id), "esperados": len(vienen)})
    salida.sort(key=lambda x: (x["fecha"], x["hora"]))
    return salida[:MAX_PROXIMAS]


def _profe(profesor_id, hoy):
    return {"rol": "profe", "hoy": hoy.isoformat(), "horas": _horas_profe(profesor_id, hoy),
            "proximas": _proximas(profesor_id, hoy)}


@inicio_bp.get("/api/inicio")
@requiere_login("profe", "encargado")
def inicio():
    hoy = rec.hoy()
    u = g.usuario
    if u.rol == ROL_DUENO:
        return jsonify(_json(_dueno(hoy)))
    if u.rol == "encargado":
        return jsonify(_json(_encargado(hoy)))
    # profe: solo lo suyo, siempre de su usuario (nada que venga en la url)
    if not u.profesor_id:
        return jsonify({"error": "Tu usuario no está vinculado a un profe"}), 403
    return jsonify(_json(_profe(u.profesor_id, hoy)))
