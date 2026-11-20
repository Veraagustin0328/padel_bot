"""
Panel del alumno / padre: /api/yo/... Solo jugador, tutor y jugador_tutor.

Regla única de acceso: un usuario ve solo los alumnos vinculados a él en alumno_usuario,
y el vínculo se cruza con el rol (si a un tutor le cambian el rol a jugador, deja de ver
a los hijos aunque quede la fila vieja). Todo lo que reciba un alumno_id pasa por
@con_alumno, que da 404 (no 403) si no es suyo: así no se puede averiguar qué ids existen.

Las respuestas se arman a mano con lista blanca de campos: nada de teléfonos, montos
del club ni datos de otros alumnos o tutores.

Quién entra:
- jugador / tutor / jugador_tutor: lo suyo.
- encargado y profe: 403 (tienen su propio panel).
- dueño: pasa, como en todo requiere_login, pero no tiene vínculos de alumno por su rol,
  así que ve lista vacía y cualquier alumno le da 404.
"""
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, g

from app import cambios_dias
from app import niveles
from app import recuperaciones as rec
from app.extensions import db
from app.models import Alumno
from app.models_academia import (AlumnoUsuario, AlumnoPerfil, Ausencia, AusenciaLapso, Clase, Inscripcion,
                                 RecuperacionClase)
from app.models_cuotas import CuotaMes, PagoCuota
from app.models_plataforma import Profesor
from app.routes.auth import requiere_login

yo_bp = Blueprint("yo", __name__)

ROLES_ALUMNO = ("jugador", "tutor", "jugador_tutor")
RELACIONES_TUTOR = ("padre", "madre", "tutor")
# qué relaciones habilita cada rol
VE_PROPIO = ("jugador", "jugador_tutor")
VE_HIJOS = ("tutor", "jugador_tutor")

NO_ENCONTRADO = "No encontré ese alumno"


def alumnos_mios(usuario):
    """{alumno_id: "propio" | "hijo"} de este usuario, según sus filas y su rol."""
    mios = {}
    filas = db.session.query(AlumnoUsuario.alumno_id, AlumnoUsuario.relacion).filter(
        AlumnoUsuario.usuario_id == usuario.id).all()
    for alumno_id, relacion in filas:
        if relacion == "jugador" and usuario.rol in VE_PROPIO:
            mios[alumno_id] = "propio"
        elif relacion in RELACIONES_TUTOR and usuario.rol in VE_HIJOS:
            mios.setdefault(alumno_id, "hijo")  # si fuera las dos cosas, gana propio
    return mios


def alumno_mio(alumno_id):
    """El Alumno si está vinculado al usuario logueado; si no, None (la ruta da 404)."""
    if alumno_id not in alumnos_mios(g.usuario):
        return None
    return db.session.get(Alumno, alumno_id)


def con_alumno(f):
    """Para rutas /api/yo/alumnos/<alumno_id>/...: chequea pertenencia y pasa el Alumno.
    Va DEBAJO de @requiere_login (necesita g.usuario)."""
    @wraps(f)
    def envoltura(alumno_id, *args, **kwargs):
        alumno = alumno_mio(alumno_id)
        if not alumno:
            return jsonify({"error": NO_ENCONTRADO}), 404
        return f(alumno, *args, **kwargs)
    envoltura.chequea_alumno = True  # lo mira la prueba: toda ruta con alumno_id lo tiene que tener
    return envoltura


def _texto(clave):
    valor = rec.regla(clave)
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


# ---------- rutas ----------

@yo_bp.get("/api/yo/alumnos")
@requiere_login(*ROLES_ALUMNO)
def mis_alumnos():
    mios = alumnos_mios(g.usuario)
    if not mios:
        return jsonify([])
    filas = (db.session.query(Alumno.id, Alumno.nombre, AlumnoPerfil.es_menor)
             .outerjoin(AlumnoPerfil, AlumnoPerfil.alumno_id == Alumno.id)
             .filter(Alumno.id.in_(list(mios)))
             .all())
    salida = [{"id": id_, "nombre": nombre, "es_menor": bool(es_menor), "vinculo": mios[id_]}
              for id_, nombre, es_menor in filas]
    salida.sort(key=lambda a: (a["vinculo"] != "propio", a["nombre"].lower()))  # propio primero
    return jsonify(salida)


@yo_bp.get("/api/yo/datos-pago")
@requiere_login(*ROLES_ALUMNO)
def datos_pago():
    # de config_academia; si falta, None y el panel dice que se lo pida al encargado
    return jsonify({"nombre_academia": _texto("nombre_academia"), "datos_pago": _texto("datos_pago")})


