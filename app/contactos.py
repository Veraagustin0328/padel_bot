"""Quién es quién por teléfono.
Un número puede ser de varios alumnos (papás con más de un hijo), así que siempre se devuelve lista.
Cuando es de varios, se recuerda de cuál se está hablando ("alumno activo") por un rato.
"""
from datetime import datetime, timedelta

from app import planilla
from app.extensions import db
from app.models import Alumno, ContactoAlumno, EstadoChat


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


# ---------- alumno activo de la charla ----------

def alumno_activo(telefono, alumnos: list[Alumno], horas: int) -> Alumno | None:
    """El que quedó elegido en la charla, si no venció y sigue siendo de este número."""
    estado = EstadoChat.query.filter_by(telefono=telefono).first()
    if not estado or not estado.alumno_activo_id or not estado.alumno_activo_en:
        return None
    if estado.alumno_activo_en < datetime.utcnow() - timedelta(hours=horas):
        return None
    return next((a for a in alumnos if a.id == estado.alumno_activo_id), None)


def fijar_alumno_activo(telefono, alumno_id: int) -> None:
    estado = EstadoChat.query.filter_by(telefono=telefono).first()
    if not estado:
        estado = EstadoChat(telefono=telefono)
        db.session.add(estado)
    estado.alumno_activo_id = alumno_id
    estado.alumno_activo_en = datetime.utcnow()
    db.session.commit()
