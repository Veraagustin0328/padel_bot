"""Cuotas y pagos: generar el mes, ver quién debe, registrar pagos y ajustes."""
from datetime import date

from flask import Blueprint, g, jsonify, request
from app.cuotas import cargar_tarifas, clases_del_mes, cuota_de
from app.extensions import db
from app.models import Alumno
from app.models_cuotas import CONCEPTOS, MEDIOS_PAGO, CuotaMes, PagoCuota
from app.routes.auth import requiere_login

cuotas_bp = Blueprint("cuotas_panel", __name__)


def _mes(txt):
    """'2026-11' -> date(2026, 11, 1), o None si no sirve."""
    try:
        y, mm = str(txt).split("-")
        return date(int(y), int(mm), 1)
    except Exception:
        return None


def _quien():
    return getattr(g.get("usuario"), "id", None)


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def generar_mes(inicio):
    """Crea la cuota de cada alumno con clases ese mes. No pisa las que ya existen."""
    por_alumno = clases_del_mes(inicio)

    ya = {c.alumno_id for c in CuotaMes.query.filter_by(mes=inicio, concepto="cuota")}
    tarifas = cargar_tarifas(inicio)  # las que rigen ese mes
    creadas, existian, sin_precio = 0, 0, []
    for alumno_id, cs in por_alumno.items():
        if alumno_id in ya:
            existian += 1
            continue
        r = cuota_de(cs, tarifas)
        if r["total"] <= 0:
            sin_precio.append(alumno_id)
            continue
        detalle = "; ".join(r["lineas"] + [f"AVISO: {a}" for a in r["avisos"]])
        db.session.add(CuotaMes(
            alumno_id=alumno_id, mes=inicio, concepto="cuota",
            monto=r["total"], monto_calculado=r["total"], detalle=detalle,
        ))
        creadas += 1
    db.session.commit()
    return {"creadas": creadas, "ya_existian": existian, "sin_precio": len(sin_precio)}


@cuotas_bp.post("/api/cuotas/generar")
@requiere_login("encargado")
def generar():
    inicio = _mes((request.get_json(silent=True) or {}).get("mes"))
    if not inicio:
        return jsonify(error="Mes inválido, usá AAAA-MM"), 400
    return jsonify(generar_mes(inicio))


@cuotas_bp.get("/api/cuotas")
@requiere_login("encargado")
def listar():
    inicio = _mes(request.args.get("mes", ""))
    if not inicio:
        return jsonify(error="Mes inválido, usá AAAA-MM"), 400

    cuotas = CuotaMes.query.filter_by(mes=inicio).all()
    pagos = PagoCuota.query.filter_by(mes=inicio).order_by(PagoCuota.fecha, PagoCuota.id).all()
    ids = {c.alumno_id for c in cuotas} | {p.alumno_id for p in pagos}
    nombres = {a.id: a.nombre for a in Alumno.query.filter(Alumno.id.in_(ids))} if ids else {}

    items = {}
    for a_id in ids:
        items[a_id] = {"alumno_id": a_id, "alumno": nombres.get(a_id, f"#{a_id}"),
                       "cargos": [], "pagos": [], "cuota": 0, "pagado": 0}
    for c in cuotas:
        it = items[c.alumno_id]
        it["cuota"] += c.monto
        it["cargos"].append({"id": c.id, "concepto": c.concepto, "monto": c.monto,
                             "calculado": c.monto_calculado, "nota": c.nota, "detalle": c.detalle})
    for p in pagos:
        it = items[p.alumno_id]
        it["pagado"] += p.monto
        it["pagos"].append({"id": p.id, "monto": p.monto, "fecha": p.fecha.isoformat(),
                            "medio": p.medio, "nota": p.nota, "concepto": p.concepto,
                            "comprobante_id": p.comprobante_id,
                            "origen": f"Comprobante #{p.comprobante_id}" if p.comprobante_id else "Manual"})

    lista = []
    for it in items.values():
        it["debe"] = max(it["cuota"] - it["pagado"], 0)
        it["a_favor"] = max(it["pagado"] - it["cuota"], 0)
        if it["a_favor"] > 0:
            it["estado"] = "a_favor"  # pagó de más: no es parcial
        elif it["cuota"] > 0 and it["debe"] == 0:
            it["estado"] = "pago"
        elif it["pagado"] > 0:
            it["estado"] = "parcial"
        else:
            it["estado"] = "debe"
        lista.append(it)
    lista.sort(key=lambda x: (-x["debe"], x["alumno"].lower()))

    return jsonify(
        mes=inicio.strftime("%Y-%m"),
        items=lista,
        totales={
            "cuotas": sum(i["cuota"] for i in lista),
            "pagado": sum(i["pagado"] for i in lista),
            "deuda": sum(i["debe"] for i in lista),
            "deben": sum(1 for i in lista if i["debe"] > 0),
            "alumnos": len(lista),
        },
    )


