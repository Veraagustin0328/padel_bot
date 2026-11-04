"""Cuotas mensuales y pagos de los alumnos."""
from datetime import date, datetime

from app.extensions import db

# cada alumno tiene, por mes, una cuota y puede tener cargos aparte (inscripción, ajustes)
CONCEPTOS = ("cuota", "inscripcion", "ajuste")
MEDIOS_PAGO = ("efectivo", "transferencia", "mercadopago", "otro")


class CuotaMes(db.Model):
    __tablename__ = "cuotas_mes"

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id", ondelete="CASCADE"), nullable=False, index=True)
    mes = db.Column(db.Date, nullable=False, index=True)          # siempre el día 1 del mes
    concepto = db.Column(db.String(20), nullable=False, default="cuota")
    monto = db.Column(db.Integer, nullable=False, default=0)      # lo que se cobra (se puede ajustar a mano)
    monto_calculado = db.Column(db.Integer, nullable=True)         # lo que dio la cuenta automática
    nota = db.Column(db.String(200), nullable=True)
    detalle = db.Column(db.Text, nullable=True)                    # de dónde salió el monto
    creada = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("alumno_id", "mes", "concepto", name="uq_cuota_alumno_mes_concepto"),
    )


class PagoCuota(db.Model):
    __tablename__ = "pagos_cuota"

    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id", ondelete="CASCADE"), nullable=False, index=True)
    mes = db.Column(db.Date, nullable=False, index=True)          # a qué mes se aplica
    concepto = db.Column(db.String(20), nullable=False, default="cuota", server_default="cuota")
    monto = db.Column(db.Integer, nullable=False)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    medio = db.Column(db.String(20), nullable=False, default="efectivo")
    # fila del comprobante en la planilla si vino de ahí; único así un comprobante no paga dos veces
    comprobante_id = db.Column(db.Integer, nullable=True, unique=True)
    nota = db.Column(db.String(200), nullable=True)
    creado_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    creado = db.Column(db.DateTime, default=datetime.utcnow)
