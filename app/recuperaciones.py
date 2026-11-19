"""Faltas, recuperaciones y viajes: toda la lógica de las reglas en un solo lugar.

La usan las rutas del panel y, más adelante, el agente. Las reglas salen de
ConfigAcademia, así cada club pone las suyas:
- aviso_horas: con cuántas horas de anticipación hay que avisar la falta (24)
- recupera_mismo_mes: la recuperación tiene que caer en el mes de la falta (true)
- max_recuperaciones_mes: tope por alumno y por mes (1; 0 o null = sin tope)
- politicas: los textos que ven el alumno y el agente (ver politicas())

Cuando lo pide el alumno o el agente:
- falta avisada tarde o sin aviso: la clase cuenta como realizada y se pierde -> ErrorRegla
- tope del mes ya usado -> ErrorRegla
- sin falta para recuperar -> ErrorRegla
- falta en otro mes: queda 'pendiente' con el motivo y decide el encargado
La excepción la hace el encargado a mano (pedida_por="encargado"): queda confirmada
con el motivo anotado en fuera_de_regla.

Falta de la academia (origen="academia": clase suspendida, no vino el profe): no es culpa
del alumno, así que se recupera siempre y no cuenta para su tope. Ojo: NO es lo mismo
que origen="profe", que es el profe marcando que el alumno no vino (esa se pierde).
A CONFIRMAR CON GABI.

Lo que no se puede hacer ni con aprobación (clase que no existe, día equivocado,
clase llena) también tira ErrorRegla.

Fechas y horas siempre en hora argentina (ZONA_HORARIA). Las columnas DateTime
se guardan en UTC sin zona, como el resto de la base.
Acá no se hace commit: lo hace quien llama.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import extract, or_

from app import config_club
from app import models_academia as m
from app.extensions import db
from app.models import Alumno

ZONA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Argentina/Buenos_Aires"))

# Textos de políticas: los carga migrar_politicas.py en config_academia y cada club los cambia.
# Marcas que se reemplazan al leer: {aviso_horas}, {recuperaciones_mes} ("1 clase"), {inscripcion} ("$25.000").
POLITICAS_DEFAULT = [
    {"titulo": "Inscripción", "items": ["{inscripcion} (pago único)."]},
    {"titulo": "Reprogramación y asistencia", "items": [
        "Avisar con al menos {aviso_horas} hs de anticipación.",
        "Se permite recuperar hasta {recuperaciones_mes} al mes.",
        "Sin aviso previo de {aviso_horas} hs, la clase se considera realizada y se pierde.",
    ]},
    {"titulo": "Condiciones de pago", "items": [
        "Las clases se abonan por mes adelantado, el total, sin excepción.",
        "Para paquetes grupales, todos los participantes deben abonar en el mismo momento.",
    ]},
]

REGLAS_DEFAULT = {"aviso_horas": 24, "recupera_mismo_mes": True, "max_recuperaciones_mes": 1,
                  "contacto_club_alquiler": "",  # WhatsApp del club para alquiler de canchas
                  "politicas": POLITICAS_DEFAULT}
ACTIVAS = ("confirmada", "pendiente")   # las que ocupan la falta y cuentan para el tope
# falta que no es culpa del alumno (clase suspendida, no vino el profe): ver arriba
ORIGEN_ACADEMIA = "academia"


class ErrorRegla(ValueError):
    """Algo que no se puede hacer (o que la regla no deja pedir: solo el encargado hace la excepción).
    codigo: aviso_tarde / tope / sin_falta, para que el agente arme su texto. None en el resto."""

    def __init__(self, mensaje, codigo=None):
        super().__init__(mensaje)
        self.codigo = codigo


# ---------- reglas y horas ----------

def regla(clave):
    # una sola consulta por pedido para toda la config (ver config_club)
    texto = config_club.valor(clave)
    if texto is None:
        return REGLAS_DEFAULT.get(clave)
    try:
        return json.loads(texto)
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


def _plata(monto):
    return "$" + f"{monto:,}".replace(",", ".")


class _Marcas(dict):
    def __missing__(self, clave):  # una llave que no conozco queda como está
        return "{" + clave + "}"


def _rellenar(texto, marcas):
    try:
        return texto.format_map(marcas)
    except (ValueError, IndexError):  # una llave suelta escrita a mano: va tal cual
        return texto


def politicas():
    """[{titulo, items: [texto]}] de config_academia, con las marcas ya reemplazadas.
    Si los números cambian (aviso_horas, tope, inscripción), el texto se acomoda solo."""
    tope = int(regla("max_recuperaciones_mes") or 0)
    try:
        inscripcion = int(regla("inscripcion"))
    except (TypeError, ValueError):
        inscripcion = 0
    marcas = _Marcas(
        aviso_horas=regla("aviso_horas") or 0,
        recuperaciones_mes=f"{tope} clase{'s' if tope != 1 else ''}",
        inscripcion=_plata(inscripcion) if inscripcion > 0 else "Monto a confirmar con el encargado",
    )
    secciones = regla("politicas")
    if not isinstance(secciones, list):  # falta la clave o la cargaron con otra forma: las de siempre
        secciones = POLITICAS_DEFAULT
    salida = []
    for seccion in secciones:
        if not isinstance(seccion, dict):
            continue
        items = [_rellenar(str(t), marcas) for t in seccion.get("items") or [] if str(t).strip()]
        if items:
            salida.append({"titulo": str(seccion.get("titulo") or ""), "items": items})
    return salida


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
    if not clase.vigente_en(fecha):
        raise ErrorRegla("Esa clase no se da en esa fecha (es de otra temporada)")


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


def fechas_de_clase(clase, desde, hasta):
    """Las fechas entre desde y hasta (incluidas) en que la clase se da: su día y su temporada.
    No mira 'activa': eso lo filtra quien llama."""
    f = desde + timedelta(days=(clase.dia_semana - desde.weekday()) % 7)
    while f <= hasta:
        if clase.vigente_en(f):
            yield f
        f += timedelta(days=7)


def _en_lote(clases, desde, hasta, fechas_de):
    """La lógica de alumnos_del_dia para varias clases y varias fechas, con 4 consultas en total.
    fechas_de(clase) -> las fechas a armar de esa clase. Devuelve {(clase_id, fecha): (vienen, no_vienen)}."""
    ids = [c.id for c in clases]
    if not ids:
        return {}

    # inscripciones que tocan el rango; después se mira cada fecha ('hasta' = primer día que ya no está)
    insc = {i: [] for i in ids}
    for cid, aid, d, h in db.session.query(
            m.Inscripcion.clase_id, m.Inscripcion.alumno_id, m.Inscripcion.desde, m.Inscripcion.hasta).filter(
            m.Inscripcion.clase_id.in_(ids), m.Inscripcion.desde <= hasta,
            or_(m.Inscripcion.hasta.is_(None), m.Inscripcion.hasta > desde)):
        insc[cid].append((aid, d, h))

    # los viajes de todas las clases (clase_id vacío) y los de estas
    lapsos = m.AusenciaLapso.query.filter(
        m.AusenciaLapso.estado == "confirmado",
        m.AusenciaLapso.desde <= hasta,
        m.AusenciaLapso.hasta >= desde,
        or_(m.AusenciaLapso.clase_id.is_(None), m.AusenciaLapso.clase_id.in_(ids)),
    ).all()

    faltan_de = {}
    for cid, f, aid in db.session.query(m.Ausencia.clase_id, m.Ausencia.fecha, m.Ausencia.alumno_id).filter(
            m.Ausencia.clase_id.in_(ids), m.Ausencia.fecha.between(desde, hasta)):
        faltan_de.setdefault((cid, f), []).append(aid)

    recuperan_de = {}
    for cid, f, aid in db.session.query(
            m.RecuperacionClase.clase_id, m.RecuperacionClase.fecha, m.RecuperacionClase.alumno_id).filter(
            m.RecuperacionClase.clase_id.in_(ids), m.RecuperacionClase.fecha.between(desde, hasta),
            m.RecuperacionClase.estado == "confirmada"):
        recuperan_de.setdefault((cid, f), []).append(aid)

    salida = {}
    for c in clases:
        for f in fechas_de(c):
            fijos = {aid for aid, d, h in insc[c.id] if d <= f and (h is None or h > f)}
            no_vienen, reemplazos = {}, []
            for lap in lapsos:
                if lap.clase_id not in (None, c.id) or not (lap.desde <= f <= lap.hasta):
                    continue
                if lap.alumno_id in fijos:
                    no_vienen[lap.alumno_id] = "viaje"
                    if lap.reemplazo_alumno_id:
                        reemplazos.append(lap.reemplazo_alumno_id)
            for aid in faltan_de.get((c.id, f), ()):
                if aid in fijos:
                    no_vienen.setdefault(aid, "falta")

            vienen = {aid: "fijo" for aid in fijos if aid not in no_vienen}
            for aid in reemplazos:
                vienen.setdefault(aid, "reemplazo")
            for aid in recuperan_de.get((c.id, f), ()):
                vienen.setdefault(aid, "recupera")
            salida[(c.id, f)] = (vienen, no_vienen)
    return salida


def alumnos_en_rango(clases, desde, hasta):
    """alumnos_del_dia para varias clases en un rango (ej. la semana), con 4 consultas en total.
    Solo arma las fechas en que cada clase se da. Devuelve {(clase_id, fecha): (vienen, no_vienen)}.
    Si tocás la lógica, tocá también alumnos_del_dia: tienen que dar igual."""
    return _en_lote(clases, desde, hasta, lambda c: fechas_de_clase(c, desde, hasta))


def alumnos_del_dia_en_lote(clases, fecha):
    """alumnos_del_dia para varias clases de la misma fecha. Devuelve {clase_id: (vienen, no_vienen)}.
    Arma la fecha para todas las que le pasen, sin mirar el día (eso lo filtra quien llama)."""
    lote = _en_lote(clases, fecha, fecha, lambda c: (fecha,))
    return {c.id: lote[(c.id, fecha)] for c in clases}


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
    if origen == ORIGEN_ACADEMIA:
        a_tiempo = True  # la suspendió la academia: no hay aviso tarde que valga
    if a_tiempo is None:
        a_tiempo = es_a_tiempo(clase, fecha, avisada_en)
    aus = m.Ausencia(alumno_id=alumno_id, clase_id=clase.id, fecha=fecha, origen=origen,
                     motivo=(motivo or "").strip()[:255] or None,
                     avisada_en=avisada_en, a_tiempo=bool(a_tiempo))
    db.session.add(aus)
    db.session.flush()
    return aus, True


def es_de_academia(aus):
    """Falta que no es culpa del alumno (clase suspendida, no vino el profe). A confirmar con Gabi."""
    return aus.origen == ORIGEN_ACADEMIA


def faltas_recuperables(alumno_id, para_fecha=None, solo_en_regla=False):
    """Faltas sin recuperación activa, de la más conveniente a la menos:
    primero las del mismo mes que para_fecha, después las de la academia (no gastan el tope),
    después las avisadas a tiempo, después la más vieja.
    solo_en_regla: deja afuera las avisadas tarde o sin aviso (esas se pierden)."""
    para_fecha = para_fecha or hoy()
    usadas = db.session.query(m.RecuperacionClase.ausencia_id).filter(
        m.RecuperacionClase.ausencia_id.isnot(None),
        m.RecuperacionClase.estado.in_(ACTIVAS),
    )
    faltas = m.Ausencia.query.filter(
        m.Ausencia.alumno_id == alumno_id,
        m.Ausencia.id.notin_(usadas),
    ).all()
    if solo_en_regla:
        faltas = [a for a in faltas if a.a_tiempo or es_de_academia(a)]
    faltas.sort(key=lambda a: (_mes(a.fecha) != _mes(para_fecha), not es_de_academia(a), not a.a_tiempo, a.fecha))
    return faltas


def sincronizar_asistencia(clase, fecha, alumno_id, estado):
    """Lo que marca el profe en Mis clases se refleja en Ausencia (solo para alumnos fijos).
    'No vino' -> si no había falta, queda una sin aviso. Si ya había una no se toca nunca:
    el aviso a tiempo sale del agente o del encargado, no del profe.
    """
    if not inscripto(alumno_id, clase.id, fecha):
        return
    aus = m.Ausencia.query.filter_by(alumno_id=alumno_id, clase_id=clase.id, fecha=fecha).first()

    if estado == "presente":
        # vino al final: la falta que había puesto el profe se borra, salvo que ya la esté usando
        if aus and aus.origen == "profe" and not recuperacion_activa(aus.id):
            db.session.delete(aus)
        return

    # la que ya está (del agente, del encargado o una que pasaron a tiempo) queda como está
    if not aus:
        db.session.add(m.Ausencia(alumno_id=alumno_id, clase_id=clase.id, fecha=fecha, origen="profe",
                                  a_tiempo=False, motivo="sin aviso"))
        db.session.flush()


# ---------- recuperaciones ----------

def _usadas_en_mes(alumno_id, fecha):
    """Recuperaciones activas del alumno en ese mes que cuentan para su tope.
    Las de faltas de la academia no cuentan (no fue culpa del alumno)."""
    de_academia = db.session.query(m.Ausencia.id).filter(
        m.Ausencia.alumno_id == alumno_id, m.Ausencia.origen == ORIGEN_ACADEMIA)
    return m.RecuperacionClase.query.filter(
        m.RecuperacionClase.alumno_id == alumno_id,
        m.RecuperacionClase.estado.in_(ACTIVAS),
        extract("year", m.RecuperacionClase.fecha) == fecha.year,
        extract("month", m.RecuperacionClase.fecha) == fecha.month,
        or_(m.RecuperacionClase.ausencia_id.is_(None), m.RecuperacionClase.ausencia_id.notin_(de_academia)),
    ).count()


def recuperaciones_disponibles(alumno_id, fecha=None):
    """Cuántas le quedan en el mes de esa fecha (None = sin tope). Para el Inicio del alumno."""
    tope = int(regla("max_recuperaciones_mes") or 0)
    if not tope:
        return None
    return max(tope - _usadas_en_mes(alumno_id, fecha or hoy()), 0)


def chequear_regla(alumno_id, fecha, aus=None):
    """Para lo que pide el alumno o el agente: devuelve la falta que se usa para recuperar el día
    'fecha', o tira ErrorRegla con codigo si la regla no lo deja. aus vacío = elige la mejor.
    - aviso_tarde: la falta fue sin aviso o tarde -> la clase cuenta como realizada y se pierde
    - tope: ya usó las recuperaciones del mes (las de faltas de la academia no cuentan)
    - sin_falta: no hay ninguna falta para recuperar
    """
    horas = regla("aviso_horas") or 0
    if aus is None:
        candidatas = faltas_recuperables(alumno_id, para_fecha=fecha, solo_en_regla=True)
        if candidatas:
            aus = candidatas[0]
        else:
            # si lo único que tiene en ese mes son faltas tarde, le digo eso y no "no tenés faltas"
            tardes = [a for a in faltas_recuperables(alumno_id, para_fecha=fecha) if _mes(a.fecha) == _mes(fecha)]
            if tardes:
                aus = tardes[0]
            else:
                raise ErrorRegla("No tiene una falta avisada a tiempo para recuperar", codigo="sin_falta")
    de_academia = es_de_academia(aus)
    if not aus.a_tiempo and not de_academia:
        raise ErrorRegla(f"La falta del {aus.fecha:%d/%m} fue sin aviso o con menos de {horas} hs: "
                         "la clase se considera realizada y no se recupera", codigo="aviso_tarde")
    tope = int(regla("max_recuperaciones_mes") or 0)
    if tope and not de_academia:
        usadas = _usadas_en_mes(alumno_id, fecha)
        if usadas >= tope:
            raise ErrorRegla(f"Ya usó {usadas} recuperación(es) en {fecha:%m/%Y} y el tope es {tope}",
                             codigo="tope")
    return aus


def pedir_recuperacion(alumno_id, clase_id, fecha, ausencia_id=None, pedida_por="agente",
                       forzar=False, usuario_id=None):
    """Arma la recuperación. Alumno o agente: falta tarde, tope usado o sin falta -> ErrorRegla
    (con codigo); falta de otro mes -> pendiente con el motivo; si cumple todo, confirmada.
    Si la carga el encargado queda confirmada igual (es la excepción a mano), con el motivo anotado.
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

    # la falta que se recupera: la que eligieron o la más conveniente.
    # El alumno y el agente solo pueden usar las que entran en la regla; el encargado, cualquiera.
    if ausencia_id:
        aus = db.session.get(m.Ausencia, ausencia_id)
        if not aus or aus.alumno_id != alumno_id:
            raise ErrorRegla("Esa falta no es de ese alumno")
        if recuperacion_activa(aus.id):
            raise ErrorRegla("Esa falta ya tiene una recuperación")
    elif gestion:
        candidatas = faltas_recuperables(alumno_id, para_fecha=fecha)
        aus = candidatas[0] if candidatas else None
    else:
        aus = None  # la elige chequear_regla
    # lo que la regla no deja pedir: se rechaza (antes quedaba pendiente). La excepción, a mano.
    if not gestion:
        aus = chequear_regla(alumno_id, fecha, aus)
    de_academia = bool(aus and es_de_academia(aus))
    tope = int(regla("max_recuperaciones_mes") or 0)
    usadas = _usadas_en_mes(alumno_id, fecha) if tope and not de_academia else 0

    vienen, _ = alumnos_del_dia(clase, fecha)
    if alumno_id in vienen:
        raise ErrorRegla("Ya está en esa clase ese día")
    llena = clase.cupo - len(vienen) <= 0
    if llena and not forzar:
        raise ErrorRegla("La clase está llena ese día")

    # motivos: lo que queda pendiente (otro mes) o, si la carga el encargado, la excepción que hizo
    motivos = []
    if not aus:
        motivos.append("no tiene una falta registrada para recuperar")
    else:
        if not aus.a_tiempo and not de_academia:
            motivos.append(f"la falta del {aus.fecha:%d/%m} fue sin aviso o con aviso tarde")
        if regla("recupera_mismo_mes") and _mes(aus.fecha) != _mes(fecha):
            motivos.append(f"la falta es del {aus.fecha:%d/%m} y quiere recuperar en otro mes")
    if tope and usadas >= tope:
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
