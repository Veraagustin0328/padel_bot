"""Quién es quién por teléfono.
Un número puede ser de varios alumnos (papás con más de un hijo), así que siempre se devuelve lista.
Cuando es de varios, se recuerda de cuál se está hablando ("alumno activo") por un rato.
"""
import json
from datetime import datetime, timedelta

from app import planilla
from app.extensions import db
from app.models import Alumno, ContactoAlumno, EstadoChat
from app.models_academia import ConfigAcademia

PAUSA_HORAS_DEFAULT = 12  # si el club no puso pausa_horas en config_academia


def tel10(telefono) -> str:
    """Los últimos 10 dígitos, igual que planilla._tel."""
    return planilla._tel(telefono)


def alumnos_de_telefono(telefono) -> list[Alumno]:
    """Todos los alumnos que tienen este número como contacto, ordenados por nombre.
    Además miro Alumno.telefono por si hay alguno cargado sin contacto (de antes de la migración)."""
    t = tel10(telefono)
    if len(t) < 10:
        return []
    ids_contacto = db.session.query(ContactoAlumno.alumno_id).filter(ContactoAlumno.tel10 == t)
    return (
        Alumno.query.filter(db.or_(Alumno.id.in_(ids_contacto), Alumno.telefono.like(f"%{t}")))
        .order_by(Alumno.nombre, Alumno.id)
        .all()
    )


def crear_contacto(alumno: Alumno, telefono, parentesco="propio", nombre=None) -> ContactoAlumno | None:
    """Agrega el contacto si no estaba (el commit lo hace quien llama). None si el número no sirve."""
    t = tel10(telefono)
    if len(t) < 10:
        return None
    ya = ContactoAlumno.query.filter_by(alumno_id=alumno.id, tel10=t).first()
    if ya:
        return ya
    c = ContactoAlumno(alumno_id=alumno.id, telefono=str(telefono), tel10=t,
                       parentesco=parentesco, nombre=nombre or None)
    db.session.add(c)
    return c


# ---------- estado de la charla (pausa y alumno activo) ----------
# La clave es tel10: WhatsApp manda 549..., en la base suele estar sin 549, y así da lo mismo.

def estado_chat(telefono, crear: bool = False) -> EstadoChat | None:
    """La fila de EstadoChat de este número. Con crear=True la agrega si no está (el commit lo hace quien llama)."""
    t = tel10(telefono)
    if len(t) < 10:
        return None
    estado = EstadoChat.query.filter_by(telefono=t).first()
    if not estado and crear:
        estado = EstadoChat(telefono=t)
        db.session.add(estado)
    return estado


def telefonos_de_alumno(alumno: Alumno) -> list[tuple[str, str]]:
    """Todos los números del alumno como (tel10, etiqueta): sus contactos y Alumno.telefono
    por si es de antes de los contactos. Sin repetidos."""
    vistos = {}
    for c in ContactoAlumno.query.filter_by(alumno_id=alumno.id).order_by(ContactoAlumno.id).all():
        if len(c.tel10) == 10 and c.tel10 not in vistos:
            vistos[c.tel10] = c.nombre or c.parentesco
    t = tel10(alumno.telefono)
    if len(t) == 10 and t not in vistos:
        vistos[t] = "propio"
    return list(vistos.items())


def horas_pausa() -> int:
    """Cuántas horas dura la pausa del agente, de config_academia (pausa_horas). 0 = no vence sola."""
    cfg = db.session.get(ConfigAcademia, "pausa_horas")
    try:
        n = int(json.loads(cfg.valor)) if cfg else PAUSA_HORAS_DEFAULT
    except (TypeError, ValueError):
        n = PAUSA_HORAS_DEFAULT
    return max(n, 0)


def poner_modo(telefono, modo: str) -> None:
    """Pausa ("humano") o reanuda ("bot") este número. El commit lo hace quien llama."""
    estado = estado_chat(telefono, crear=True)
    if not estado:
        return
    estado.modo = modo
    estado.pausado_en = datetime.utcnow() if modo == "humano" else None


def esta_pausado(telefono) -> bool:
    """True si el encargado tomó la charla. Si la pausa venció, la levanto y vuelve el agente.
    Sin pausado_en (pausas de antes de la migración) no vence."""
    estado = estado_chat(telefono)
    if not estado or estado.modo != "humano":
        return False
    horas = horas_pausa()
    if horas and estado.pausado_en and estado.pausado_en < datetime.utcnow() - timedelta(hours=horas):
        estado.modo = "bot"
        estado.pausado_en = None
        db.session.commit()
        print(f"[pausa] venció la pausa de {estado.telefono} ({horas} hs), vuelve el agente", flush=True)
        return False
    return True


def alumno_activo(telefono, alumnos: list[Alumno], horas: int) -> Alumno | None:
    """El que quedó elegido en la charla, si no venció y sigue siendo de este número."""
    estado = estado_chat(telefono)
    if not estado or not estado.alumno_activo_id or not estado.alumno_activo_en:
        return None
    if estado.alumno_activo_en < datetime.utcnow() - timedelta(hours=horas):
        return None
    return next((a for a in alumnos if a.id == estado.alumno_activo_id), None)


def fijar_alumno_activo(telefono, alumno_id: int) -> None:
    estado = estado_chat(telefono, crear=True)
    if not estado:
        return
    estado.alumno_activo_id = alumno_id
    estado.alumno_activo_en = datetime.utcnow()
    db.session.commit()
