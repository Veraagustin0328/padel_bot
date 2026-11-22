"""Editar, dar de baja, reactivar y borrar alumnos (dueño y encargado, desde Fichas).

Usa la misma validación de teléfonos y la misma detección de parecidos que el alta (alumnos_alta).
Todo queda en Auditoria con quién lo hizo. El commit lo hace quien llama.
- Baja: estado "baja" y cierra sus inscripciones (hasta = hoy). No borra cuotas, asistencias ni faltas.
- Reactivar: vuelve a "activo" sin reinscribirlo (las clases las vuelve a cargar el encargado).
- Borrar: solo si no tiene nada de historia (ver motivos_para_no_borrar).
"""
import json
from datetime import datetime

from sqlalchemy import func, literal, or_, select, union_all

from app import niveles
from app import recuperaciones as rec
from app.alumnos_alta import (PLANILLAS_ALTA, ErrorAlta, _leer_contactos, _norm_nombre, es_menor,
                              parecidos)
from app.contactos import tel10
from app.extensions import db
from app.models import Alumno, CambioPendiente, ContactoAlumno, EstadoChat
from app.models_academia import AlumnoPerfil, Auditoria, Clase, Inscripcion, RecuperacionClase
from app.models_cuotas import CuotaMes, PagoCuota

MOTIVOS_BAJA = ("horario", "lesion", "precio", "mudanza", "otro")  # entra en Alumno.motivo_baja (20 letras)
# lo que se va con el alumno al borrarlo: no es historia, son datos de la ficha
SE_BORRAN_CON_EL = {"contactos_alumno", "alumno_perfil"}
SE_DESENGANCHAN = {("estados_chat", "alumno_activo_id")}  # charla del agente: queda sin alumno elegido
# cómo se dice cada cosa que impide borrar: (una, varias)
NOMBRE_TABLA = {
    "inscripciones": ("clase (anotado alguna vez)", "clases (anotado alguna vez)"),
    "cuotas_mes": ("cuota", "cuotas"),
    "pagos_cuota": ("pago", "pagos"),
    "asistencias": ("asistencia", "asistencias"),
    "ausencias": ("falta", "faltas"),
    "ausencias_lapso": ("viaje o reemplazo", "viajes o reemplazos"),
    "recuperaciones_clase": ("recuperación", "recuperaciones"),
    "notas": ("nota", "notas"),
    "cambios_pendientes": ("cambio de días", "cambios de días"),
    "promo_alumno": ("promo", "promos"),
    "alumno_usuario": ("usuario del panel vinculado", "usuarios del panel vinculados"),
}


def _auditar(alumno_id, accion, antes, despues, usuario_id):
    db.session.add(Auditoria(entidad="alumno", entidad_id=alumno_id, accion=accion, usuario_id=usuario_id,
                             antes=json.dumps(antes, ensure_ascii=False, default=str) if antes is not None else None,
                             despues=json.dumps(despues, ensure_ascii=False, default=str) if despues is not None else None))


def _ficha(alumno) -> dict:
    """Lo editable del alumno, para comparar antes y después."""
    cs = ContactoAlumno.query.filter_by(alumno_id=alumno.id).order_by(ContactoAlumno.id).all()
    return {"nombre": alumno.nombre, "planilla": alumno.planilla, "nivel": alumno.categoria or "",
            "contactos": [{"telefono": c.telefono, "parentesco": c.parentesco, "nombre": c.nombre or ""} for c in cs]}


# ---------------------------------------------------------------- editar
def parecidos_edicion(alumno, nombre, telefonos) -> list[dict]:
    """Como en el alta, pero solo por lo nuevo: un teléfono que ya tenía (ej. el de los papás que
    comparte con el hermano) o el mismo nombre no vuelven a avisar en cada edición."""
    ya_tenia = {c.tel10 for c in ContactoAlumno.query.filter_by(alumno_id=alumno.id)} | {tel10(alumno.telefono)}
    nuevos = [t for t in telefonos if t and tel10(t) not in ya_tenia]
    cambia_nombre = _norm_nombre(nombre) != _norm_nombre(alumno.nombre)
    if not cambia_nombre and not nuevos:
        return []
    return parecidos(nombre if cambia_nombre else "", nuevos, excluir_id=alumno.id)


