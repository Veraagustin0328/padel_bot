"""
Tablas nuevas de la plataforma de Arena Pádel.

Van aparte de models.py para no tocar lo que ya anda con el agente.
Las tablas viejas (alumnos, grupos, etc.) quedan como están: acá solo
se agregan cosas nuevas y se enganchan por alumno_id.
"""
from datetime import date, datetime

from app.extensions import db


class Usuario(db.Model):
    """Gente que entra al panel: Gabi, encargados, profes."""
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="encargado")  # admin / encargado / profe
    profesor_id = db.Column(db.Integer, db.ForeignKey("profesores.id"), nullable=True)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


class Plan(db.Model):
    """Qué clases toma un alumno: cuántas grupales y cuántas particulares por semana."""
    __tablename__ = "planes"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)  # ej: "2 grupales", "1 grupal + 1 particular"
    grupales_por_semana = db.Column(db.Integer, nullable=False, default=0)
    particulares_por_semana = db.Column(db.Integer, nullable=False, default=0)
    descripcion = db.Column(db.String(255), nullable=True)
    activo = db.Column(db.Boolean, default=True)

    precios = db.relationship("PrecioPlan", backref="plan", order_by="PrecioPlan.vigente_desde.desc()")


class PrecioPlan(db.Model):
    """
    Historial de precios de cada plan. No se pisa nada: cada aumento es una fila nueva
    con la fecha desde la que rige. El precio vigente es el último con vigente_desde <= hoy.
    """
    __tablename__ = "precios_plan"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("planes.id"), nullable=False, index=True)
    monto = db.Column(db.Numeric(12, 2), nullable=False)
    vigente_desde = db.Column(db.Date, nullable=False, index=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


class AlumnoPlan(db.Model):
    """
    Qué plan tiene cada alumno y desde cuándo (guarda el historial si cambia).
    precio_especial sirve para becas, familiares o acuerdos: si está cargado, manda sobre el del plan.
    """
    __tablename__ = "alumno_plan"

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("planes.id"), nullable=False)
    desde = db.Column(db.Date, nullable=False)
    hasta = db.Column(db.Date, nullable=True)  # vacío = plan actual
    precio_especial = db.Column(db.Numeric(12, 2), nullable=True)
    nota = db.Column(db.String(255), nullable=True)


class Cuota(db.Model):
    """Lo que le corresponde pagar a un alumno en un mes. Se genera a principio de mes."""
    __tablename__ = "cuotas"
    __table_args__ = (db.UniqueConstraint("alumno_id", "anio", "mes", name="uq_cuota_alumno_mes"),)

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False, index=True)
    anio = db.Column(db.Integer, nullable=False)
    mes = db.Column(db.Integer, nullable=False)  # 1 a 12
    monto = db.Column(db.Numeric(12, 2), nullable=False)
    estado = db.Column(db.String(15), nullable=False, default="pendiente")  # pendiente / parcial / pagada / anulada
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    pagos = db.relationship("PagoAlumno", backref="cuota")


class Comprobante(db.Model):
    """Lo que avisa el alumno por WhatsApp (monto + foto o PDF). Gabi lo revisa y confirma."""
    __tablename__ = "comprobantes"

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=True, index=True)
    telefono = db.Column(db.String(20), nullable=False, index=True)
    monto = db.Column(db.Numeric(12, 2), nullable=True)
    anio = db.Column(db.Integer, nullable=True)
    mes = db.Column(db.Integer, nullable=True)
    estado = db.Column(db.String(15), nullable=False, default="pendiente")  # pendiente / confirmado / aplicado / anulado
    media_id = db.Column(db.String(120), nullable=True)  # id del archivo en WhatsApp
    media_tipo = db.Column(db.String(15), nullable=True)  # image / document
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    resuelto_en = db.Column(db.DateTime, nullable=True)
    resuelto_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)


class PagoAlumno(db.Model):
    """
    Pago ya aplicado a una cuota. Si alguien paga dos meses juntos, son dos filas.
    (La tabla vieja 'pagos' queda sin usar.)
    """
    __tablename__ = "pagos_alumno"

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False, index=True)
    cuota_id = db.Column(db.Integer, db.ForeignKey("cuotas.id"), nullable=True, index=True)
    comprobante_id = db.Column(db.Integer, db.ForeignKey("comprobantes.id"), nullable=True)
    monto = db.Column(db.Numeric(12, 2), nullable=False)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    medio = db.Column(db.String(20), nullable=True)  # transferencia / efectivo / otro
    origen = db.Column(db.String(15), nullable=False, default="panel")  # panel / agente / planilla
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


class Profesor(db.Model):
    __tablename__ = "profesores"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(20), nullable=True)
    activo = db.Column(db.Boolean, default=True)

    valores_hora = db.relationship("ValorHora", backref="profesor", order_by="ValorHora.vigente_desde.desc()")
    horas = db.relationship("HoraDictada", backref="profesor")


class ValorHora(db.Model):
    """
    Valor de la hora de cada profe, con historial como los precios de los planes.
    profesor_id vacío = valor por defecto para todos los que no tengan uno propio.
    """
    __tablename__ = "valores_hora"

    id = db.Column(db.Integer, primary_key=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey("profesores.id"), nullable=True, index=True)
    monto = db.Column(db.Numeric(12, 2), nullable=False)
    vigente_desde = db.Column(db.Date, nullable=False, index=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


class HoraDictada(db.Model):
    """La profe carga 'hice tantas horas'. El sueldo semanal sale de horas x valor vigente."""
    __tablename__ = "horas_dictadas"

    id = db.Column(db.Integer, primary_key=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey("profesores.id"), nullable=False, index=True)
    fecha = db.Column(db.Date, nullable=False, index=True)
    horas = db.Column(db.Numeric(5, 2), nullable=False)
    tipo = db.Column(db.String(15), nullable=True)  # grupal / particular (opcional)
    nota = db.Column(db.String(255), nullable=True)
    estado = db.Column(db.String(15), nullable=False, default="pendiente")  # pendiente / aprobada / rechazada
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


class Planificacion(db.Model):
    """Qué se entrena en la semana: 'esta semana volea y bandeja'."""
    __tablename__ = "planificaciones"

    id = db.Column(db.Integer, primary_key=True)
    semana_inicio = db.Column(db.Date, nullable=False, index=True)  # el lunes de esa semana
    titulo = db.Column(db.String(120), nullable=False)  # ej: "Volea y bandeja"
    detalle = db.Column(db.Text, nullable=True)
    categoria = db.Column(db.String(20), nullable=True)  # vacío = para todas
    creado_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)