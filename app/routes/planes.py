"""
Planes y precios: la pantalla lee y escribe la tabla de tarifas (la misma que usan las cuotas y el agente).
Una "tarifa" es franja + tipo + personas + veces por semana. Guarda historial: cada cambio es una
fila nueva con la fecha desde la que rige, nunca se pisa el valor anterior.
Plan y PrecioPlan quedan sin uso.
Ver: encargado y dueño. Crear, cargar precios, aumentos, editar y quitar filas: solo el dueño.
Editar o quitar una fila solo si ninguna cuota generada la usó (ver app/tarifas_uso.py).
"""
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps

from flask import Blueprint, g, request, jsonify

from app.extensions import db
from app.models_academia import Auditoria
from app.models_tarifas import FRANJA_HEAD_COACH, FRANJAS, TIPOS_TARIFA, Tarifa
from app.recuperaciones import hoy as _hoy
from app.routes.auth import requiere_login
from app.tarifas_uso import estado_fila

planes_bp = Blueprint("planes", __name__)

# textos para mostrar; el orden de las franjas es el de la pantalla
NOMBRE_FRANJA = {"manana": "Mañana", "tarde": "Tarde", "sabado": "Sábado", "kids": "Kids",
                 FRANJA_HEAD_COACH: "Head Coach"}
NOMBRE_TIPO = {"academia": "Modo Academia", "particular": "Particular", "promo_2x1": "Promo 2x1"}
# franjas que no aceptan todos los tipos (el head coach solo tiene particulares)
TIPOS_POR_FRANJA = {FRANJA_HEAD_COACH: ("particular",)}
PERSONAS_MAX = 3  # 3 = "3 o 4", pagan igual


# ---------- ayudas ----------

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
    if m != m.to_integral_value():
        raise ValueError("El monto va sin centavos")
    return int(m)


def _entero(valor, campo, minimo, maximo):
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{campo} tiene que ser un número entero")
    if n < minimo or n > maximo:
        raise ValueError(f"{campo} tiene que estar entre {minimo} y {maximo}")
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


def _clave(t):
    return (t.franja, t.tipo, t.personas, t.veces_por_semana)


def _filas_de(clave):
    franja, tipo, personas, veces = clave
    return Tarifa.query.filter_by(franja=franja, tipo=tipo, personas=personas, veces_por_semana=veces)


def _guardar_precio(clave, monto, desde):
    """Si ya hay una fila para esa misma fecha la corrige, si no crea una nueva. Las anteriores no se tocan."""
    existente = _filas_de(clave).filter_by(vigente_desde=desde).first()
    if existente:
        existente.precio = monto
        existente.activa = True
        return existente
    franja, tipo, personas, veces = clave
    fila = Tarifa(franja=franja, tipo=tipo, personas=personas, veces_por_semana=veces,
                  precio=monto, vigente_desde=desde, activa=True)
    db.session.add(fila)
    return fila


def _nombre(clave):
    _franja, tipo, personas, veces = clave
    partes = [NOMBRE_TIPO.get(tipo, tipo)]
    if tipo == "particular":
        partes.append({1: "1 persona", 2: "2 personas c/u"}.get(personas, "3 o 4 personas c/u"))
    elif tipo == "promo_2x1":
        partes.append("c/u")
    partes.append("1 vez por semana" if veces == 1 else f"{veces} veces por semana")
    return " · ".join(partes)


