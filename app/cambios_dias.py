"""Cambio de días de un alumno: deja unas clases fijas y pasa a otras desde una fecha.

Lo usan el agente (el alumno lo pide y queda pendiente del encargado, o el encargado lo
propone y queda pendiente del alumno) y el panel, que lo aprueba con aplicar() o lo
rechaza con rechazar(). Solo aplicar() toca inscripciones y la cuota.

Ojo con Inscripcion.hasta: es el primer día que ya NO va (igual que Mis clases y
recuperaciones). Una inscripción vale en f si desde <= f y (hasta vacío o hasta > f).
"""
import json
import re
from datetime import date, datetime, timedelta

from sqlalchemy import or_

from app import planilla
from app import recuperaciones as rec
from app.cuotas import FRANJA_POR_AMBITO, cargar_tarifas, clases_del_mes, cuota_de
from app.extensions import db
from app.models import Alumno, CambioPendiente
from app.models_academia import Auditoria, Clase, ConfigAcademia, Inscripcion
from app.models_cuotas import CuotaMes, PagoCuota

NOMBRE_DIA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
MESES = [m.lower() for m in planilla.MESES]

_RX_FECHA = re.compile(r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?!\d)")
_RX_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")


# ---------------------------------------------------------------- fechas
def primero_del_mes_siguiente(f: date) -> date:
    return date(f.year + (f.month == 12), f.month % 12 + 1, 1)


def _dia_de_corte() -> int | None:
    """Hasta qué día del mes se puede pedir el cambio para el mes siguiente.
    Vacío = hasta el último día (lo de Gabi). Cada club lo pone en config_academia."""
    cfg = db.session.get(ConfigAcademia, "cambio_dias_corte")
    try:
        n = int(json.loads(cfg.valor)) if cfg else None
    except (TypeError, ValueError):
        return None
    return n if n and 1 <= n <= 31 else None


def vigencia_minima(hoy: date | None = None) -> date:
    """La primera fecha en que puede arrancar un cambio pedido hoy: el 1 del mes siguiente,
    o el del otro si ya pasó el día de corte."""
    hoy = hoy or rec.hoy()
    vig = primero_del_mes_siguiente(hoy)
    corte = _dia_de_corte()
    if corte and hoy.day > corte:
        vig = primero_del_mes_siguiente(vig)
    return vig


def leer_fecha(texto, hoy: date | None = None) -> date | None:
    """'diciembre', 'desde enero', '1/12', '2026-12-01', 'el mes que viene' -> fecha.
    Con un mes solo devuelve el 1 de ese mes (el próximo que venga). None si no se entiende."""
    t = planilla._norm(texto)
    if not t:
        return None
    hoy = hoy or rec.hoy()
    try:
        if (m := _RX_ISO.search(t)):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if (m := _RX_FECHA.search(t)):
            anio = int(m.group(3)) if m.group(3) else None
            if anio is not None and anio < 100:
                anio += 2000
            f = date(anio or hoy.year, int(m.group(2)), int(m.group(1)))
            if anio is None and f < hoy - timedelta(days=60):
                f = f.replace(year=hoy.year + 1)  # "1/1" dicho en noviembre es el que viene
            return f
    except ValueError:
        return None
    if "este mes" in t:
        return hoy.replace(day=1)
    if "mes que viene" in t or "proximo mes" in t or "mes siguiente" in t:
        return primero_del_mes_siguiente(hoy)
    for i, nombre in enumerate(MESES):
        if re.search(rf"\b{nombre}\b", t):
            anio = hoy.year + (i + 1 < hoy.month)
            return date(anio, i + 1, 1)
    return None


def fecha_corta(f: date) -> str:
    return f"{f.day}/{f.month}"


# ---------------------------------------------------------------- clases y cupos
def vigente_en(fecha: date):
    """Filtro de inscripciones que valen en esa fecha."""
    return db.and_(Inscripcion.desde <= fecha,
                   or_(Inscripcion.hasta.is_(None), Inscripcion.hasta > fecha))


def ocupados(clase_ids: list[int], fecha: date) -> dict[int, int]:
    """Anotados fijos en cada clase en esa fecha. Los cambios ya aprobados cuentan solos,
    porque al aprobarlos quedan como inscripciones con su desde/hasta."""
    if not clase_ids:
        return {}
    return dict(
        db.session.query(Inscripcion.clase_id, db.func.count(Inscripcion.id))
        .filter(Inscripcion.clase_id.in_(clase_ids), vigente_en(fecha))
        .group_by(Inscripcion.clase_id).all()
    )


