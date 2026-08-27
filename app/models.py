from datetime import datetime
from app.extensions import db


class Alumno(db.Model):
    __tablename__ = "alumnos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(20), unique=True, nullable=False, index=True)
    categoria = db.Column(db.String(20), nullable=False)
    planilla = db.Column(db.String(30), nullable=False)  # adultos, kids, kids_pro, etc.
    estado = db.Column(db.String(20), default="activo")  # activo / baja
    fecha_inscripcion = db.Column(db.DateTime, default=datetime.utcnow)


class Grupo(db.Model):
    __tablename__ = "grupos"

    id = db.Column(db.Integer, primary_key=True)
    profesor = db.Column(db.String(80), nullable=False)
    dia = db.Column(db.String(15), nullable=False)
    horario = db.Column(db.String(10), nullable=False)
    categoria = db.Column(db.String(20), nullable=True)
    cupo_max = db.Column(db.Integer, default=4)
    
class ClaseSuelta(db.Model):
    __tablename__ = "clases_sueltas"

    id = db.Column(db.Integer, primary_key=True)
    telefono = db.Column(db.String(20), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # particular / grupal
    dia = db.Column(db.String(15), nullable=False)
    horario = db.Column(db.String(10), nullable=False)
    profesor = db.Column(db.String(80), nullable=True)  # opcional, si lo pidieron
    estado = db.Column(db.String(20), default="pendiente")