def editar_alumno(alumno, nombre, planilla_txt, nivel, telefono, contactos, usuario_id,
                  confirmar_parecidos=False) -> tuple[dict, list]:
    """Cambia nombre, planilla, nivel y contactos. Devuelve (cambios {campo: [antes, después]}, parecidos).
    Parecidos solo por lo nuevo: un teléfono que ya tenía o el mismo nombre no vuelven a avisar.
    Si hay y no se confirmó, ErrorAlta con .parecidos. No hace commit."""
    nombre = " ".join(str(nombre or "").split())
    if len(nombre) < 3 or len(nombre) > 120 or not any(ch.isalpha() for ch in nombre):
        raise ErrorAlta("Poné nombre y apellido (hasta 120 letras)")
    planilla_txt = str(planilla_txt or "").strip().lower()
    # las de siempre, o la que ya tenía (ej. kids_pro, que se arma desde las clases)
    if planilla_txt not in PLANILLAS_ALTA and planilla_txt != (alumno.planilla or ""):
        raise ErrorAlta("Elegí la planilla: " + " o ".join(PLANILLAS_ALTA))
    nivel_ok = niveles.nivel_canonico(nivel) if nivel else None
    if nivel and (not nivel_ok or nivel_ok not in niveles.niveles()):
        # un nivel viejo que ya tenía se puede dejar como está
        if str(nivel) != (alumno.categoria or ""):
            raise ErrorAlta("Ese nivel no existe")
        nivel_ok = alumno.categoria
    if not nivel_ok and not es_menor(planilla_txt):
        raise ErrorAlta("Elegí el nivel (categoría)")
    tels = _leer_contactos(planilla_txt, telefono, contactos, tutores_en_adultos=True)

    antes = _ficha(alumno)
    dudosos = parecidos_edicion(alumno, nombre, [t for t, _, _ in tels])
    if dudosos and not confirmar_parecidos:
        e = ErrorAlta("Hay alumnos parecidos: fijate que no sea otro que ya está cargado")
        e.parecidos = dudosos
        raise e

    alumno.nombre = nombre
    alumno.planilla = planilla_txt
    perfil = db.session.get(AlumnoPerfil, alumno.id)
    if perfil is None:
        perfil = AlumnoPerfil(alumno_id=alumno.id, es_menor=False)
        db.session.add(perfil)
    perfil.es_menor = es_menor(planilla_txt)
    if (nivel_ok or "") != (alumno.categoria or ""):
        alumno.categoria = nivel_ok or ""
        if nivel_ok:
            # lo pone gestión: cuenta como confirmado (igual que clasificar desde la ficha)
            perfil.nivel_confirmado = nivel_ok
            perfil.nivel_confirmado_por = usuario_id
            perfil.nivel_confirmado_en = datetime.utcnow()

    # contactos: piso todos (son 3 como mucho), igual que el modal de Fichas
    ContactoAlumno.query.filter_by(alumno_id=alumno.id).delete()
    db.session.flush()
    for t, parentesco, nom in tels:
        db.session.add(ContactoAlumno(alumno_id=alumno.id, telefono=t, tel10=tel10(t), parentesco=parentesco, nombre=nom))
    alumno.telefono = tels[0][0]
    db.session.flush()

    despues = _ficha(alumno)
    cambios = {k: [antes[k], despues[k]] for k in antes if antes[k] != despues[k]}
    if cambios:
        _auditar(alumno.id, "editar", {k: v[0] for k, v in cambios.items()},
                 {**{k: v[1] for k, v in cambios.items()}, "parecidos_confirmados": [d["id"] for d in dudosos]},
                 usuario_id)
    return cambios, dudosos