def _tarifa_json(clave, hoy, filas=None):
    """filas: todas las de esa clave ordenadas por (vigente_desde, id); si no vienen, se buscan."""
    if filas is None:
        filas = _filas_de(clave).order_by(Tarifa.vigente_desde, Tarifa.id).all()
    pasadas = [f for f in filas if f.vigente_desde <= hoy]
    futuras = [f for f in filas if f.vigente_desde > hoy]
    vigente = pasadas[-1] if pasadas else None
    programado = futuras[0] if futuras else None
    ultima = filas[-1]
    franja, tipo, personas, veces = clave
    activa = bool(vigente and vigente.activa)
    return {
        "id": ultima.id,  # cualquier fila sirve para ubicar la tarifa; uso la última
        "franja": franja,
        "franja_nombre": NOMBRE_FRANJA.get(franja, franja),
        "tipo": tipo,
        "personas": personas,
        "veces_por_semana": veces,
        "nombre": _nombre(clave),
        "activo": activa,
        "precio_vigente": vigente.precio if activa else None,
        "vigente_desde": vigente.vigente_desde.isoformat() if activa else None,
        "precio_programado": (
            {"monto": programado.precio, "desde": programado.vigente_desde.isoformat()}
            if programado and programado.activa else None
        ),
    }


def _orden(clave):
    franja, tipo, personas, veces = clave
    return (FRANJAS.index(franja) if franja in FRANJAS else 99,
            TIPOS_TARIFA.index(tipo) if tipo in TIPOS_TARIFA else 99, personas, veces)


def _fila_dict(t):
    return {"id": t.id, "franja": t.franja, "tipo": t.tipo, "personas": t.personas,
            "veces_por_semana": t.veces_por_semana, "precio": t.precio, "activa": t.activa,
            "vigente_desde": t.vigente_desde.isoformat()}


def _auditar(fila_id, accion, antes=None, despues=None):
    db.session.add(Auditoria(
        entidad="tarifa", entidad_id=fila_id, accion=accion,
        antes=json.dumps(antes, ensure_ascii=False) if antes is not None else None,
        despues=json.dumps(despues, ensure_ascii=False) if despues is not None else None,
        usuario_id=g.usuario.id,
    ))


def _fila_tocable(fila_id):
    """(fila, None) si se puede editar o quitar de verdad; si no, (None, respuesta de error).
    El chequeo se hace acá de nuevo: no se confía en lo que mostró el panel antes."""
    t = db.session.get(Tarifa, fila_id)
    if not t:
        return None, (jsonify({"error": "No existe esa fila de precio"}), 404)
    estado = estado_fila(t, _hoy())
    if not estado["puede_directo"]:
        return None, (jsonify({"error": estado["explicacion"], "chequeo": estado}), 409)
    return t, None


def _buscar(tarifa_id):
    t = db.session.get(Tarifa, tarifa_id)
    return _clave(t) if t else None


# ---------- rutas ----------

@planes_bp.get("/api/planes")
@requiere_login("encargado")
def listar_planes():
    hoy = _hoy()
    por_clave = {}
    for t in Tarifa.query.order_by(Tarifa.vigente_desde, Tarifa.id):  # una sola consulta
        por_clave.setdefault(_clave(t), []).append(t)
    return jsonify({
        "franjas": [{"id": f, "nombre": NOMBRE_FRANJA.get(f, f), "tipos": list(TIPOS_POR_FRANJA.get(f, TIPOS_TARIFA))}
                    for f in FRANJAS],
        "tipos": [{"id": t, "nombre": NOMBRE_TIPO.get(t, t)} for t in TIPOS_TARIFA],
        "tarifas": [_tarifa_json(c, hoy, por_clave[c]) for c in sorted(por_clave, key=_orden)],
    })


@planes_bp.post("/api/planes")
@requiere_login("dueno")
@_con_validacion
def crear_plan():
    """Tarifa nueva. Si esa combinación ya existe, se le carga precio con 'Subir precios' o /precios."""
    d = request.get_json(silent=True) or {}
    franja, tipo = d.get("franja"), d.get("tipo")
    if franja not in FRANJAS:
        raise ValueError("Elegí una franja")
    if tipo not in TIPOS_TARIFA:
        raise ValueError("Elegí un tipo")
    if tipo not in TIPOS_POR_FRANJA.get(franja, TIPOS_TARIFA):
        raise ValueError(f"{NOMBRE_FRANJA[franja]} no tiene {NOMBRE_TIPO[tipo]}")
    if tipo == "particular":
        personas = _entero(d.get("personas"), "Las personas", 1, PERSONAS_MAX)
    else:
        personas = 0  # academia y promo cobran por persona, no por grupo
    veces = _entero(d.get("veces_por_semana"), "Las veces por semana", 1, 7)
    monto = _monto(d.get("precio"))
    desde = _fecha(d.get("vigente_desde"), _hoy())

    clave = (franja, tipo, personas, veces)
    if _filas_de(clave).first():
        return jsonify({"error": f"Ya existe {NOMBRE_FRANJA[franja]}: {_nombre(clave)}. "
                                 "Para cambiarle el precio usá Subir precios."}), 409
    _guardar_precio(clave, monto, desde)
    db.session.commit()
    return jsonify(_tarifa_json(clave, _hoy())), 201


