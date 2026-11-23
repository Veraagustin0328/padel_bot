"""Cuántos alumnos de la planilla ya están cargados en la base, por grupo ("X de Y"). SOLO LECTURA.

- Grupo = turno de cobro (franja de app/cuotas.py): cada ámbito de clase cae en uno
  (kids y kids_pro van juntos en Kids). El nombre sale de config_academia 'nombres_grupos'
  ({"manana": "...", ...}) y si no está, del nombre del primer ámbito de ese turno.
- Y = filas de "listado alumnos" con NOMBRE, ESTADO vacío o activo y PLANILLA de ese grupo.
- X = de esas filas, las que tienen un alumno activo en la base con el mismo nombre
  (mismo cruce que comparar_planilla_base.py: sin tildes, mayúsculas ni signos).
- Si no se puede leer la planilla, o un grupo no tiene ninguna fila en la planilla
  (columna PLANILLA vacía o con otro texto), ese grupo no tiene Y: X pasa a ser los
  alumnos activos de la base de ese grupo (por sus clases de hoy y, si no tiene, por su planilla).
"""
import json

from sqlalchemy import or_

from app import config_club, planilla
from app.alumnos_alta import _norm_nombre
from app.cuotas import FRANJA_POR_AMBITO
from app.extensions import db
from app.models import Alumno
from app.models_academia import Clase, Inscripcion, clase_vigente_en

# nombre de cada ámbito: el mismo que usan Clases y Estadística de horas
NOMBRE_AMBITO = {"adultos": "Adultos mañana", "adultos_tarde": "Adultos tarde", "sabados": "Sábados",
                 "kids": "Kids", "kids_pro": "Kids Pro"}


def clave(nombre) -> str:
    """Nombre para cruzar planilla y base: 'Paula  Arangüez' y 'paula aranguez' dan lo mismo."""
    return _norm_nombre(nombre)


def filas_planilla(filas) -> list[dict]:
    """Filas con NOMBRE de "listado alumnos" (lista de celdas, la primera es el encabezado)."""
    if not filas:
        return []
    enc = [str(h).strip().upper() for h in filas[0]]

    def val(fila, col):
        i = enc.index(col) if col in enc else None
        return str(fila[i]).strip() if i is not None and i < len(fila) else ""

    salida = []
    for n, fila in enumerate(filas[1:], start=2):
        nombre = val(fila, "NOMBRE")
        if nombre:
            salida.append({"fila": n, "numero": val(fila, "N°"), "nombre": nombre, "estado": val(fila, "ESTADO"),
                           "al_dia": val(fila, "AL DIA"), "planilla": val(fila, "PLANILLA")})
    return salida


def es_activo_planilla(fila) -> bool:
    return planilla._norm(fila["estado"]) in ("", "activo")


def ambito_de_texto(texto):
    """'adultos tarde', 'Kids Pro', 'sábados' -> ámbito de clase, o None si no se reconoce."""
    t = planilla._norm(texto)
    if not t:
        return None
    for ambito, nombre in NOMBRE_AMBITO.items():
        if t in (ambito, ambito.replace("_", " "), planilla._norm(nombre)):
            return ambito
    return None


def franja_de_texto(texto):
    return FRANJA_POR_AMBITO.get(ambito_de_texto(texto))


def _nombres_grupos() -> dict:
    """{franja: nombre} en el orden de los ámbitos. config_academia 'nombres_grupos' pisa el que viene."""
    nombres = {}
    for ambito, franja in FRANJA_POR_AMBITO.items():
        nombres.setdefault(franja, NOMBRE_AMBITO.get(ambito, ambito))
    try:
        propios = json.loads(config_club.valor("nombres_grupos") or "{}")
    except ValueError:
        propios = {}
    if isinstance(propios, dict):
        nombres.update({f: str(n) for f, n in propios.items() if f in nombres and str(n).strip()})
    return nombres


def _base_activa(hoy):
    """[(alumno_id, clave del nombre, {franjas})] de los alumnos activos de la base."""
    alumnos = db.session.query(Alumno.id, Alumno.nombre, Alumno.planilla).filter(
        or_(Alumno.estado.is_(None), Alumno.estado != "baja")).all()
    por_clases = {}
    filas = (db.session.query(Inscripcion.alumno_id, Clase.ambito)
             .join(Clase, Clase.id == Inscripcion.clase_id)
             .filter(Clase.activa.is_(True), clase_vigente_en(hoy), Inscripcion.desde <= hoy,
                     or_(Inscripcion.hasta.is_(None), Inscripcion.hasta > hoy)))
    for aid, ambito in filas:
        if ambito in FRANJA_POR_AMBITO:
            por_clases.setdefault(aid, set()).add(FRANJA_POR_AMBITO[ambito])
    salida = []
    for aid, nombre, plan in alumnos:
        franjas = por_clases.get(aid) or ({franja_de_texto(plan)} - {None})
        salida.append((aid, clave(nombre), franjas))
    return salida


def resumen(filas, error, hoy) -> dict:
    """filas: lo que devolvió la planilla (None si no se pudo leer). error: texto del error o None.
    Devuelve {grupos: [{id, nombre, cargados, planilla}], total: {...}, error, sin_grupo}.
    planilla = None cuando no hay Y para mostrar (no se inventa)."""
    base = _base_activa(hoy)
    claves_base = {c for _, c, _ in base}
    nombres = _nombres_grupos()

    activas = [f for f in filas_planilla(filas)] if filas is not None else None
    activas = [f for f in activas if es_activo_planilla(f)] if activas is not None else None

    por_grupo = {f: {"cargados": 0, "planilla": 0} for f in nombres}
    sin_grupo = 0
    if activas is not None:
        for f in activas:
            franja = franja_de_texto(f["planilla"])
            if franja is None:
                sin_grupo += 1
                continue
            por_grupo[franja]["planilla"] += 1
            por_grupo[franja]["cargados"] += clave(f["nombre"]) in claves_base

    # grupos sin Y: se cuentan solo los de la base (no se inventa la planilla)
    base_por_grupo = {f: sum(1 for _, _, fs in base if f in fs) for f in nombres}
    grupos = []
    for franja, nombre in nombres.items():
        g = por_grupo[franja]
        if activas is not None and g["planilla"]:
            grupos.append({"id": franja, "nombre": nombre, "cargados": g["cargados"], "planilla": g["planilla"]})
        elif base_por_grupo[franja]:
            grupos.append({"id": franja, "nombre": nombre, "cargados": base_por_grupo[franja], "planilla": None})

    if activas is not None:
        total = {"cargados": sum(clave(f["nombre"]) in claves_base for f in activas), "planilla": len(activas)}
    else:
        total = {"cargados": len(base), "planilla": None}
    return {"grupos": grupos, "total": total, "error": error, "sin_grupo": sin_grupo}
