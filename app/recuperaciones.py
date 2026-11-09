"""Faltas, recuperaciones y viajes: toda la lógica de las reglas en un solo lugar.

La usan las rutas del panel y, más adelante, el agente. Las reglas salen de
ConfigAcademia, así cada club pone las suyas:
- aviso_horas: con cuántas horas de anticipación hay que avisar la falta (24)
- recupera_mismo_mes: la recuperación tiene que caer en el mes de la falta (true)
- max_recuperaciones_mes: tope por alumno y por mes (1; 0 o null = sin tope)

Lo que se sale de la regla no se rechaza solo: queda 'pendiente' con el motivo
en fuera_de_regla y decide el encargado. Lo que no se puede hacer ni con
aprobación (clase que no existe, día equivocado, clase llena) tira ErrorRegla.

Fechas y horas siempre en hora argentina (ZONA_HORARIA). Las columnas DateTime
se guardan en UTC sin zona, como el resto de la base.
Acá no se hace commit: lo hace quien llama.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import extract, or_

from app import models_academia as m
from app.extensions import db
from app.models import Alumno

ZONA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Argentina/Buenos_Aires"))

REGLAS_DEFAULT = {"aviso_horas": 24, "recupera_mismo_mes": True, "max_recuperaciones_mes": 1}
ACTIVAS = ("confirmada", "pendiente")   # las que ocupan la falta y cuentan para el tope


class ErrorRegla(ValueError):
    """Algo que no se puede hacer ni con aprobación del encargado."""


# ---------- reglas y horas ----------

def regla(clave):
    cfg = db.session.get(m.ConfigAcademia, clave)
    if not cfg:
        return REGLAS_DEFAULT.get(clave)
    try:
        return json.loads(cfg.valor)
    except (TypeError, ValueError):
        return REGLAS_DEFAULT.get(clave)


def ahora():
    return datetime.now(ZONA)


def hoy():
    # en Render el server está en UTC: a las 22 hs de acá ya sería mañana
    return ahora().date()


def utc_naive(dt):
    """Datetime con zona (o naive en hora argentina) -> UTC sin zona, como se guarda."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZONA)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _a_zona(dt_utc):
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(ZONA)


def inicio_clase(clase, fecha):
    return datetime.combine(fecha, clase.hora_inicio, tzinfo=ZONA)


def es_a_tiempo(clase, fecha, avisada_en_utc):
    horas = float(regla("aviso_horas") or 0)
    return _a_zona(avisada_en_utc) <= inicio_clase(clase, fecha) - timedelta(hours=horas)


def _mes(f):
    return (f.year, f.month)


# ---------- quién está en cada clase ----------

def _clase(clase_id):
    clase = db.session.get(m.Clase, clase_id) if clase_id else None
    if not clase:
        raise ErrorRegla("No encontré la clase")
    return clase


def _alumno(alumno_id):
    alumno = db.session.get(Alumno, alumno_id) if alumno_id else None
    if not alumno:
        raise ErrorRegla("No encontré el alumno")
    return alumno


def _chequear_dia(clase, fecha):
    if fecha.weekday() != clase.dia_semana:
        raise ErrorRegla("Esa clase no se da ese día")


def _vigente(consulta, fecha):
    # mismo criterio que Mis clases: 'hasta' es el primer día que ya no está
    return consulta.filter(
        m.Inscripcion.desde <= fecha,
        or_(m.Inscripcion.hasta.is_(None), m.Inscripcion.hasta > fecha),
    )


def inscripto(alumno_id, clase_id, fecha):
    q = db.session.query(m.Inscripcion.id).filter_by(alumno_id=alumno_id, clase_id=clase_id)
    return _vigente(q, fecha).first() is not None


def lapsos_en(fecha, clase_id=None):
    """Viajes confirmados que cubren esa fecha (los de todas las clases + los de esa clase)."""
    q = m.AusenciaLapso.query.filter(
        m.AusenciaLapso.estado == "confirmado",
        m.AusenciaLapso.desde <= fecha,
        m.AusenciaLapso.hasta >= fecha,
    )
    if clase_id is not None:
        q = q.filter(or_(m.AusenciaLapso.clase_id.is_(None), m.AusenciaLapso.clase_id == clase_id))
    return q.all()