def libres(clase: Clase, fecha: date) -> int:
    return clase.cupo - ocupados([clase.id], fecha).get(clase.id, 0)


def lleno_desde(clase: Clase, fecha: date) -> bool:
    """True si en esa fecha, o en alguna más adelante en que entra gente, no queda lugar."""
    fechas = {fecha} | {d for (d,) in db.session.query(Inscripcion.desde).filter(
        Inscripcion.clase_id == clase.id, Inscripcion.desde > fecha).distinct()}
    return any(libres(clase, f) <= 0 for f in fechas)


def clases_del_alumno(alumno_id: int, fecha: date) -> list[Clase]:
    """Clases fijas activas en las que está anotado en esa fecha."""
    return (Clase.query.join(Inscripcion, Inscripcion.clase_id == Clase.id)
            .filter(Inscripcion.alumno_id == alumno_id, Clase.activa.is_(True), vigente_en(fecha))
            .order_by(Clase.dia_semana, Clase.hora_inicio).distinct().all())


def franja_de(clase: Clase) -> str | None:
    return FRANJA_POR_AMBITO.get(clase.ambito)


def texto_clase(c: Clase) -> str:
    return f"{NOMBRE_DIA[c.dia_semana]} {c.hora_inicio.strftime('%H:%M')}"


def texto_clases(clases: list[Clase]) -> str:
    nombres = [texto_clase(c) for c in clases]
    if len(nombres) <= 1:
        return "".join(nombres)
    return ", ".join(nombres[:-1]) + " y " + nombres[-1]


def _de_hora(clases: list[Clase], hora: tuple[int, int | None]) -> list[Clase]:
    h, mi = hora

    def con(hh):
        return [c for c in clases if c.hora_inicio.hour == hh and (mi is None or c.hora_inicio.minute == mi)]
    return con(h) or (con(h + 12) if h < 12 else [])  # "a las 5" puede ser 17


def con_lugar(fecha: date, franjas: set, nivel_ok=None, sin_dias: set = frozenset(),
              excluir: set = frozenset()) -> list[Clase]:
    """Grupales activas con lugar en esa fecha, para ofrecer como alternativa."""
    clases = (Clase.query.filter(Clase.activa.is_(True), Clase.tipo == "grupal")
              .order_by(Clase.dia_semana, Clase.hora_inicio).all())
    clases = [c for c in clases if c.dia_semana not in sin_dias and c.id not in excluir
              and (not franjas or franja_de(c) in franjas) and (nivel_ok is None or nivel_ok(c))]
    cuentas = ocupados([c.id for c in clases], fecha)
    return [c for c in clases if c.cupo - cuentas.get(c.id, 0) > 0]