@cuotas_bp.post("/api/cuotas/pago")
@requiere_login("encargado")
def registrar_pago():
    d = request.get_json(silent=True) or {}
    inicio, monto, alumno_id = _mes(d.get("mes")), _entero(d.get("monto")), _entero(d.get("alumno_id"))
    if not inicio or not monto or monto <= 0 or not alumno_id:
        return jsonify(error="Faltan alumno, mes o un monto mayor a 0"), 400
    if not db.session.get(Alumno, alumno_id):
        return jsonify(error="No existe ese alumno"), 404
    medio = d.get("medio") if d.get("medio") in MEDIOS_PAGO else "efectivo"
    concepto = d.get("concepto") if d.get("concepto") in CONCEPTOS else "cuota"
    p = PagoCuota(alumno_id=alumno_id, mes=inicio, concepto=concepto, monto=monto, medio=medio,
             nota=(d.get("nota") or "")[:200] or None, creado_por=_quien())
    db.session.add(p)
    db.session.commit()
    return jsonify(id=p.id), 201


@cuotas_bp.delete("/api/cuotas/pago/<int:pago_id>")
@requiere_login("encargado")
def borrar_pago(pago_id):
    p = db.session.get(PagoCuota, pago_id)
    if not p:
        return jsonify(error="No existe ese pago"), 404
    if p.comprobante_id:
        # si lo borro acá el comprobante queda confirmado sin pago
        return jsonify(error=f"Este pago viene del comprobante #{p.comprobante_id}: rechazalo o volvelo a pendiente desde Comprobantes"), 409
    db.session.delete(p)
    db.session.commit()
    return jsonify(ok=True)


@cuotas_bp.patch("/api/cuotas/<int:cuota_id>")
@requiere_login("encargado")
def ajustar(cuota_id):
    """Cambiar el monto a mano (prorrateo, descuento) con una nota de por qué."""
    c = db.session.get(CuotaMes, cuota_id)
    if not c:
        return jsonify(error="No existe esa cuota"), 404
    d = request.get_json(silent=True) or {}
    if "monto" in d:
        monto = _entero(d["monto"])
        if monto is None or monto < 0:
            return jsonify(error="Monto inválido"), 400
        c.monto = monto
    if "nota" in d:
        c.nota = (d["nota"] or "")[:200] or None
    db.session.commit()
    return jsonify(ok=True)


@cuotas_bp.post("/api/cuotas/cargo")
@requiere_login("encargado")
def agregar_cargo():
    """Cargo aparte: inscripción o ajuste. Uno de cada tipo por alumno y mes."""
    d = request.get_json(silent=True) or {}
    inicio, monto, alumno_id = _mes(d.get("mes")), _entero(d.get("monto")), _entero(d.get("alumno_id"))
    concepto = d.get("concepto")
    if concepto not in CONCEPTOS or concepto == "cuota" or not inicio or monto is None or not alumno_id:
        return jsonify(error="Faltan alumno, mes, monto o el concepto (inscripcion / ajuste)"), 400
    if concepto == "inscripcion" and CuotaMes.query.filter_by(alumno_id=alumno_id, concepto="inscripcion").first():
        return jsonify(error="Este alumno ya pagó la inscripción, se cobra una sola vez"), 409
    if CuotaMes.query.filter_by(alumno_id=alumno_id, mes=inicio, concepto=concepto).first():
        return jsonify(error="Ese cargo ya existe, editalo"), 409
    c = CuotaMes(alumno_id=alumno_id, mes=inicio, concepto=concepto, monto=monto,
              nota=(d.get("nota") or "")[:200] or None)
    db.session.add(c)
    db.session.commit()
    return jsonify(id=c.id), 201