def alumnos_del_dia(clase, fecha):
    """Devuelve (vienen, no_vienen).
    vienen:    {alumno_id: 'fijo' | 'reemplazo' | 'recupera'}
    no_vienen: {alumno_id: 'viaje' | 'falta'}  (solo fijos)
    """
    q = db.session.query(m.Inscripcion.alumno_id).filter(m.Inscripcion.clase_id == clase.id)
    fijos = {aid for (aid,) in _vigente(q, fecha)}

    no_vienen, reemplazos = {}, []
    for lap in lapsos_en(fecha, clase.id):
        if lap.alumno_id in fijos:
            no_vienen[lap.alumno_id] = "viaje"
            if lap.reemplazo_alumno_id:
                reemplazos.append(lap.reemplazo_alumno_id)
    faltan = db.session.query(m.Ausencia.alumno_id).filter_by(clase_id=clase.id, fecha=fecha)
    for (aid,) in faltan:
        if aid in fijos:
            no_vienen.setdefault(aid, "falta")

    vienen = {aid: "fijo" for aid in fijos if aid not in no_vienen}
    for aid in reemplazos:
        vienen.setdefault(aid, "reemplazo")
    recuperan = db.session.query(m.RecuperacionClase.alumno_id).filter_by(
        clase_id=clase.id, fecha=fecha, estado="confirmada")
    for (aid,) in recuperan:
        vienen.setdefault(aid, "recupera")
    return vienen, no_vienen


def lugares_libres(clase, fecha):
    vienen, _ = alumnos_del_dia(clase, fecha)
    return clase.cupo - len(vienen)


# ---------- faltas ----------

def recuperacion_activa(ausencia_id):
    return m.RecuperacionClase.query.filter(
        m.RecuperacionClase.ausencia_id == ausencia_id,
        m.RecuperacionClase.estado.in_(ACTIVAS),
    ).first()


def avisar_ausencia(alumno_id, clase_id, fecha, origen, motivo=None, avisada_en=None, a_tiempo=None):
    """Registra la falta. Devuelve (ausencia, nueva). Si ya estaba avisada la devuelve tal cual.
    avisada_en: UTC sin zona (vacío = ahora). a_tiempo: se pasa solo si alguien lo certifica.
    """
    _alumno(alumno_id)
    clase = _clase(clase_id)
    _chequear_dia(clase, fecha)
    if not inscripto(alumno_id, clase.id, fecha):
        raise ErrorRegla("Ese alumno no está anotado en esa clase ese día")

    existente = m.Ausencia.query.filter_by(alumno_id=alumno_id, clase_id=clase.id, fecha=fecha).first()
    if existente:
        return existente, False

    avisada_en = avisada_en or datetime.utcnow()
    if a_tiempo is None:
        a_tiempo = es_a_tiempo(clase, fecha, avisada_en)
    aus = m.Ausencia(alumno_id=alumno_id, clase_id=clase.id, fecha=fecha, origen=origen,
                     motivo=(motivo or "").strip()[:255] or None,
                     avisada_en=avisada_en, a_tiempo=bool(a_tiempo))
    db.session.add(aus)
    db.session.flush()
    return aus, True


def faltas_recuperables(alumno_id, para_fecha=None):
    """Faltas sin recuperación activa, de la más conveniente a la menos:
    primero las del mismo mes que para_fecha, después las avisadas a tiempo, después la más vieja."""
    para_fecha = para_fecha or hoy()
    usadas = db.session.query(m.RecuperacionClase.ausencia_id).filter(
        m.RecuperacionClase.ausencia_id.isnot(None),
        m.RecuperacionClase.estado.in_(ACTIVAS),
    )
    faltas = m.Ausencia.query.filter(
        m.Ausencia.alumno_id == alumno_id,
        m.Ausencia.id.notin_(usadas),
    ).all()
    faltas.sort(key=lambda a: (_mes(a.fecha) != _mes(para_fecha), not a.a_tiempo, a.fecha))
    return faltas


