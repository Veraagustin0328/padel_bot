"""
Planes y precios. Los precios guardan historial: cada cambio es una fila nueva
con la fecha desde la que rige, nunca se pisa el valor anterior.
Todas las rutas piden login (encargado o admin).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

from flask import Blueprint, request, jsonify

from app.extensions import db
from app.models_plataforma import Plan, PrecioPlan
from app.routes.auth import requiere_login

planes_bp = Blueprint("planes", __name__)


# ---------- ayudas ----------

def _hoy():
    # hora argentina (UTC-3), así el "hoy" no se corre de noche
    return (datetime.utcnow() - timedelta(hours=3)).date()


def _fecha(texto, defecto=None):
    if not texto:
        return defecto
    try:
        return date.fromisoformat(str(texto))
    except ValueError:
        raise ValueError("La fecha tiene que ser AAAA-MM-DD")


def _decimal(valor, campo):
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        raise ValueError(f"{campo} no es un número válido")
    if not d.is_finite():
        raise ValueError(f"{campo} no es un número válido")
    return d


def _monto(valor):
    m = _decimal(valor, "El monto")
    if m <= 0:
        raise ValueError("El monto tiene que ser mayor a cero")
    return m.quantize(Decimal("0.01"))


def _entero(valor, campo):
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{campo} tiene que ser un número entero")
    if n < 0 or n > 14:
        raise ValueError(f"{campo} está fuera de rango")
    return n


def _con_validacion(f):
    """Si algo falla al validar, devuelve 400 con el motivo en vez de explotar."""
    @wraps(f)
    def envoltura(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 400
    return envoltura


def _precio_en(plan_id, fecha):
    """Precio que rige en una fecha: el último con vigente_desde <= fecha."""
    return (
        PrecioPlan.query
        .filter(PrecioPlan.plan_id == plan_id, PrecioPlan.vigente_desde <= fecha)
        .order_by(PrecioPlan.vigente_desde.desc(), PrecioPlan.id.desc())
        .first()
    )


def _guardar_precio(plan_id, monto, desde):
    """Si ya hay un precio para esa misma fecha lo corrige, si no crea uno nuevo."""
    existente = PrecioPlan.query.filter_by(plan_id=plan_id, vigente_desde=desde).first()
    if existente:
        existente.monto = monto
    else:
        db.session.add(PrecioPlan(plan_id=plan_id, monto=monto, vigente_desde=desde))


def _plan_json(plan):
    hoy = _hoy()
    vigente = _precio_en(plan.id, hoy)
    programado = (
        PrecioPlan.query
        .filter(PrecioPlan.plan_id == plan.id, PrecioPlan.vigente_desde > hoy)
        .order_by(PrecioPlan.vigente_desde.asc())
        .first()
    )
    return {
        "id": plan.id,
        "nombre": plan.nombre,
        "grupales_por_semana": plan.grupales_por_semana,
        "particulares_por_semana": plan.particulares_por_semana,
        "descripcion": plan.descripcion,
        "activo": plan.activo,
        "precio_vigente": float(vigente.monto) if vigente else None,
        "vigente_desde": vigente.vigente_desde.isoformat() if vigente else None,
        "precio_programado": (
            {"monto": float(programado.monto), "desde": programado.vigente_desde.isoformat()}
            if programado else None
        ),
    }


def _buscar_plan(plan_id):
    return db.session.get(Plan, plan_id)


# ---------- rutas ----------

@planes_bp.get("/api/planes")
@requiere_login("encargado")
def listar_planes():
    planes = Plan.query.order_by(Plan.grupales_por_semana, Plan.particulares_por_semana, Plan.id).all()
    return jsonify([_plan_json(p) for p in planes])


@planes_bp.post("/api/planes")
@requiere_login("encargado")
@_con_validacion
def crear_plan():
    d = request.get_json(silent=True) or {}
    nombre = (d.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("Falta el nombre del plan")
    grupales = _entero(d.get("grupales_por_semana", 0), "Las clases grupales")
    particulares = _entero(d.get("particulares_por_semana", 0), "Las clases particulares")
    if grupales + particulares == 0:
        raise ValueError("El plan tiene que incluir al menos una clase por semana")
    monto = _monto(d.get("precio"))
    desde = _fecha(d.get("vigente_desde"), _hoy())

    plan = Plan(
        nombre=nombre,
        grupales_por_semana=grupales,
        particulares_por_semana=particulares,
        descripcion=(d.get("descripcion") or None),
    )
    db.session.add(plan)
    db.session.flush()  # para tener el id antes de cargar el precio
    _guardar_precio(plan.id, monto, desde)
    db.session.commit()
    return jsonify(_plan_json(plan)), 201


@planes_bp.patch("/api/planes/<int:plan_id>")
@requiere_login("encargado")
@_con_validacion
def editar_plan(plan_id):
    plan = _buscar_plan(plan_id)
    if not plan:
        return jsonify({"error": "No existe ese plan"}), 404
    d = request.get_json(silent=True) or {}

    if "nombre" in d:
        nombre = (d["nombre"] or "").strip()
        if not nombre:
            raise ValueError("El nombre no puede quedar vacío")
        plan.nombre = nombre
    if "grupales_por_semana" in d:
        plan.grupales_por_semana = _entero(d["grupales_por_semana"], "Las clases grupales")
    if "particulares_por_semana" in d:
        plan.particulares_por_semana = _entero(d["particulares_por_semana"], "Las clases particulares")
    if "descripcion" in d:
        plan.descripcion = d["descripcion"] or None
    if "activo" in d:
        plan.activo = bool(d["activo"])
    if plan.grupales_por_semana + plan.particulares_por_semana == 0:
        raise ValueError("El plan tiene que incluir al menos una clase por semana")

    db.session.commit()
    return jsonify(_plan_json(plan))


@planes_bp.get("/api/planes/<int:plan_id>/precios")
@requiere_login("encargado")
def historial_precios(plan_id):
    if not _buscar_plan(plan_id):
        return jsonify({"error": "No existe ese plan"}), 404
    filas = (
        PrecioPlan.query.filter_by(plan_id=plan_id)
        .order_by(PrecioPlan.vigente_desde.desc(), PrecioPlan.id.desc())
        .all()
    )
    return jsonify([
        {"id": f.id, "monto": float(f.monto), "vigente_desde": f.vigente_desde.isoformat()}
        for f in filas
    ])


@planes_bp.post("/api/planes/<int:plan_id>/precios")
@requiere_login("encargado")
@_con_validacion
def cargar_precio(plan_id):
    plan = _buscar_plan(plan_id)
    if not plan:
        return jsonify({"error": "No existe ese plan"}), 404
    d = request.get_json(silent=True) or {}
    monto = _monto(d.get("monto"))
    desde = _fecha(d.get("vigente_desde"), _hoy())
    _guardar_precio(plan.id, monto, desde)
    db.session.commit()
    return jsonify(_plan_json(plan)), 201


@planes_bp.post("/api/planes/aumento")
@requiere_login("encargado")
@_con_validacion
def aumento_masivo():
    """
    Sube (o baja) un porcentaje a todos los planes activos.
    Sin "confirmar": true solo devuelve la vista previa y no guarda nada.
    """
    d = request.get_json(silent=True) or {}
    pct = _decimal(d.get("porcentaje"), "El porcentaje")
    if pct <= -100 or pct > 1000:
        raise ValueError("El porcentaje está fuera de rango")
    paso = _decimal(d.get("redondeo", 100), "El redondeo")
    if paso < 1:
        raise ValueError("El redondeo tiene que ser 1 o más")
    desde = _fecha(d.get("vigente_desde"), _hoy())
    confirmar = bool(d.get("confirmar", False))

    filas, sin_precio = [], []
    for plan in Plan.query.filter_by(activo=True).order_by(Plan.id).all():
        actual = _precio_en(plan.id, desde)
        if not actual:
            sin_precio.append(plan.nombre)
            continue
        crudo = actual.monto * (Decimal(100) + pct) / Decimal(100)
        nuevo = ((crudo / paso).quantize(Decimal(1), rounding=ROUND_HALF_UP) * paso).quantize(Decimal("0.01"))
        filas.append((plan, actual.monto, nuevo))

    if confirmar:
        for plan, _viejo, nuevo in filas:
            _guardar_precio(plan.id, nuevo, desde)
        db.session.commit()

    return jsonify({
        "aplicado": confirmar,
        "vigente_desde": desde.isoformat(),
        "porcentaje": float(pct),
        "redondeo": float(paso),
        "planes": [
            {"id": p.id, "nombre": p.nombre, "precio_actual": float(v), "precio_nuevo": float(n)}
            for p, v, n in filas
        ],
        "sin_precio": sin_precio,
    })