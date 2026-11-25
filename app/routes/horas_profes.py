"""Profes y horas: cuánto se le paga a cada profe en el mes. SOLO el dueño.

Acá hay plata y tarifas: lo del dueño va con @requiere_login("dueno"); el encargado y los
profes reciben 403. La única excepción es /api/mis-horas: cada profe ve SOLO lo suyo, y el
profe sale siempre de g.usuario.profesor_id (nunca de lo que manda el panel).
"""
import csv
import io
from decimal import Decimal

from flask import Blueprint, Response, g, jsonify, request

from app import horas_profes, tarifas_profes
from app.extensions import db
from app.models_plataforma import Profesor
from app.routes.auth import requiere_login

horas_profes_bp = Blueprint("horas_profes", __name__)


def _json(valor):
    """Decimal -> número para el panel (Flask los manda como texto)."""
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_json(v) for v in valor]
    return valor


def _mes_o_error():
    rango = horas_profes.leer_mes(request.args.get("mes"))
    if not rango:
        return None, (jsonify({"error": "El mes tiene que ser AAAA-MM"}), 400)
    return rango, None


@horas_profes_bp.get("/api/profes-horas")
@requiere_login("dueno")
def resumen():
    rango, error = _mes_o_error()
    if error:
        return error
    datos = horas_profes.resumen_mes(*rango)
    # el cálculo solo trae a los que tuvieron clases o pendientes en el mes: sumo a los activos
    # que faltan (sin horas), así se les puede cargar la tarifa aunque todavía no hayan dado clases
    ya = {p["profesor_id"] for p in datos["profes"]}
    faltan = [p for p in Profesor.query.filter(Profesor.activo.is_(True)) if p.id not in ya]
    tarifas = horas_profes._tarifas([p.id for p in faltan])
    for p in faltan:
        datos["profes"].append({"profesor_id": p.id, "nombre": p.nombre, "clases": [], "sin_alumnos": [],
                                "pendientes": [], "horas": 0, "monto": 0, "sin_tarifa": False,
                                "tarifa": horas_profes.tarifa_en(tarifas[p.id], rango[1]), "horas_pendientes": 0})
    datos["profes"].sort(key=lambda x: (x["profesor_id"] is None, x["nombre"].lower()))
    # la marca de head coach (sus particulares de mañana tienen tarifa propia en Planes y precios)
    # y la próxima tarifa que ya está cargada para más adelante (si hay)
    head_coach = {pid for (pid,) in db.session.query(Profesor.id).filter(Profesor.es_head_coach.is_(True))}
    todas = horas_profes._tarifas([p["profesor_id"] for p in datos["profes"] if p["profesor_id"] is not None])
    for p in datos["profes"]:
        p["head_coach"] = p["profesor_id"] in head_coach
        futuras = [v for v in todas.get(p["profesor_id"], []) if v.vigente_desde > rango[1]]
        prox = min(futuras, key=lambda v: v.vigente_desde) if futuras else None
        p["proxima_tarifa"] = {"monto": prox.monto, "desde": prox.vigente_desde.isoformat()} if prox else None
    return jsonify(_json(datos))


def _error_tarifa(e):
    db.session.rollback()
    cuerpo = {"error": str(e)}
    if e.pedir_confirmacion:
        cuerpo["confirmar"] = True
        return jsonify(cuerpo), 409
    return jsonify(cuerpo), 400


@horas_profes_bp.get("/api/profes/<int:profesor_id>/tarifas")
@requiere_login("dueno")
def ver_tarifas(profesor_id):
    profe = db.session.get(Profesor, profesor_id)
    if not profe:
        return jsonify({"error": "No existe ese profe"}), 404
    return jsonify({"profesor_id": profe.id, "nombre": profe.nombre,
                    "tarifas": tarifas_profes.historial(profe.id)})


@horas_profes_bp.post("/api/profes/<int:profesor_id>/tarifas")
@requiere_login("dueno")
def nueva_tarifa(profesor_id):
    """Tarifa nueva con su vigencia. No pisa las anteriores. Un mes pasado pide confirmar (409)."""
    profe = db.session.get(Profesor, profesor_id)
    if not profe:
        return jsonify({"error": "No existe ese profe"}), 404
    d = request.get_json(silent=True) or {}
    try:
        tarifas_profes.agregar_tarifa(profe, d.get("monto"), d.get("desde"), g.usuario.id,
                                      confirmar_pasado=d.get("confirmar") is True)
    except tarifas_profes.ErrorTarifa as e:
        return _error_tarifa(e)
    db.session.commit()
    return jsonify({"profesor_id": profe.id, "tarifas": tarifas_profes.historial(profe.id)}), 201