# ---------------------------------------------------------------- baja y reactivar
def _abiertas(alumno_id, hoy):
    """Inscripciones que siguen o que empiezan más adelante ('hasta' es el primer día que ya no va)."""
    filas = (Inscripcion.query.filter(Inscripcion.alumno_id == alumno_id,
                                      or_(Inscripcion.hasta.is_(None), Inscripcion.hasta > hoy))
             .order_by(Inscripcion.id).all())
    # las vacías (desde = hasta: una que iba a empezar y se cerró en una baja) no cuentan
    return [i for i in filas if not (i.hasta and i.desde and i.hasta <= i.desde)]


def _recuperaciones_futuras(alumno_id, hoy):
    return RecuperacionClase.query.filter(RecuperacionClase.alumno_id == alumno_id, RecuperacionClase.fecha >= hoy,
                                          RecuperacionClase.estado.in_(rec.ACTIVAS)).all()


def _cambios_pendientes(alumno_id):
    return CambioPendiente.query.filter_by(alumno_id=alumno_id, estado="pendiente").all()


def _texto_clase(c) -> str:
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"{dias[c.dia_semana]} {c.hora_inicio.strftime('%H:%M')}" + (f" ({c.nivel})" if c.nivel else "")


def resumen_baja(alumno) -> dict:
    """Lo que va a pasar si se lo da de baja, para el aviso de confirmación."""
    hoy = rec.hoy()
    abiertas = _abiertas(alumno.id, hoy)
    clases = {c.id: c for c in Clase.query.filter(Clase.id.in_([i.clase_id for i in abiertas]))} if abiertas else {}
    return {
        "clases": [_texto_clase(clases[i.clase_id]) for i in abiertas if i.clase_id in clases],
        "recuperaciones": len(_recuperaciones_futuras(alumno.id, hoy)),
        "cambios_pendientes": len(_cambios_pendientes(alumno.id)),
    }


def dar_de_baja(alumno, usuario_id, motivo=None) -> dict:
    """Estado baja, cierra sus clases desde hoy y cancela lo que tenía por delante (recuperaciones
    y cambios de días pendientes). El historial (cuotas, asistencias, faltas) queda como estaba."""
    if (alumno.estado or "activo") == "baja":
        raise ErrorAlta("Ya está de baja")
    motivo = str(motivo or "").strip().lower() or None
    if motivo is not None and motivo not in MOTIVOS_BAJA:
        raise ErrorAlta("Ese motivo no existe")
    hoy = rec.hoy()
    resumen = resumen_baja(alumno)
    cerradas = []
    for i in _abiertas(alumno.id, hoy):
        # si arrancaba más adelante queda vacía (desde = hasta): nunca llegó a ir
        i.hasta = max(hoy, i.desde) if i.desde else hoy
        cerradas.append(i.id)
    for r in _recuperaciones_futuras(alumno.id, hoy):
        r.estado = "cancelada"
        r.resuelta_por = usuario_id
        r.resuelta_en = datetime.utcnow()
    for c in _cambios_pendientes(alumno.id):
        c.estado = "cancelado"
        c.motivo_rechazo = "baja del alumno"
        c.resuelto_por = usuario_id
        c.resuelto_en = datetime.utcnow()
    antes = {"estado": alumno.estado or "activo", "motivo_baja": alumno.motivo_baja}
    alumno.estado = "baja"
    alumno.motivo_baja = motivo
    _auditar(alumno.id, "baja", antes, {"estado": "baja", "motivo_baja": motivo, "desde": hoy,
                                        "inscripciones_cerradas": cerradas, **resumen}, usuario_id)
    db.session.flush()
    return {**resumen, "cerradas": len(cerradas)}