# ---------- Inicio: resumen de un alumno ----------

DIAS_PROXIMA = 15  # hasta dónde se busca la próxima clase (cubre dos semanas y un feriado largo)


def _pila(nombre):
    return (nombre or "").split()[0] if nombre else ""


def _clases_en(alumno_id, desde, hasta):
    """Todas las clases del alumno entre desde y hasta (inclusive), en orden: sus fijas (con la falta
    avisada o el viaje marcados) y las recuperaciones confirmadas. Mismas reglas que Mis clases:
    inscripción vigente ese día, clase activa y de su temporada. Nada de compañeros ni teléfonos.
    Cada una: {clase, fecha, inicio, estado: va / falta / viaje, recuperacion}."""
    # 4 consultas para todo el rango, en vez de una por día
    inscripciones = (db.session.query(Inscripcion, Clase).join(Clase, Clase.id == Inscripcion.clase_id)
                     .filter(Inscripcion.alumno_id == alumno_id, Clase.activa.is_(True),
                             Inscripcion.desde <= hasta,
                             db.or_(Inscripcion.hasta.is_(None), Inscripcion.hasta > desde))
                     .all())
    faltas = {(a.clase_id, a.fecha) for a in Ausencia.query.filter(
        Ausencia.alumno_id == alumno_id, Ausencia.fecha >= desde, Ausencia.fecha <= hasta)}
    viajes = AusenciaLapso.query.filter(
        AusenciaLapso.alumno_id == alumno_id, AusenciaLapso.estado == "confirmado",
        AusenciaLapso.desde <= hasta, AusenciaLapso.hasta >= desde).all()
    recus = RecuperacionClase.query.filter(
        RecuperacionClase.alumno_id == alumno_id, RecuperacionClase.estado == "confirmada",
        RecuperacionClase.fecha >= desde, RecuperacionClase.fecha <= hasta).all()

    def de_viaje(clase, fecha):
        return any(v.desde <= fecha <= v.hasta and (v.clase_id is None or v.clase_id == clase.id) for v in viajes)

    salida = []
    fecha = desde
    while fecha <= hasta:
        vistas = set()  # por si quedó una inscripción vieja y una nueva de la misma clase
        for ins, c in inscripciones:
            if (c.dia_semana != fecha.weekday() or c.id in vistas or not c.vigente_en(fecha)
                    or not (ins.desde <= fecha and (ins.hasta is None or ins.hasta > fecha))):
                continue
            vistas.add(c.id)
            estado = "falta" if (c.id, fecha) in faltas else "viaje" if de_viaje(c, fecha) else "va"
            salida.append({"clase": c, "fecha": fecha, "estado": estado, "recuperacion": False})
        fecha += timedelta(days=1)
    fijas = {(i["clase"].id, i["fecha"]): i for i in salida}
    for x in recus:
        c = db.session.get(Clase, x.clase_id)
        if not c or not c.activa:
            continue
        misma = fijas.get((c.id, x.fecha))
        if misma:
            # recuperación en su misma clase fija ese día: se muestra una sola vez. Si la fija estaba
            # como falta o viaje, con la recuperación va igual (y queda marcada como recuperación)
            if misma["estado"] != "va":
                misma.update(estado="va", recuperacion=True)
            continue
        fijas[(c.id, x.fecha)] = {"clase": c, "fecha": x.fecha, "estado": "va", "recuperacion": True}
        salida.append(fijas[(c.id, x.fecha)])
    for item in salida:
        item["inicio"] = rec.inicio_clase(item["clase"], item["fecha"])
    salida.sort(key=lambda i: i["inicio"])
    return salida


# clase sin color (sin rama, mixta o el club no la cargó): gris neutro
GRIS_SIN_COLOR = "#9ca3af"


def _color_de(clase, tabla):
    """Solo el color de la clase, nunca el nivel (pedido de Gabi: el alumno ve el color y listo).
    Sale de config_academia 'colores_rama', igual que en el panel de gestión."""
    col = niveles.color_clase(clase.nivel, clase.rama, clase.columna_color, tabla)["columna"]
    fila = tabla["columnas"][col - 1] if col else None
    if not fila or not fila["color"]:
        return {"nombre": None, "hex": GRIS_SIN_COLOR}
    nombre = fila["nombre"] if not fila["nombre"].startswith("#") else None  # si la columna es un hex suelto
    return {"nombre": nombre, "hex": fila["color"]}