@horas_profes_bp.post("/api/profes")
@requiere_login("dueno")
def nuevo_profe():
    """Alta de profe: nombre, Head Coach y (opcional) la primera tarifa con su vigencia."""
    d = request.get_json(silent=True) or {}
    try:
        profe = tarifas_profes.crear_profe(d.get("nombre"), d.get("head_coach", False), d.get("monto"),
                                           d.get("desde"), g.usuario.id, confirmar_pasado=d.get("confirmar") is True)
    except tarifas_profes.ErrorTarifa as e:
        return _error_tarifa(e)
    db.session.commit()
    return jsonify({"profesor_id": profe.id, "nombre": profe.nombre, "head_coach": profe.es_head_coach,
                    "tarifas": tarifas_profes.historial(profe.id)}), 201


@horas_profes_bp.post("/api/profes/<int:profesor_id>/head-coach")
@requiere_login("dueno")
def marcar_head_coach(profesor_id):
    """Prende o apaga la marca de head coach. Cambia la cuota de sus alumnos desde que rija su tarifa."""
    profe = db.session.get(Profesor, profesor_id)
    if not profe:
        return jsonify({"error": "No existe ese profe"}), 404
    d = request.get_json(silent=True) or {}
    if not isinstance(d.get("activo"), bool):
        return jsonify({"error": "Falta 'activo' (true o false)"}), 400
    tarifas_profes.marcar_head_coach(profe, d["activo"], g.usuario.id)  # queda en la auditoría
    db.session.commit()
    return jsonify({"profesor_id": profe.id, "head_coach": profe.es_head_coach})


def _num(valor):
    # para Excel en castellano: coma decimal y sin ".00" de más
    if valor is None:
        return ""
    texto = f"{Decimal(valor):.2f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


@horas_profes_bp.get("/api/profes-horas/csv")
@requiere_login("dueno")
def exportar_csv():
    rango, error = _mes_o_error()
    if error:
        return error
    datos = horas_profes.resumen_mes(*rango)

    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";")
    w.writerow(["Profe", "Estado", "Fecha", "Hora", "Grupo", "Presentes", "Horas", "Tarifa", "Monto"])
    estados = (("clases", "Pagada"), ("sin_alumnos", "Sin alumnos (no se paga)"),
               ("pendientes", "Pendiente de confirmar"))
    for p in datos["profes"]:
        for clave, texto in estados:
            for c in p[clave]:
                w.writerow([p["nombre"], texto, c["fecha"], c["hora"], c["grupo"], c["presentes"],
                            _num(c["horas"]), _num(c.get("tarifa")), _num(c.get("monto"))])
    w.writerow([])
    w.writerow(["Profe", "Horas pagas", "Tarifa vigente", "Monto", "Horas pendientes", "Sin tarifa"])
    for p in datos["profes"]:
        w.writerow([p["nombre"], _num(p["horas"]), _num(p["tarifa"]), _num(p["monto"]),
                    _num(p["horas_pendientes"]), "si" if p["sin_tarifa"] else ""])
    w.writerow(["TOTAL", _num(datos["total_horas"]), "", _num(datos["total_monto"]), "", ""])

    mes = datos["desde"][:7]
    # BOM para que Excel lea bien las tildes
    return Response("﻿" + salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="horas_profes_{mes}.csv"'})


# ---------- la vista de cada profe ----------

@horas_profes_bp.get("/api/mis-horas")
@requiere_login("profe")
def mis_horas():
    """Las horas del mes del profe logueado: sus clases, su tarifa y su monto. Nada de otros."""
    # solo de acá: se ignora cualquier id que venga en la url. "Ver como" ya viene validado (solo dueño)
    vista = g.get("ver_como")
    profesor_id = vista.id if vista else g.usuario.profesor_id
    if not profesor_id:
        return jsonify({"error": "Tu usuario no está vinculado a un profe"}), 403
    rango, error = _mes_o_error()
    if error:
        return error
    datos = horas_profes.resumen_mes(*rango, profesor_id=profesor_id)
    # por las dudas, nos quedamos solo con su fila (el cálculo ya filtra por él)
    suyo = next((p for p in datos["profes"] if p["profesor_id"] == profesor_id), None)
    # sin clases en el mes igual mostramos su tarifa vigente al cierre
    vacio = {"horas": 0, "monto": 0, "sin_tarifa": False, "horas_pendientes": 0,
             "tarifa": horas_profes.tarifa_en(horas_profes._tarifas([profesor_id])[profesor_id], rango[1]),
             "clases": [], "pendientes": [], "sin_alumnos": []}
    p = suyo or vacio
    return jsonify(_json({
        "desde": datos["desde"],
        "hasta": datos["hasta"],
        "horas": p["horas"],
        "monto": p["monto"],
        "tarifa": p["tarifa"],
        "sin_tarifa": p["sin_tarifa"],
        "horas_pendientes": p["horas_pendientes"],
        "clases": p["clases"],
        "pendientes": p["pendientes"],
        "sin_alumnos": p["sin_alumnos"],
    }))
