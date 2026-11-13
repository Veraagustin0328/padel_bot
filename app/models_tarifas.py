"""Tarifas de la academia: el precio depende de franja + tipo + cantidad de personas + veces por semana.

La cuota de un alumno es la suma de sus clases, cada una a su tarifa
(ej. 1 grupal + 1 particular = tarifa de 1 grupal + tarifa de 1 particular).

Guardan historial: un aumento es una fila nueva con su vigente_desde, nunca se pisa la anterior.
En una fecha rige la última fila con vigente_desde <= esa fecha (si esa fila está inactiva, no hay precio).
"""
from datetime import date

from app.extensions import db

FRANJAS = ("manana", "tarde", "sabado", "kids", "head_coach")
# head_coach: particulares de mañana del profe marcado es_head_coach (solo tipo particular)
FRANJA_HEAD_COACH = "head_coach"
TIPOS_TARIFA = ("academia", "particular", "promo_2x1")


class Tarifa(db.Model):
    __tablename__ = "tarifas"
    __table_args__ = (
        db.UniqueConstraint("franja", "tipo", "personas", "veces_por_semana", "vigente_desde", name="uq_tarifa"),
    )

    id = db.Column(db.Integer, primary_key=True)
    franja = db.Column(db.String(10), nullable=False)    # manana / tarde / sabado / kids / head_coach
    tipo = db.Column(db.String(12), nullable=False)      # academia / particular / promo_2x1
    personas = db.Column(db.SmallInteger, nullable=False, default=0)  # 0 = no aplica, 1, 2, 3 (3 = "3 o 4")
    veces_por_semana = db.Column(db.SmallInteger, nullable=False, default=1)
    precio = db.Column(db.Integer, nullable=False)       # por mes, por persona
    activa = db.Column(db.Boolean, nullable=False, default=True)
    vigente_desde = db.Column(db.Date, nullable=False, default=date.today)