@planes_bp.get("/api/planes/<int:tarifa_id>/precios")
@requiere_login("encargado")
def historial_precios(tarifa_id):
    clave = _buscar(tarifa_id)
    if not clave:
        return jsonify({"error": "No existe esa tarifa"}), 404
    filas = _filas_de(clave).order_by(Tarifa.vigente_desde.desc(), Tarifa.id.desc()).all()
    return jsonify([
        {"id": f.id, "monto": f.precio, "vigente_desde": f.vigente_desde.isoformat(), "activa": f.activa}
        for f in filas
    ])


@planes_bp.get("/api/planes/filas/<int:fila_id>/chequeo")
@requiere_login("dueno")
def chequear_fila(fila_id):
    """Antes de editar o quitar una fila de precio: si se puede de verdad o solo con historial."""
    t = db.session.get(Tarifa, fila_id)
    if not t:
        return jsonify({"error": "No existe esa fila de precio"}), 404
    return jsonify(estado_fila(t, _hoy()))


@planes_bp.patch("/api/planes/filas/<int:fila_id>")
@requiere_login("dueno")
@_con_validacion
def editar_fila(fila_id):
    """Cambia el precio de una fila que ninguna cuota generada usó. Si la usaron: 409 con el motivo."""
    t, error = _fila_tocable(fila_id)
    if error:
        return error
    if not t.activa:
        return jsonify({"error": "Esa fila es una baja, no tiene precio. Si fue un error, quitala."}), 400
    monto = _monto((request.get_json(silent=True) or {}).get("precio"))
    if monto != t.precio:
        antes = _fila_dict(t)
        t.precio = monto
        _auditar(t.id, "editar_precio", antes, _fila_dict(t))
        db.session.commit()
    return jsonify(_tarifa_json(_clave(t), _hoy()))


@planes_bp.delete("/api/planes/filas/<int:fila_id>")
@requiere_login("dueno")
def quitar_fila(fila_id):
    """Borra una fila que ninguna cuota generada usó. Si la usaron: 409 con el motivo."""
    t, error = _fila_tocable(fila_id)
    if error:
        return error
    clave = _clave(t)
    _auditar(t.id, "borrar", _fila_dict(t), None)
    db.session.delete(t)
    db.session.commit()
    # si era la única fila, la tarifa desaparece de la lista
    quedan = _filas_de(clave).count()
    return jsonify({"ok": True, "tarifa": _tarifa_json(clave, _hoy()) if quedan else None})