def sincronizar_asistencia(clase, fecha, alumno_id, estado):
    """Lo que marca el profe en Mis clases se refleja en Ausencia (solo para alumnos fijos).
    'Avisó' -> falta a tiempo (el profe lo certifica). 'Ausente' -> falta sin aviso.
    Si la falta la cargó el alumno, el agente o el encargado, no se pisa.
    """
    if not inscripto(alumno_id, clase.id, fecha):
        return
    aus = m.Ausencia.query.filter_by(alumno_id=alumno_id, clase_id=clase.id, fecha=fecha).first()

    if estado == "presente":
        # vino al final: la falta que había puesto el profe se borra, salvo que ya la esté usando
        if aus and aus.origen == "profe" and not recuperacion_activa(aus.id):
            db.session.delete(aus)
        return

    certifica = estado == "ausente_avisa"
    if not aus:
        db.session.add(m.Ausencia(alumno_id=alumno_id, clase_id=clase.id, fecha=fecha, origen="profe",
                                  a_tiempo=certifica, motivo=None if certifica else "sin aviso"))
    elif aus.origen == "profe":
        aus.a_tiempo = certifica
        aus.motivo = None if certifica else "sin aviso"
    db.session.flush()


# ---------- recuperaciones ----------

def _usadas_en_mes(alumno_id, fecha):
    return m.RecuperacionClase.query.filter(
        m.RecuperacionClase.alumno_id == alumno_id,
        m.RecuperacionClase.estado.in_(ACTIVAS),
        extract("year", m.RecuperacionClase.fecha) == fecha.year,
        extract("month", m.RecuperacionClase.fecha) == fecha.month,
    ).count()


def pedir_recuperacion(alumno_id, clase_id, fecha, ausencia_id=None, pedida_por="agente",
                       forzar=False, usuario_id=None):
    """Arma la recuperación. Si cumple todo queda confirmada; si no, pendiente con el motivo.
    Si la carga el encargado queda confirmada igual (él decide), con el motivo anotado.
    forzar (solo encargado): la mete aunque la clase esté llena.
    """
    _alumno(alumno_id)
    clase = _clase(clase_id)
    if not clase.activa:
        raise ErrorRegla("Esa clase no está activa")
    _chequear_dia(clase, fecha)
    gestion = pedida_por == "encargado"
    forzar = bool(forzar and gestion)

    if not gestion and inicio_clase(clase, fecha) <= ahora():
        raise ErrorRegla("Esa clase ya empezó o ya pasó")
    if inscripto(alumno_id, clase.id, fecha):
        raise ErrorRegla("Esa es su clase fija, no hace falta recuperar ahí")
    duplicada = m.RecuperacionClase.query.filter(
        m.RecuperacionClase.alumno_id == alumno_id,
        m.RecuperacionClase.clase_id == clase.id,
        m.RecuperacionClase.fecha == fecha,
        m.RecuperacionClase.estado.in_(ACTIVAS),
    ).first()
    if duplicada:
        raise ErrorRegla("Ya tiene una recuperación en esa clase ese día")

    vienen, _ = alumnos_del_dia(clase, fecha)
    if alumno_id in vienen:
        raise ErrorRegla("Ya está en esa clase ese día")
    llena = clase.cupo - len(vienen) <= 0
    if llena and not forzar:
        raise ErrorRegla("La clase está llena ese día")

    # la falta que se recupera: la que eligieron o la más conveniente
    if ausencia_id:
        aus = db.session.get(m.Ausencia, ausencia_id)
        if not aus or aus.alumno_id != alumno_id:
            raise ErrorRegla("Esa falta no es de ese alumno")
        if recuperacion_activa(aus.id):
            raise ErrorRegla("Esa falta ya tiene una recuperación")
    else:
        candidatas = faltas_recuperables(alumno_id, para_fecha=fecha)
        aus = candidatas[0] if candidatas else None

    motivos = []
    if not aus:
        motivos.append("no tiene una falta registrada para recuperar")
    else:
        if not aus.a_tiempo:
            motivos.append(f"la falta del {aus.fecha:%d/%m} fue sin aviso o con aviso tarde")
        if regla("recupera_mismo_mes") and _mes(aus.fecha) != _mes(fecha):
            motivos.append(f"la falta es del {aus.fecha:%d/%m} y quiere recuperar en otro mes")
    tope = int(regla("max_recuperaciones_mes") or 0)
    if tope:
        usadas = _usadas_en_mes(alumno_id, fecha)
        if usadas >= tope:
            motivos.append(f"ya tiene {usadas} recuperación(es) ese mes y el tope es {tope}")
    if llena:
        motivos.append("la clase estaba llena (la metió el encargado)")

    estado = "confirmada" if (gestion or not motivos) else "pendiente"
    recu = m.RecuperacionClase(
        alumno_id=alumno_id, ausencia_id=aus.id if aus else None, clase_id=clase.id, fecha=fecha,
        estado=estado, fuera_de_regla="; ".join(motivos)[:255] or None, pedida_por=pedida_por,
    )
    if gestion:
        recu.resuelta_por = usuario_id
        recu.resuelta_en = datetime.utcnow()
    db.session.add(recu)
    db.session.flush()
    return recu