def armar(alumno_id: int, fecha: date, dias_nuevos: list[int], hora=None,
          dias_deja: list[int] | None = None, clase_ids: list[int] | None = None, nivel_ok=None) -> dict:
    """Arma el cambio sin guardar nada. Devuelve un dict con 'status':
    ok (deja, nuevas, quedan), sin_clases, faltan_dias, no_tiene_dia (dias, actuales),
    elegir_hora (dia, opciones), sin_cupo (dia, alternativas), sin_cambios.
    nivel_ok(clase) -> bool filtra por el nivel del alumno (lo pasa el agente)."""
    actuales = clases_del_alumno(alumno_id, fecha)
    if not actuales:
        return {"status": "sin_clases"}
    ids_actuales = {c.id for c in actuales}

    if dias_deja:
        tiene = {c.dia_semana for c in actuales}
        faltan = [d for d in dias_deja if d not in tiene]
        if faltan:
            return {"status": "no_tiene_dia", "dias": faltan, "actuales": actuales}
        deja = [c for c in actuales if c.dia_semana in dias_deja]
    else:
        # sin decir qué deja: deja todas las grupales (las particulares siguen)
        deja = [c for c in actuales if c.tipo == "grupal"] or actuales
    franjas = {franja_de(c) for c in deja} - {None}

    base = Clase.query.filter(Clase.activa.is_(True), Clase.tipo == "grupal")
    nuevas = []
    if clase_ids:
        nuevas = base.filter(Clase.id.in_(clase_ids)).order_by(Clase.dia_semana, Clase.hora_inicio).all()
    cubiertos = {c.dia_semana for c in nuevas}
    pendientes = [d for d in dict.fromkeys(dias_nuevos or []) if d not in cubiertos]
    if not nuevas and not pendientes:
        return {"status": "faltan_dias"}

    pedidos = set(dias_nuevos or []) | cubiertos
    horas_de_antes = {c.hora_inicio for c in deja}

    def sin_cupo(dia):
        return {"status": "sin_cupo", "dia": dia,
                "alternativas": con_lugar(fecha, franjas, nivel_ok, sin_dias=pedidos, excluir=ids_actuales)}

    for c in nuevas:
        if c.id not in ids_actuales and libres(c, fecha) <= 0:
            return sin_cupo(c.dia_semana)

    for dia in pendientes:
        cand = base.filter(Clase.dia_semana == dia).order_by(Clase.hora_inicio).all()
        cand = [c for c in cand if franja_de(c) in franjas] or cand
        if nivel_ok is not None:
            cand = [c for c in cand if nivel_ok(c)]
        if hora:
            cand = _de_hora(cand, hora)
        ya = [c for c in cand if c.id in ids_actuales]
        if ya:  # ese día ya va: lo mantiene
            nuevas.append(ya[0])
            continue
        cuentas = ocupados([c.id for c in cand], fecha)
        hay = [c for c in cand if c.cupo - cuentas.get(c.id, 0) > 0]
        if not hay:
            return sin_cupo(dia)
        if len(hay) > 1:
            misma_hora = [c for c in hay if c.hora_inicio in horas_de_antes]
            if len(misma_hora) != 1:
                return {"status": "elegir_hora", "dia": dia, "opciones": hay}
            hay = misma_hora
        nuevas.append(hay[0])

    ids_nuevas = {c.id for c in nuevas}
    deja = [c for c in deja if c.id not in ids_nuevas]
    nuevas = [c for c in nuevas if c.id not in ids_actuales]
    if not deja and not nuevas:
        return {"status": "sin_cambios", "actuales": actuales}
    ids_deja = {c.id for c in deja}
    quedan = sorted([c for c in actuales if c.id not in ids_deja] + nuevas,
                    key=lambda c: (c.dia_semana, c.hora_inicio))
    return {"status": "ok", "deja": deja, "nuevas": nuevas, "quedan": quedan, "actuales": actuales}


# ---------------------------------------------------------------- precio
def precio_de(clases: list[Clase]) -> tuple[int | None, str]:
    """(cuota mensual, detalle). None si no hay una tarifa exacta: nunca se inventa."""
    if not clases:
        return None, "sin clases"
    r = cuota_de(clases, cargar_tarifas())
    if r["total"] <= 0 or r["avisos"]:
        return None, "; ".join(r["avisos"]) or "sin tarifa"
    return int(r["total"]), "; ".join(r["lineas"])


# ---------------------------------------------------------------- solicitudes
def ids(texto) -> list[int]:
    try:
        return [int(x) for x in json.loads(texto or "[]")]
    except (TypeError, ValueError):
        return []


def pendientes_del_alumno(alumno_id: int, espera: str | None = None) -> list[CambioPendiente]:
    q = CambioPendiente.query.filter_by(alumno_id=alumno_id, tipo="cambio_dias", estado="pendiente")
    if espera:
        q = q.filter_by(espera=espera)
    return q.order_by(CambioPendiente.creado_en.desc()).all()


def crear(alumno, deja: list[Clase], nuevas: list[Clase], vigente_desde: date,
          origen: str, espera: str, pedido_por: str, precio: int | None) -> CambioPendiente:
    """Guarda la solicitud. Si el alumno ya tenía otra pendiente igual, la nueva la reemplaza."""
    for viejo in pendientes_del_alumno(alumno.id):
        viejo.estado = "cancelado"
        viejo.motivo_rechazo = "reemplazado por un pedido nuevo"
    propuesta = (f"Desde el {fecha_corta(vigente_desde)}: deja {texto_clases(deja) or 'nada'} "
                 f"y pasa a {texto_clases(nuevas) or 'nada'}. Cuota estimada: "
                 + (f"${precio:,}".replace(",", ".") if precio else "sin tarifa exacta") + ".")
    cambio = CambioPendiente(
        alumno_telefono=alumno.telefono, alumno_id=alumno.id, tipo="cambio_dias",
        propuesta=propuesta, estado="pendiente", espera=espera, origen=origen,
        pedido_por=pedido_por, vigente_desde=vigente_desde, precio_estimado=precio,
        clases_deja=json.dumps([c.id for c in deja]),
        clases_nuevas=json.dumps([c.id for c in nuevas]),
    )
    db.session.add(cambio)
    db.session.commit()
    return cambio


# ---------------------------------------------------------------- aprobar y rechazar (panel)
class ErrorCambio(ValueError):
    """No se puede aplicar tal cual: el panel muestra el mensaje."""


