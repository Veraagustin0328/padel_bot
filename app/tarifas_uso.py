"""Si una fila de tarifa se puede cambiar o quitar de verdad, o solo corregir con historial.

Regla (la eligió el dueño):
- Se puede editar o borrar de verdad si NINGUNA cuota generada la usó, rija o no.
- Si alguna cuota generada la usó, no se toca: se carga un precio nuevo con fecha o se da de baja
  desde una fecha.

"La usó" se calcula, porque la cuota no guarda qué tarifa usó: una cuota (concepto "cuota") de un
mes en que esa fila era la que regía el día 1, y que en su detalle tiene "franja tipo [de N] x".
Se mira cualquier cantidad de veces porque las sumadas (ej. x3 = x2 + x1) usan otras filas.
Si se equivoca, es para el lado seguro: bloquea, nunca deja borrar una usada.
Una fila inactiva (una baja) la "usó" cualquier cuota de esos meses: su efecto fue dejar sin precio.
"""
from sqlalchemy import or_

from app.models_cuotas import CuotaMes
from app.models_tarifas import Tarifa


def _nombre_en_detalle(t):
    # mismo formato que cuotas.cuota_de: "manana particular de 2 x1 = 72000"
    return f"{t.franja} {t.tipo}" + (f" de {t.personas}" if t.personas else "") + " x"


def _siguiente(t):
    """La fila que la reemplaza (misma tarifa, fecha posterior), o None."""
    filas = (Tarifa.query.filter_by(franja=t.franja, tipo=t.tipo, personas=t.personas,
                                    veces_por_semana=t.veces_por_semana)
             .order_by(Tarifa.vigente_desde, Tarifa.id).all())
    despues = [f for f in filas if (f.vigente_desde, f.id) > (t.vigente_desde, t.id)]
    return despues[0] if despues else None


def cuotas_que_la_usaron(t):
    """Cuotas generadas que salieron (o pudieron salir) de esta fila."""
    q = CuotaMes.query.filter(CuotaMes.concepto == "cuota", CuotaMes.mes >= t.vigente_desde)
    sig = _siguiente(t)
    if sig is not None:
        q = q.filter(CuotaMes.mes < sig.vigente_desde)
    if t.activa:
        nombre = _nombre_en_detalle(t)
        q = q.filter(or_(CuotaMes.detalle.ilike(f"{nombre}%"), CuotaMes.detalle.ilike(f"%; {nombre}%")))
    return q.all()


def estado_fila(t, hoy):
    """{puede_directo, rige, cuotas, meses, explicacion} para mostrar antes de confirmar."""
    usadas = cuotas_que_la_usaron(t)
    meses = sorted({c.mes.strftime("%m/%Y") for c in usadas}, key=lambda s: (s[3:], s[:2]))
    rige = t.vigente_desde <= hoy
    desde = t.vigente_desde.strftime("%d/%m/%Y")
    if not usadas:
        cuando = f"Rige desde el {desde}" if rige else f"Todavía no rige (arranca el {desde})"
        explicacion = f"{cuando} y ninguna cuota generada la usó: se puede cambiar el precio o quitar."
    else:
        explicacion = (f"La usaron {len(usadas)} cuotas ya generadas ({', '.join(meses)}): no se puede "
                       "cambiar ni quitar. Cargá un precio nuevo con fecha o dala de baja desde una fecha.")
    return {"id": t.id, "puede_directo": not usadas, "rige": rige, "cuotas": len(usadas), "meses": meses,
            "explicacion": explicacion}
