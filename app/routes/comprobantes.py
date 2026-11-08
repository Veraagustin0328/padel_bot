"""API de comprobantes para el panel.
Lee y escribe la misma pestaña "comprobantes" que usa el agente, así Gabi ve lo mismo en los dos lados.
Estados: PENDIENTE -> CONFIRMADO -> APLICADO (o ANULADO).
Al confirmar se crea un PagoCuota en Neon con comprobante_id = fila; al rechazar o volver a pendiente se borra.
"""
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from app import planilla
from app.extensions import db
from app.models import Alumno
from app.models_cuotas import CONCEPTOS, MEDIOS_PAGO, PagoCuota
from app.routes.auth import requiere_login
from app.sheets_client import leer_pestana, pestana

comprobantes_bp = Blueprint("comprobantes", __name__)

TAB = planilla.TAB_COMPROBANTES
ENC = planilla.ENC_COMPROBANTES


# ---------- a quién y a qué mes corresponde ----------

def _indices_alumnos():
    """Teléfono (últimos 10) -> [ids] y nombre normalizado -> [ids], para no consultar por cada fila."""
    por_tel, por_nombre = {}, {}
    for a in Alumno.query.all():
        t = planilla._tel(a.telefono)
        if t:
            por_tel.setdefault(t, []).append(a.id)  # lista: papás con varios hijos comparten tel
        por_nombre.setdefault(planilla._norm(a.nombre), []).append(a.id)
    return por_tel, por_nombre


def _alumno_de(f, indices):
    """Primero por teléfono; si no, por nombre exacto y solo si hay uno.
    Si el tel es de varios alumnos devuelvo None: que elijan a mano."""
    por_tel, por_nombre = indices
    t = planilla._tel(f.get("TELEFONO"))
    if t and t in por_tel:
        ids_tel = por_tel[t]
        return ids_tel[0] if len(ids_tel) == 1 else None
    ids = por_nombre.get(planilla._norm(f.get("ALUMNO")), [])
    return ids[0] if len(ids) == 1 else None


def _mes_de(f):
    """'Noviembre' + FECHA '03/11/2026 10:20' -> date(2026, 11, 1). Sin mes válido -> None."""
    nombre = planilla._norm(f.get("MES")).upper()
    if nombre not in planilla.MESES:
        return None
    mes = planilla.MESES.index(nombre) + 1
    try:
        cuando = datetime.strptime(str(f.get("FECHA", "")).split()[0], "%d/%m/%Y")
    except (ValueError, IndexError):
        cuando = planilla._ahora()
    anio = cuando.year
    if mes - cuando.month > 6:  # comprobante de diciembre mandado en enero
        anio -= 1
    return date(anio, mes, 1)


def _mes_txt(txt):
    """'2026-11' -> date(2026, 11, 1), o None."""
    try:
        y, m = str(txt).split("-")
        return date(int(y), int(m), 1)
    except Exception:
        return None


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _a_json(f, indices, pagos):
    monto = planilla._a_numero(f.get("MONTO"))
    if monto is not None and monto == int(monto):
        monto = int(monto)
    mes = _mes_de(f)
    return {
        "id": f["_fila"],  # el número de fila en la hoja
        "fecha": f.get("FECHA", ""),
        "telefono": str(f.get("TELEFONO", "")),
        "alumno": f.get("ALUMNO", "") or "",
        "monto": monto,
        "mes": f.get("MES", ""),
        "estado": planilla._norm(f.get("ESTADO")),
        "alumno_id": _alumno_de(f, indices),           # None si no lo pude identificar
        "mes_iso": mes.strftime("%Y-%m") if mes else None,
        "pago_id": pagos.get(f["_fila"]),               # el PagoCuota que generó, si hay
    }


def _buscar(fila):
    for f in leer_pestana(TAB):
        if f["_fila"] == fila:
            return f
    return None


def _escribir_estado(fila, nuevo, monto=None):
    ws = pestana(TAB, ENC)
    if monto is not None:
        ws.update_cell(fila, ENC.index("MONTO") + 1, monto)
    ws.update_cell(fila, ENC.index("ESTADO") + 1, nuevo)


def _borrar_pago_de(fila):
    """Saca de la sesión el pago que generó este comprobante (el commit lo hace quien llama)."""
    p = PagoCuota.query.filter_by(comprobante_id=fila).first()
    if p:
        db.session.delete(p)
    return p is not None


def _cambiar_estado(fila, nuevo, desde, borrar_pago=False):
    f = _buscar(fila)
    if not f:
        return jsonify({"error": "No encontré ese comprobante."}), 404
    if planilla._norm(f.get("ESTADO")) not in desde:
        return jsonify({"error": "Ese comprobante ya cambió de estado. Refrescá la lista."}), 409
    borrado = _borrar_pago_de(fila) if borrar_pago else False
    db.session.flush()
    _escribir_estado(fila, nuevo)  # si la planilla falla, no se commitea el borrado
    db.session.commit()
    return jsonify({"ok": True, "id": fila, "estado": nuevo.lower(), "pago_borrado": borrado})