def reactivar(alumno, usuario_id) -> None:
    """Vuelve a activo. No lo reinscribe: sus clases las carga el encargado a mano."""
    if (alumno.estado or "activo") != "baja":
        raise ErrorAlta("No está de baja")
    antes = {"estado": alumno.estado, "motivo_baja": alumno.motivo_baja}
    alumno.estado = "activo"
    alumno.motivo_baja = None
    _auditar(alumno.id, "reactivar", antes, {"estado": "activo"}, usuario_id)
    db.session.flush()


# ---------------------------------------------------------------- borrar
def _referencias():
    """(tabla, columna) de todo lo que apunta a alumnos.id, leído de los modelos.
    Así una tabla nueva con historia del alumno frena el borrado sin tener que acordarse de sumarla acá."""
    salida = []
    for tabla in db.Model.metadata.sorted_tables:
        for fk in tabla.foreign_keys:
            if fk.column.table.name == "alumnos" and fk.column.name == "id":
                salida.append((tabla, fk.parent))
    return salida


def _inscripcion_sin_pagar(alumno_id):
    """La inscripción que carga el alta, si no tiene pagos: es del alta, no historia. Se va con el alumno.
    Cualquier otro cargo (cuota, ajuste) o un pago sí frenan el borrado."""
    if PagoCuota.query.filter_by(alumno_id=alumno_id).first():
        return []
    return CuotaMes.query.filter_by(alumno_id=alumno_id, concepto="inscripcion").all()


def motivos_para_no_borrar(alumno) -> list[str]:
    """Por qué no se puede borrar ("tiene 3 cuotas"). Vacía = se puede.
    Todos los conteos van en una sola consulta (UNION ALL): de a uno eran ~20 idas a la base."""
    perdonadas = {c.id for c in _inscripcion_sin_pagar(alumno.id)}
    partes = []
    for tabla, col in _referencias():
        if tabla.name in SE_BORRAN_CON_EL or (tabla.name, col.name) in SE_DESENGANCHAN:
            continue
        q = select(literal(tabla.name).label("tabla"), func.count().label("n")).select_from(tabla).where(col == alumno.id)
        if tabla.name == "cuotas_mes" and perdonadas:
            q = q.where(tabla.c.id.notin_(perdonadas))
        partes.append(q)
    if not partes:
        return []
    motivos, vistas = [], set()
    for nombre, n in db.session.execute(union_all(*partes)).all():
        if n and nombre not in vistas:  # una tabla con dos columnas al alumno (viajes) cuenta una vez
            vistas.add(nombre)
            una, varias = NOMBRE_TABLA.get(nombre, (nombre.replace("_", " "),) * 2)
            motivos.append(f"{n} {una if n == 1 else varias}")
    return motivos


def borrar_alumno(alumno, usuario_id, confirmacion) -> None:
    """Borra al alumno sin historia. confirmacion: el nombre tal cual o True ("entiendo que no se puede deshacer")."""
    if not (confirmacion is True or (isinstance(confirmacion, str)
                                     and _norm_nombre(confirmacion) == _norm_nombre(alumno.nombre))):
        raise ErrorAlta("Para borrarlo escribí su nombre o tildá que entendés que no se puede deshacer")
    motivos = motivos_para_no_borrar(alumno)
    if motivos:
        raise ErrorAlta("No se puede borrar: tiene " + ", ".join(motivos) + ". Dalo de baja.")
    ficha = _ficha(alumno)
    for c in _inscripcion_sin_pagar(alumno.id):
        db.session.delete(c)
    EstadoChat.query.filter_by(alumno_activo_id=alumno.id).update({"alumno_activo_id": None})
    ContactoAlumno.query.filter_by(alumno_id=alumno.id).delete()
    AlumnoPerfil.query.filter_by(alumno_id=alumno.id).delete()
    _auditar(alumno.id, "borrar", {**ficha, "estado": alumno.estado, "telefono": alumno.telefono}, None, usuario_id)
    db.session.delete(alumno)
    db.session.flush()