def clases_por_ids(ids_: list[int]) -> list[Clase]:
    if not ids_:
        return []
    return Clase.query.filter(Clase.id.in_(ids_)).order_by(Clase.dia_semana, Clase.hora_inicio).all()


def anotado_en(alumno_id: int, clase_id: int, fecha: date) -> Inscripcion | None:
    return Inscripcion.query.filter(Inscripcion.clase_id == clase_id, Inscripcion.alumno_id == alumno_id,
                                    vigente_en(fecha)).first()


def sin_lugar(cambio: CambioPendiente) -> list[Clase]:
    """Clases nuevas del cambio que ya no tienen lugar en su fecha (aprobarlo va a fallar)."""
    fecha = cambio.vigente_desde
    if not fecha or not cambio.alumno_id:
        return []
    return [c for c in clases_por_ids(ids(cambio.clases_nuevas))
            if not anotado_en(cambio.alumno_id, c.id, fecha) and lleno_desde(c, fecha)]


def _auditar(cambio: CambioPendiente, accion: str, despues: dict, usuario_id: int | None) -> None:
    db.session.add(Auditoria(
        entidad="cambio_dias", entidad_id=cambio.id, accion=accion,
        antes=json.dumps({"deja": ids(cambio.clases_deja)}),
        despues=json.dumps(despues, ensure_ascii=False, default=str),
        usuario_id=usuario_id,
    ))


def _para_resolver(cambio_id: int) -> CambioPendiente:
    cambio = CambioPendiente.query.filter_by(id=cambio_id).with_for_update().first()
    if not cambio or cambio.tipo != "cambio_dias":
        raise ErrorCambio("No encontré ese cambio de días")
    if cambio.estado != "pendiente":
        raise ErrorCambio(f"Ese cambio ya está {cambio.estado}")
    if cambio.espera == "alumno":
        raise ErrorCambio("Ese cambio todavía espera que el alumno lo acepte")
    return cambio


def recalcular_cuota(alumno_id: int, mes: date) -> dict:
    """Si la cuota del mes ya estaba generada y no tiene pagos, la vuelve a calcular.
    Con pagos o ajustada a mano no la pisa: devuelve un aviso para el encargado."""
    cuota = CuotaMes.query.filter_by(alumno_id=alumno_id, mes=mes, concepto="cuota").first()
    nombre_mes = MESES[mes.month - 1]
    if not cuota:
        return {"cuota": "sin_generar"}
    pagos = PagoCuota.query.filter_by(alumno_id=alumno_id, mes=mes, concepto="cuota").count()
    if pagos:
        return {"cuota": "con_pagos", "aviso": f"La cuota de {nombre_mes} ya tiene pagos: no la toqué, revisala a mano."}
    if cuota.monto_calculado is not None and cuota.monto != cuota.monto_calculado:
        return {"cuota": "ajustada", "aviso": f"La cuota de {nombre_mes} estaba ajustada a mano: no la toqué, revisala."}
    r = cuota_de(clases_del_mes(mes, alumno_id).get(alumno_id, []), cargar_tarifas(mes))
    if r["total"] <= 0 or r["sin_tarifa"]:
        # si alguna clase no tiene precio no la recalculo: bajaría la cuota sin que nadie lo vea
        return {"cuota": "sin_tarifa", "aviso": f"No pude calcular la cuota de {nombre_mes}: revisala a mano."}
    antes = cuota.monto
    cuota.monto = cuota.monto_calculado = int(r["total"])
    cuota.detalle = "; ".join(r["lineas"] + [f"AVISO: {a}" for a in r["avisos"]])
    cuota.nota = ((cuota.nota or "") + f" Recalculada por cambio de días ({antes} -> {cuota.monto}).").strip()[:200]
    return {"cuota": "recalculada", "antes": antes, "ahora": cuota.monto}