# ---------- rutas ----------

@comprobantes_bp.get("/api/comprobantes")
@requiere_login("encargado")
def listar():
    estado = (request.args.get("estado") or "pendiente").lower()
    try:
        filas = leer_pestana(TAB)
    except Exception as e:
        return jsonify({"error": f"No pude leer la planilla: {e}"}), 502
    indices = _indices_alumnos()
    pagos = {p.comprobante_id: p.id for p in PagoCuota.query.filter(PagoCuota.comprobante_id.isnot(None))}
    items = [_a_json(f, indices, pagos) for f in filas if f.get("TELEFONO") or f.get("ALUMNO")]
    if estado != "todos":
        items = [i for i in items if i["estado"] == estado]
    items.reverse()  # los más nuevos primero
    return jsonify(items[:200])


@comprobantes_bp.get("/api/comprobantes/alumnos")
@requiere_login("encargado")
def alumnos():
    """Para el selector cuando el comprobante no trae alumno reconocible."""
    lista = Alumno.query.order_by(Alumno.nombre).all()
    return jsonify([{"id": a.id, "nombre": a.nombre, "estado": a.estado} for a in lista])


@comprobantes_bp.post("/api/comprobantes/<int:fila>/confirmar")
@requiere_login("encargado")
def confirmar(fila):
    """Aprueba el comprobante y crea el PagoCuota. Lo que manda el panel pisa lo detectado."""
    d = request.get_json(silent=True) or {}
    try:
        f = _buscar(fila)
    except Exception as e:
        return jsonify({"error": f"No pude leer la planilla: {e}"}), 502
    if not f:
        return jsonify({"error": "No encontré ese comprobante."}), 404
    if planilla._norm(f.get("ESTADO")) != "pendiente":
        return jsonify({"error": "Ese comprobante ya cambió de estado. Refrescá la lista."}), 409
    if PagoCuota.query.filter_by(comprobante_id=fila).first():
        return jsonify({"error": "Este comprobante ya generó un pago."}), 409

    monto = planilla._a_numero(d.get("monto")) if d.get("monto") not in (None, "") else planilla._a_numero(f.get("MONTO"))
    if monto is None or monto <= 0:
        return jsonify({"error": "El monto no es válido."}), 400
    monto = int(round(monto))

    alumno_id = _entero(d.get("alumno_id")) or _alumno_de(f, _indices_alumnos())
    mes = _mes_txt(d.get("mes")) if d.get("mes") else _mes_de(f)
    if not alumno_id or not mes:
        # no creo nada: el panel tiene que elegir alumno y mes
        return jsonify({"error": "No pude identificar el alumno o el mes. Elegilos antes de aprobar.",
                        "falta": [k for k, v in (("alumno", alumno_id), ("mes", mes)) if not v]}), 422
    if not db.session.get(Alumno, alumno_id):
        return jsonify({"error": "No existe ese alumno."}), 404

    concepto = d.get("concepto") if d.get("concepto") in CONCEPTOS else "cuota"
    medio = d.get("medio") if d.get("medio") in MEDIOS_PAGO else "transferencia"
    p = PagoCuota(alumno_id=alumno_id, mes=mes, concepto=concepto, monto=monto, medio=medio,
                  comprobante_id=fila, nota=f"Comprobante #{fila}",
                  creado_por=getattr(g.get("usuario"), "id", None))
    try:
        db.session.add(p)
        db.session.flush()  # acá salta el unique si alguien aprobó en paralelo
        _escribir_estado(fila, "CONFIRMADO", monto)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Este comprobante ya generó un pago."}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"No pude escribir en la planilla: {e}"}), 502
    return jsonify({"ok": True, "id": fila, "estado": "confirmado", "pago_id": p.id})


@comprobantes_bp.post("/api/comprobantes/<int:fila>/rechazar")
@requiere_login("encargado")
def rechazar(fila):
    try:
        return _cambiar_estado(fila, "ANULADO", ("pendiente", "confirmado"), borrar_pago=True)
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"No pude escribir en la planilla: {e}"}), 502


@comprobantes_bp.post("/api/comprobantes/<int:fila>/desaprobar")
@requiere_login("encargado")
def desaprobar(fila):
    """Vuelve un confirmado a pendiente y borra el pago que había generado."""
    try:
        return _cambiar_estado(fila, "PENDIENTE", ("confirmado",), borrar_pago=True)
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"No pude escribir en la planilla: {e}"}), 502


@comprobantes_bp.post("/api/comprobantes/aplicar")
@requiere_login("encargado")
def aplicar():
    try:
        return jsonify(planilla.aplicar_pagos_confirmados())
    except Exception as e:
        return jsonify({"error": f"No pude escribir en la planilla: {e}"}), 502