def _json_clase(item, profes, tabla):
    clase, fecha = item["clase"], item["fecha"]
    fin = datetime.combine(fecha, clase.hora_inicio) + timedelta(minutes=clase.duracion_min or 60)
    profe = profes.get(clase.profesor_id)
    return {
        "fecha": fecha.isoformat(),
        "dia": cambios_dias.NOMBRE_DIA[fecha.weekday()],
        "hora": clase.hora_inicio.strftime("%H:%M"),
        "hora_fin": fin.strftime("%H:%M"),
        "color": _color_de(clase, tabla),  # sin nivel a propósito: no se filtra ni mirando la API
        "profe": _pila(profe) if profe else None,
        "recuperacion": item["recuperacion"],
    }


def _agenda(alumno_id):
    """(próxima clase, semana). La semana va de lunes a domingo (hora del club) con el estado de
    cada clase: paso / proxima / viene / falta / viaje. La próxima puede caer la semana que viene:
    falta avisada y viaje no cuentan como próxima."""
    hoy, ahora = rec.hoy(), rec.ahora()
    lunes = hoy - timedelta(days=hoy.weekday())
    domingo = lunes + timedelta(days=6)
    items = _clases_en(alumno_id, lunes, max(domingo, hoy + timedelta(days=DIAS_PROXIMA)))
    proxima = next((i for i in items if i["estado"] == "va" and i["inicio"] > ahora
                    and i["fecha"] <= hoy + timedelta(days=DIAS_PROXIMA)), None)
    ids_profe = {i["clase"].profesor_id for i in items if i["clase"].profesor_id}
    profes = dict(db.session.query(Profesor.id, Profesor.nombre).filter(Profesor.id.in_(ids_profe))) if ids_profe else {}
    tabla = niveles.tabla()

    semana = []
    for i in items:
        if i["fecha"] > domingo:
            break
        if i is proxima:
            estado = "proxima"
        elif i["estado"] != "va":
            estado = i["estado"]  # falta / viaje: tachadas, pasadas o no
        else:
            estado = "paso" if i["inicio"] <= ahora else "viene"
        semana.append({**_json_clase(i, profes, tabla), "estado": estado})
    return (_json_clase(proxima, profes, tabla) if proxima else None), semana


def _cuota_del_mes(alumno_id):
    """Pagó / Debe con montos (decisión P1): lo mismo que ya le dice el agente. Sin detalle ni notas."""
    mes = rec.hoy().replace(day=1)
    cuota = db.session.query(db.func.coalesce(db.func.sum(CuotaMes.monto), 0)).filter(
        CuotaMes.alumno_id == alumno_id, CuotaMes.mes == mes).scalar()
    pagado = db.session.query(db.func.coalesce(db.func.sum(PagoCuota.monto), 0)).filter(
        PagoCuota.alumno_id == alumno_id, PagoCuota.mes == mes).scalar()
    cuota, pagado = int(cuota), int(pagado)
    if not cuota:
        estado = "sin_cargar"  # todavía no se generó: el panel no inventa monto
    else:
        estado = "pago" if pagado >= cuota else "debe"  # el parcial es deuda (se paga el total)
    return {"mes": mes.strftime("%Y-%m"), "estado": estado, "cuota": cuota, "pagado": pagado,
            "debe": max(cuota - pagado, 0)}


@yo_bp.get("/api/yo/alumnos/<int:alumno_id>/resumen")
@requiere_login(*ROLES_ALUMNO)
@con_alumno
def resumen(alumno):
    perfil = db.session.get(AlumnoPerfil, alumno.id)
    proxima, semana = _agenda(alumno.id)
    tope = int(rec.regla("max_recuperaciones_mes") or 0)
    return jsonify({
        "alumno": {"id": alumno.id, "nombre": alumno.nombre, "nombre_pila": _pila(alumno.nombre),
                   "es_menor": bool(perfil and perfil.es_menor),
                   "vinculo": alumnos_mios(g.usuario)[alumno.id]},
        "proxima_clase": proxima,
        "semana": semana,
        "cuota": _cuota_del_mes(alumno.id),
        # tope None = el club no tiene tope
        "recuperaciones": {"disponibles": rec.recuperaciones_disponibles(alumno.id), "tope": tope or None},
    })


@yo_bp.get("/api/yo/politicas")
@requiere_login(*ROLES_ALUMNO)
def politicas():
    # de config_academia; si falta la clave, los textos por defecto (los del PDF de planes)
    return jsonify({"nombre_academia": _texto("nombre_academia"), "politicas": rec.politicas()})