def aplicar(cambio_id: int, usuario_id: int | None) -> dict:
    """Aprueba: cierra las clases que deja (hasta = vigente_desde, el primer día que ya no va),
    abre las nuevas desde vigente_desde, vuelve a mirar el cupo, audita y recalcula la cuota."""
    cambio = _para_resolver(cambio_id)
    fecha = cambio.vigente_desde
    if not fecha or not cambio.alumno_id:
        raise ErrorCambio("Al cambio le falta el alumno o la fecha")
    deja, nuevas = clases_por_ids(ids(cambio.clases_deja)), clases_por_ids(ids(cambio.clases_nuevas))

    # cupo de nuevo, con las clases bloqueadas por si aprueban dos a la vez
    if nuevas:
        db.session.query(Clase).filter(Clase.id.in_([c.id for c in nuevas])).with_for_update().all()
    for c in nuevas:
        if not c.activa:
            raise ErrorCambio(f"La clase del {texto_clase(c)} ya no está activa")
        if not anotado_en(cambio.alumno_id, c.id, fecha) and lleno_desde(c, fecha):
            raise ErrorCambio(f"La clase del {texto_clase(c)} ya no tiene lugar desde el {fecha_corta(fecha)}")

    for c in deja:
        ins = anotado_en(cambio.alumno_id, c.id, fecha)
        if not ins:
            raise ErrorCambio(f"El alumno ya no está en la clase del {texto_clase(c)} el {fecha_corta(fecha)}")
        ins.hasta = fecha
    for c in nuevas:
        abierta = Inscripcion.query.filter(Inscripcion.clase_id == c.id, Inscripcion.alumno_id == cambio.alumno_id,
                                           or_(Inscripcion.hasta.is_(None), Inscripcion.hasta > fecha)).first()
        if abierta:
            continue  # ya está (o ya entra): no se duplica
        db.session.add(Inscripcion(clase_id=c.id, alumno_id=cambio.alumno_id, desde=fecha))
    db.session.flush()

    cambio.estado = "aprobado"
    cambio.espera = None
    cambio.resuelto_en = datetime.utcnow()
    cambio.resuelto_por = usuario_id
    cuota = recalcular_cuota(cambio.alumno_id, fecha.replace(day=1))
    quedan = clases_del_alumno(cambio.alumno_id, fecha)
    _auditar(cambio, "aprobado", {"nuevas": [c.id for c in nuevas], "desde": fecha, "cuota": cuota}, usuario_id)
    db.session.commit()
    return {"cambio": cambio, "quedan": quedan, "cuota": cuota}


def rechazar(cambio_id: int, usuario_id: int | None, motivo: str) -> CambioPendiente:
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErrorCambio("Poné el motivo del rechazo, así se lo contamos al alumno")
    cambio = _para_resolver(cambio_id)
    cambio.estado = "rechazado"
    cambio.espera = None
    cambio.motivo_rechazo = motivo[:500]
    cambio.resuelto_en = datetime.utcnow()
    cambio.resuelto_por = usuario_id
    _auditar(cambio, "rechazado", {"motivo": cambio.motivo_rechazo}, usuario_id)
    db.session.commit()
    return cambio


# ---------------------------------------------------------------- textos para el alumno
def _pesos(n: int) -> str:
    return "$" + f"{int(n):,}".replace(",", ".")


def texto_aprobado(alumno: Alumno, cambio: CambioPendiente, quedan: list[Clase], cuota: dict) -> str:
    nombre = (alumno.nombre or "").split()[0] if alumno else ""
    monto = cuota.get("ahora") if cuota.get("cuota") == "recalculada" else cambio.precio_estimado
    texto = (f"¡Hola{' ' + nombre if nombre else ''}! \U0001F64C Ya quedó aprobado tu cambio de días: "
             f"desde el {fecha_corta(cambio.vigente_desde)} venís {texto_clases(quedan) or 'sin clases fijas'}.")
    if monto:
        texto += f" Tu cuota pasa a ser de {_pesos(monto)} por mes."
    return texto + " ¡Nos vemos en la cancha! \U0001F3BE"


def texto_rechazado(alumno: Alumno, cambio: CambioPendiente) -> str:
    nombre = (alumno.nombre or "").split()[0] if alumno else ""
    desde = f" desde el {fecha_corta(cambio.vigente_desde)}" if cambio.vigente_desde else ""
    return (f"Hola{' ' + nombre if nombre else ''}, te cuento que el cambio de días que pediste{desde} "
            f"no se pudo aprobar. Motivo: {cambio.motivo_rechazo}. Seguís con tus días de siempre. "
            "Si querés, escribime y buscamos otra opción.")


def telefono_whatsapp(cambio: CambioPendiente) -> str:
    """Número para escribirle: el mismo desde el que pidió, o el de la base con 549 adelante."""
    for t in (cambio.pedido_por if cambio.origen == "alumno" else None, cambio.alumno_telefono):
        dig = re.sub(r"\D", "", str(t or ""))
        if len(dig) == 10:
            return "549" + dig
        if len(dig) == 12 and dig.startswith("54"):
            return "549" + dig[2:]
        if len(dig) == 13 and dig.startswith("549"):
            return dig
    return ""