@planes_bp.post("/api/planes/filas/<int:fila_id>/baja")
@requiere_login("dueno")
@_con_validacion
def dar_de_baja(fila_id):
    """Deja la tarifa de esa fila sin precio desde una fecha (hoy o más adelante), sin tocar lo anterior.
    Es lo que se hace con una fila que ya usó alguna cuota: queda una fila nueva inactiva con su fecha."""
    t = db.session.get(Tarifa, fila_id)
    if not t:
        return jsonify({"error": "No existe esa fila de precio"}), 404
    hoy = _hoy()
    desde = _fecha((request.get_json(silent=True) or {}).get("desde"), hoy)
    if desde < hoy:
        # para atrás cambiaría meses que ya se pudieron cobrar
        raise ValueError("La baja va desde hoy o más adelante, no para atrás")
    clave = _clave(t)
    filas = _filas_de(clave).order_by(Tarifa.vigente_desde, Tarifa.id).all()
    if any(f.vigente_desde == desde for f in filas):
        return jsonify({"error": f"Ya hay un precio cargado para el {desde:%d/%m/%Y}. "
                                 "Editá o quitá esa fila en vez de darla de baja."}), 409
    rige = [f for f in filas if f.vigente_desde <= desde]
    if not rige or not rige[-1].activa:
        raise ValueError(f"Esa tarifa ya está sin precio el {desde:%d/%m/%Y}")
    franja, tipo, personas, veces = clave
    baja = Tarifa(franja=franja, tipo=tipo, personas=personas, veces_por_semana=veces,
                  precio=rige[-1].precio, vigente_desde=desde, activa=False)  # precio: el de antes, solo de referencia
    db.session.add(baja)
    db.session.flush()
    _auditar(baja.id, "baja", None, _fila_dict(baja))
    db.session.commit()
    despues = [f for f in filas if f.vigente_desde > desde]
    aviso = (f"Ojo: el precio cargado para el {despues[0].vigente_desde:%d/%m/%Y} la vuelve a activar."
             if despues and despues[0].activa else "")
    return jsonify({**_tarifa_json(clave, hoy), "aviso": aviso}), 201


@planes_bp.post("/api/planes/<int:tarifa_id>/precios")
@requiere_login("dueno")
@_con_validacion
def cargar_precio(tarifa_id):
    clave = _buscar(tarifa_id)
    if not clave:
        return jsonify({"error": "No existe esa tarifa"}), 404
    d = request.get_json(silent=True) or {}
    monto = _monto(d.get("monto"))
    desde = _fecha(d.get("vigente_desde"), _hoy())
    _guardar_precio(clave, monto, desde)
    db.session.commit()
    return jsonify(_tarifa_json(clave, _hoy())), 201


@planes_bp.post("/api/planes/aumento")
@requiere_login("dueno")
@_con_validacion
def aumento_masivo():
    """
    Sube (o baja) un porcentaje a todas las tarifas que rigen en la fecha elegida.
    Crea filas nuevas con vigente_desde = esa fecha; las anteriores no se tocan.
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
    incluir_kids = d.get("incluir_kids", True) is not False  # kids se cobra aparte: se puede dejar afuera

    rige = {}  # clave -> fila que rige en "desde" (None si todavía no arrancó)
    for t in Tarifa.query.order_by(Tarifa.vigente_desde, Tarifa.id):
        rige.setdefault(_clave(t), None)
        if t.vigente_desde <= desde:
            rige[_clave(t)] = t

    filas, sin_precio = [], []
    for clave in sorted(rige, key=_orden):
        if clave[0] == "kids" and not incluir_kids:
            continue
        actual = rige[clave]
        if not actual or not actual.activa:
            if actual is None:
                sin_precio.append(f"{NOMBRE_FRANJA.get(clave[0], clave[0])}: {_nombre(clave)}")
            continue  # dada de baja: no se aumenta
        crudo = Decimal(actual.precio) * (Decimal(100) + pct) / Decimal(100)
        nuevo = int((crudo / paso).quantize(Decimal(1), rounding=ROUND_HALF_UP) * paso)
        if nuevo <= 0:
            raise ValueError("Con ese porcentaje algún precio queda en cero")
        filas.append((clave, actual.precio, nuevo))

    if confirmar:
        for clave, _viejo, nuevo in filas:
            _guardar_precio(clave, nuevo, desde)
        db.session.commit()

    return jsonify({
        "aplicado": confirmar,
        "vigente_desde": desde.isoformat(),
        "porcentaje": float(pct),
        "redondeo": float(paso),
        "incluir_kids": incluir_kids,
        "planes": [
            {"id": "|".join(map(str, c)), "franja": NOMBRE_FRANJA.get(c[0], c[0]),
             "nombre": _nombre(c), "precio_actual": v, "precio_nuevo": n}
            for c, v, n in filas
        ],
        "sin_precio": sin_precio,
    })
