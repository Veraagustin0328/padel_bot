"""API de comprobantes para el panel.
Lee y escribe la misma pestaña "comprobantes" que usa el agente, así Gabi ve lo mismo en los dos lados.
Estados: PENDIENTE -> CONFIRMADO -> APLICADO (o ANULADO).
"""
from flask import Blueprint, jsonify, request

from app import planilla
from app.routes.auth import requiere_login
from app.sheets_client import leer_pestana, pestana

comprobantes_bp = Blueprint("comprobantes", __name__)

TAB = planilla.TAB_COMPROBANTES
ENC = planilla.ENC_COMPROBANTES


def _a_json(f):
    monto = planilla._a_numero(f.get("MONTO"))
    if monto is not None and monto == int(monto):
        monto = int(monto)
    return {
        "id": f["_fila"],  # el número de fila en la hoja
        "fecha": f.get("FECHA", ""),
        "telefono": str(f.get("TELEFONO", "")),
        "alumno": f.get("ALUMNO", "") or "",
        "monto": monto,
        "mes": f.get("MES", ""),
        "estado": planilla._norm(f.get("ESTADO")),
    }


def _buscar(fila):
    for f in leer_pestana(TAB):
        if f["_fila"] == fila:
            return f
    return None


def _cambiar_estado(fila, nuevo, desde, monto=None):
    f = _buscar(fila)
    if not f:
        return jsonify({"error": "No encontré ese comprobante."}), 404
    if planilla._norm(f.get("ESTADO")) not in desde:
        return jsonify({"error": "Ese comprobante ya cambió de estado. Refrescá la lista."}), 409
    ws = pestana(TAB, ENC)
    if monto is not None:
        ws.update_cell(fila, ENC.index("MONTO") + 1, monto)
    ws.update_cell(fila, ENC.index("ESTADO") + 1, nuevo)
    return jsonify({"ok": True, "id": fila, "estado": nuevo.lower()})


@comprobantes_bp.get("/api/comprobantes")
@requiere_login("encargado")
def listar():
    estado = (request.args.get("estado") or "pendiente").lower()
    try:
        filas = leer_pestana(TAB)
    except Exception as e:
        return jsonify({"error": f"No pude leer la planilla: {e}"}), 502
    items = [_a_json(f) for f in filas if f.get("TELEFONO") or f.get("ALUMNO")]
    if estado != "todos":
        items = [i for i in items if i["estado"] == estado]
    items.reverse()  # los más nuevos primero
    return jsonify(items[:200])


@comprobantes_bp.post("/api/comprobantes/<int:fila>/confirmar")
@requiere_login("encargado")
def confirmar(fila):
    datos = request.get_json(silent=True) or {}
    monto = None
    if datos.get("monto") not in (None, ""):
        monto = planilla._a_numero(datos.get("monto"))
        if monto is None or monto <= 0:
            return jsonify({"error": "El monto no es válido."}), 400
    try:
        return _cambiar_estado(fila, "CONFIRMADO", ("pendiente",), monto)
    except Exception as e:
        return jsonify({"error": f"No pude escribir en la planilla: {e}"}), 502


@comprobantes_bp.post("/api/comprobantes/<int:fila>/rechazar")
@requiere_login("encargado")
def rechazar(fila):
    try:
        return _cambiar_estado(fila, "ANULADO", ("pendiente", "confirmado"))
    except Exception as e:
        return jsonify({"error": f"No pude escribir en la planilla: {e}"}), 502


@comprobantes_bp.post("/api/comprobantes/aplicar")
@requiere_login("encargado")
def aplicar():
    try:
        return jsonify(planilla.aplicar_pagos_confirmados())
    except Exception as e:
        return jsonify({"error": f"No pude escribir en la planilla: {e}"}), 502