def resolver_recuperacion(recu_id, aprobar, usuario_id, forzar=False):
    recu = db.session.get(m.RecuperacionClase, recu_id)
    if not recu:
        raise ErrorRegla("No encontré esa recuperación")
    if recu.estado != "pendiente":
        raise ErrorRegla("Esa recuperación ya está resuelta")
    if aprobar:
        clase = _clase(recu.clase_id)
        # puede que se haya llenado mientras esperaba
        if lugares_libres(clase, recu.fecha) <= 0 and not forzar:
            raise ErrorRegla("La clase se llenó mientras esperaba. Podés forzarla igual")
    recu.estado = "confirmada" if aprobar else "rechazada"
    recu.resuelta_por = usuario_id
    recu.resuelta_en = datetime.utcnow()
    db.session.flush()
    return recu


def cancelar_recuperacion(recu_id, usuario_id):
    recu = db.session.get(m.RecuperacionClase, recu_id)
    if not recu:
        raise ErrorRegla("No encontré esa recuperación")
    if recu.estado not in ACTIVAS:
        raise ErrorRegla("Esa recuperación ya no está activa")
    recu.estado = "cancelada"
    recu.resuelta_por = usuario_id
    recu.resuelta_en = datetime.utcnow()
    db.session.flush()
    return recu


# ---------- viajes (lapsos) ----------

def crear_lapso(alumno_id, desde, hasta, motivo=None, reemplazo_alumno_id=None, clase_id=None,
                origen="encargado", usuario_id=None):
    """Viaje del alumno. Si lo pide el agente queda pendiente hasta que el encargado lo confirme."""
    _alumno(alumno_id)
    if hasta < desde:
        raise ErrorRegla("La fecha de vuelta no puede ser antes que la de ida")
    if clase_id:
        _clase(clase_id)
        anotado = db.session.query(m.Inscripcion.id).filter(
            m.Inscripcion.alumno_id == alumno_id,
            m.Inscripcion.clase_id == clase_id,
            m.Inscripcion.desde <= hasta,
            or_(m.Inscripcion.hasta.is_(None), m.Inscripcion.hasta > desde),
        ).first()
        if not anotado:
            raise ErrorRegla("Ese alumno no está anotado en esa clase en esas fechas")
    if reemplazo_alumno_id:
        if reemplazo_alumno_id == alumno_id:
            raise ErrorRegla("El reemplazo tiene que ser otro alumno")
        _alumno(reemplazo_alumno_id)

    pisa = m.AusenciaLapso.query.filter(
        m.AusenciaLapso.alumno_id == alumno_id,
        m.AusenciaLapso.estado != "cancelado",
        m.AusenciaLapso.desde <= hasta,
        m.AusenciaLapso.hasta >= desde,
    )
    if clase_id:
        pisa = pisa.filter(or_(m.AusenciaLapso.clase_id.is_(None), m.AusenciaLapso.clase_id == clase_id))
    if pisa.first():
        raise ErrorRegla("Ya tiene un viaje cargado que se pisa con esas fechas")

    lap = m.AusenciaLapso(
        alumno_id=alumno_id, clase_id=clase_id or None, desde=desde, hasta=hasta,
        motivo=(motivo or "").strip()[:255] or None, reemplazo_alumno_id=reemplazo_alumno_id or None,
        estado="pendiente" if origen == "agente" else "confirmado", origen=origen, creado_por=usuario_id,
    )
    db.session.add(lap)
    db.session.flush()
    return lap


def confirmar_lapso(lapso_id):
    lap = db.session.get(m.AusenciaLapso, lapso_id)
    if not lap:
        raise ErrorRegla("No encontré ese viaje")
    if lap.estado != "pendiente":
        raise ErrorRegla("Ese viaje no está pendiente")
    lap.estado = "confirmado"
    db.session.flush()
    return lap


def cancelar_lapso(lapso_id):
    lap = db.session.get(m.AusenciaLapso, lapso_id)
    if not lap:
        raise ErrorRegla("No encontré ese viaje")
    lap.estado = "cancelado"
    db.session.flush()
    return lap
