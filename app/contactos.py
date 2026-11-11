"""Quién es quién por teléfono.
Un número puede ser de varios alumnos (papás con más de un hijo), así que siempre se devuelve lista.
"""
from app import planilla
from app.extensions import db
from app.models import Alumno, ContactoAlumno


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
