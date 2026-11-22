"""Alumnos para el panel.
/api/alumnos lee la pestaña "listado alumnos" de la planilla de Gabi (solo lectura).
Las fichas salen de Neon: alumnos con sus teléfonos de contacto, que sí se editan.
"""
import json
import re

from flask import Blueprint, g, jsonify, request

from app import alumnos_alta, alumnos_gestion, cambios_dias, cuotas, niveles, planilla
from app import recuperaciones as rec
from app.contactos import alumnos_de_telefono, tel10
from app.extensions import db
from app.models import PARENTESCOS, Alumno, ContactoAlumno
from app.models_academia import Auditoria, Clase
from app.privacidad import es_dueno
from app.routes.auth import requiere_login
from app.sheets_client import valores_pestana

alumnos_bp = Blueprint("alumnos_panel", __name__)


def _dinero(txt):
    """' $150.000,00' -> 150000. Si no hay número devuelve None."""
    s = str(txt or "").replace(".", "")
    s = re.sub(r"[^\d,]", "", s)
    if not re.search(r"\d", s):
        return None
    n = float(s.replace(",", "."))
    return int(n) if n == int(n) else n


@alumnos_bp.get("/api/alumnos")
@requiere_login("encargado")
def listar():
    # copia de hasta 90 s; "Actualizar" manda fresco=1 y lee la planilla de nuevo
    fresco = request.args.get("fresco") == "1"
    try:
        filas = valores_pestana(planilla.TAB_ALUMNOS, cache=not fresco)
    except Exception as e:
        return jsonify({"error": f"No pude leer la planilla: {e}"}), 502
    if not filas:
        return jsonify([])

    enc = [str(h).strip().upper() for h in filas[0]]

    def col(nombre):
        return enc.index(nombre) if nombre in enc else None

    def val(fila, nombre):
        i = col(nombre)
        return str(fila[i]).strip() if i is not None and i < len(fila) else ""

    dueno = es_dueno()
    salida = []
    for n, fila in enumerate(filas[1:], start=2):
        nombre = val(fila, "NOMBRE")
        if not nombre:
            continue
        meses = {}
        for m in planilla.MESES:
            texto = val(fila, m)
            # celda con algo = pagó (mismo criterio que la fórmula); el monto solo para el dueño
            meses[m] = {"texto": texto, "monto": _dinero(texto)} if dueno else {"pago": bool(texto)}
        salida.append({
            "id": n,
            "numero": val(fila, "N°"),
            "nombre": nombre,
            "edad": val(fila, "EDAD"),
            "cat": val(fila, "CAT"),
            "al_dia": val(fila, "AL DIA"),
            "mes_inicio": val(fila, "MES DE INICIO"),
            "nuevo": val(fila, "NUEVO"),
            "planilla": val(fila, "PLANILLA"),
            "estado": val(fila, "ESTADO"),
            "mes_baja": val(fila, "MES DE BAJA"),
            "motivo": val(fila, "MOTIVO"),
            "meses": meses,
        })
    return jsonify(salida)

# ---------- fichas (alumnos de Neon) y sus contactos ----------

def _max_contactos() -> int:
    """Cuántos teléfonos por alumno, sale de ConfigAcademia (tutores_por_menor). Si no está, 2."""
    return alumnos_alta.max_tutores()


def _tope(alumno: Alumno) -> int:
    """Teléfonos por alumno: los tutores de la config y, en Kids, uno más para el propio del chico."""
    return _max_contactos() + (1 if alumnos_alta.es_menor(alumno.planilla) else 0)


def _contacto_json(c: ContactoAlumno) -> dict:
    return {"id": c.id, "telefono": c.telefono, "parentesco": c.parentesco, "nombre": c.nombre or ""}


def _otros_alumnos(t10: str, alumno_id: int | None) -> list[dict]:
    """Los demás alumnos que ya tienen ese número (hermanos, o un error de carga)."""
    if len(t10) < 10:
        return []
    return [
        {"id": a.id, "nombre": a.nombre}
        for a in alumnos_de_telefono(t10)
        if a.id != alumno_id
    ]


@alumnos_bp.get("/api/alumnos/fichas")
@requiere_login("encargado")
def fichas():
    alumnos = Alumno.query.order_by(Alumno.nombre, Alumno.id).all()
    contactos = {}
    for c in ContactoAlumno.query.order_by(ContactoAlumno.id).all():
        contactos.setdefault(c.alumno_id, []).append(_contacto_json(c))
    nivel_de = niveles.datos_de([a.id for a in alumnos])
    return jsonify({
        "max_contactos": _max_contactos(),
        "parentescos": list(PARENTESCOS),
        "niveles": niveles.niveles(),
        "colores": niveles.colores_panel(),
        # sin head coach en el club la columna no se muestra
        "hay_head_coach": bool(cuotas.profes_head_coach()),
        "alumnos": [
            {
                "id": a.id,
                "nombre": a.nombre,
                "telefono": a.telefono,
                "categoria": a.categoria,
                "nivel_declarado": nivel_de.get(a.id, {}).get("nivel_declarado", ""),
                "clasificar": nivel_de.get(a.id, {}).get("clasificar", False),
                "rama": nivel_de.get(a.id, {}).get("rama", ""),
                "planilla": a.planilla,
                "estado": a.estado or "activo",
                "contactos": contactos.get(a.id, []),
                "max_contactos": _tope(a),
                "tarifa_head_coach": bool(a.tarifa_head_coach),
            }
            for a in alumnos
        ],
    })


def auditar_tarifa_head_coach(alumno_id, antes, despues, usuario_id):
    db.session.add(Auditoria(entidad="alumno", entidad_id=alumno_id, accion="tarifa_head_coach",
                             antes=json.dumps(antes), despues=json.dumps(despues), usuario_id=usuario_id))


@alumnos_bp.post("/api/alumnos/<int:alumno_id>/tarifa-head-coach")
@requiere_login("encargado")
def cambiar_tarifa_head_coach(alumno_id):
    """Casilla Tarifa Head Coach: solo para los nuevos que pidieron con el head coach. Dueño y encargado."""
    alumno = db.session.get(Alumno, alumno_id)
    if not alumno:
        return jsonify({"error": "No encontré el alumno"}), 404
    valor = (request.get_json(silent=True) or {}).get("valor")
    if not isinstance(valor, bool):
        return jsonify({"error": "Falta valor (sí o no)"}), 400
    if alumno.tarifa_head_coach != valor:
        auditar_tarifa_head_coach(alumno.id, bool(alumno.tarifa_head_coach), valor, g.usuario.id)
        alumno.tarifa_head_coach = valor
        db.session.commit()
    return jsonify({"ok": True, "tarifa_head_coach": alumno.tarifa_head_coach})


@alumnos_bp.post("/api/alumnos/<int:alumno_id>/nivel")
@requiere_login("encargado")
def clasificar_nivel(alumno_id):
    """Encargado y dueño: clasificar al nuevo o recategorizar a cualquiera. El profe va por Mis clases."""
    alumno = db.session.get(Alumno, alumno_id)
    if not alumno:
        return jsonify({"error": "No encontré el alumno"}), 404
    datos = request.get_json(silent=True) or {}
    resultado, msg = niveles.clasificar(alumno, datos.get("nivel"), g.usuario.id)
    if msg:
        return jsonify({"error": msg}), 400
    return jsonify({"alumno_id": alumno.id, **resultado})


@alumnos_bp.get("/api/alumnos/contactos/chequear")
@requiere_login("encargado")
def chequear_telefono():
    """Para avisar en el modal mientras se tipea: ¿este número ya es de otro alumno?"""
    alumno_id = request.args.get("alumno_id", type=int)
    t = tel10(request.args.get("telefono", ""))
    return jsonify({"valido": len(t) == 10, "otros": _otros_alumnos(t, alumno_id)})


def _leer_contacto(c, i: int):
    """Valida un contacto que viene del panel. Devuelve (datos, None) o (None, error)."""
    c = c if isinstance(c, dict) else {}
    telefono = str(c.get("telefono", "")).strip()
    parentesco = str(c.get("parentesco", "")).strip().lower()
    nombre = str(c.get("nombre", "")).strip()[:80]
    t = tel10(telefono)
    if len(t) < 10:
        return None, f"El teléfono {i} no tiene 10 números (con característica, sin 0 ni 15)"
    if parentesco not in PARENTESCOS:
        return None, f"Elegí el parentesco del teléfono {i}"
    return (telefono[:20], t, parentesco, nombre), None


def _sincronizar_principal(alumno: Alumno) -> None:
    """Alumno.telefono = el primer contacto que queda, o vacío si no queda ninguno.
    Así no hay un número reconociendo al alumno que no se vea en la ficha."""
    primero = (ContactoAlumno.query.filter_by(alumno_id=alumno.id)
               .order_by(ContactoAlumno.id).first())
    alumno.telefono = primero.telefono if primero else ""


def _respuesta_contactos(alumno: Alumno, tels: list[tuple[str, str]], status=200):
    """Contactos guardados del alumno + avisos de números que ya son de otro alumno."""
    avisos = []
    for telefono, t in tels:
        otros = _otros_alumnos(t, alumno.id)
        if otros:
            avisos.append({"telefono": telefono, "otros": otros})
    guardados = ContactoAlumno.query.filter_by(alumno_id=alumno.id).order_by(ContactoAlumno.id).all()
    return jsonify({"ok": True, "contactos": [_contacto_json(c) for c in guardados],
                    "max_contactos": _tope(alumno), "avisos": avisos}), status


@alumnos_bp.get("/api/alumnos/<int:alumno_id>/contactos")
@requiere_login("encargado")
def ver_contactos(alumno_id):
    alumno = db.session.get(Alumno, alumno_id)
    if not alumno:
        return jsonify({"error": "No encontré ese alumno"}), 404
    return _respuesta_contactos(alumno, [])


@alumnos_bp.post("/api/alumnos/<int:alumno_id>/contactos")
@requiere_login("encargado")
def sumar_contacto(alumno_id):
    """Agrega un teléfono. Si ya es de otro alumno se guarda igual (hermanos), solo avisa."""
    alumno = db.session.get(Alumno, alumno_id)
    if not alumno:
        return jsonify({"error": "No encontré ese alumno"}), 404
    tope = _tope(alumno)
    actuales = ContactoAlumno.query.filter_by(alumno_id=alumno.id).all()
    if len(actuales) >= tope:
        return jsonify({"error": f"Como mucho {tope} teléfonos por alumno"}), 400
    datos, error = _leer_contacto(request.get_json(silent=True), len(actuales) + 1)
    if error:
        return jsonify({"error": error}), 400
    telefono, t, parentesco, nombre = datos
    if any(c.tel10 == t for c in actuales):
        return jsonify({"error": "Ese teléfono ya está cargado en este alumno"}), 400
    db.session.add(ContactoAlumno(alumno_id=alumno.id, telefono=telefono, tel10=t,
                                  parentesco=parentesco, nombre=nombre or None))
    db.session.flush()
    _sincronizar_principal(alumno)
    db.session.commit()
    return _respuesta_contactos(alumno, [(telefono, t)], 201)


@alumnos_bp.delete("/api/alumnos/<int:alumno_id>/contactos/<int:contacto_id>")
@requiere_login("encargado")
def sacar_contacto(alumno_id, contacto_id):
    alumno = db.session.get(Alumno, alumno_id)
    contacto = db.session.get(ContactoAlumno, contacto_id)
    if not alumno or not contacto or contacto.alumno_id != alumno.id:
        return jsonify({"error": "No encontré ese contacto"}), 404
    db.session.delete(contacto)
    db.session.flush()
    _sincronizar_principal(alumno)
    db.session.commit()
    return _respuesta_contactos(alumno, [])


@alumnos_bp.put("/api/alumnos/<int:alumno_id>/contactos")
@requiere_login("encargado")
def guardar_contactos(alumno_id):
    """Lo usa el modal: reemplaza todos los contactos de una, así no queda a medias.
    Si un número ya es de otro alumno se deja igual (pueden ser hermanos), solo se avisa."""
    alumno = db.session.get(Alumno, alumno_id)
    if not alumno:
        return jsonify({"error": "No encontré ese alumno"}), 404

    cuerpo = request.get_json(silent=True) or {}
    lista = cuerpo.get("contactos")
    if not isinstance(lista, list):
        return jsonify({"error": "Faltan los contactos"}), 400
    tope = _tope(alumno)
    if len(lista) > tope:
        return jsonify({"error": f"Como mucho {tope} teléfonos por alumno"}), 400

    nuevos, vistos = [], set()
    for i, c in enumerate(lista, start=1):
        datos, error = _leer_contacto(c, i)
        if error:
            return jsonify({"error": error}), 400
        if datos[1] in vistos:
            return jsonify({"error": "Pusiste el mismo teléfono dos veces"}), 400
        vistos.add(datos[1])
        nuevos.append(datos)

    # piso todo: es más simple que comparar uno por uno y son 2 filas como mucho
    ContactoAlumno.query.filter_by(alumno_id=alumno.id).delete()
    db.session.flush()
    for telefono, t, parentesco, nombre in nuevos:
        db.session.add(ContactoAlumno(alumno_id=alumno.id, telefono=telefono, tel10=t,
                                      parentesco=parentesco, nombre=nombre or None))
    db.session.flush()
    _sincronizar_principal(alumno)
    db.session.commit()
    return _respuesta_contactos(alumno, [(n[0], n[1]) for n in nuevos])


# ---------- alta de alumnos (dueño y encargado; el profe no) ----------

@alumnos_bp.get("/api/alumnos/alta/opciones")
@requiere_login("encargado")
def opciones_alta():
    """Lo que necesita el formulario. El monto de la inscripción solo lo ve el dueño (igual que en Cuotas)."""
    monto = rec.regla("inscripcion")
    try:
        monto = int(monto)
    except (TypeError, ValueError):
        monto = 0
    inscripcion = {"configurada": monto > 0}
    if es_dueno() and monto > 0:
        inscripcion["monto"] = monto  # el encargado ni la clave: la prueba de humo lo cuenta como plata
    return jsonify({
        "planillas": list(alumnos_alta.PLANILLAS_ALTA),
        "planillas_menores": list(alumnos_alta.PLANILLAS_MENORES),
        "parentescos": list(alumnos_alta.PARENTESCOS_TUTOR),
        "max_tutores": alumnos_alta.max_tutores(),
        "niveles": niveles.niveles(),
        "hay_head_coach": bool(cuotas.profes_head_coach()),
        "inscripcion": inscripcion,
    })


def _telefonos_del_cuerpo(d) -> list[str]:
    tels = [d.get("telefono")] + [c.get("telefono") for c in (d.get("contactos") or []) if isinstance(c, dict)]
    return [t for t in tels if t]


@alumnos_bp.post("/api/alumnos/alta/chequear")
@requiere_login("encargado")
def chequear_alta():
    """Mientras se completa el formulario: parecidos por teléfono o nombre (no guarda nada)."""
    d = request.get_json(silent=True) or {}
    tels = _telefonos_del_cuerpo(d)
    invalidos = [t for t in tels if not alumnos_alta.normalizar_telefono(t)]
    # editando: solo avisa por lo nuevo (no por sus propios teléfonos ni su nombre de siempre)
    alumno = db.session.get(Alumno, d["alumno_id"]) if isinstance(d.get("alumno_id"), int) else None
    if alumno:
        lista = alumnos_gestion.parecidos_edicion(alumno, d.get("nombre"),
                                                  [alumnos_alta.normalizar_telefono(t) for t in tels])
    else:
        lista = alumnos_alta.parecidos(d.get("nombre"), tels)
    return jsonify({"parecidos": lista, "invalidos": invalidos})


@alumnos_bp.post("/api/alumnos")
@requiere_login("encargado")
def crear_alumno():
    """Alta desde el panel. Si hay parecidos y no vino confirmar, 409 con la lista para que lo confirme."""
    d = request.get_json(silent=True) or {}
    try:
        alumno, confirmados = alumnos_alta.crear_alumno(
            d.get("nombre"), d.get("planilla"), nivel=d.get("nivel") or None,
            telefono=d.get("telefono") or None, contactos=d.get("contactos") or [],
            tarifa_head_coach=d.get("tarifa_head_coach", False),
            inscripcion=d.get("inscripcion") or "cobrar",
            usuario_id=g.usuario.id, origen="panel", confirmar_parecidos=d.get("confirmar") is True,
        )
    except alumnos_alta.ErrorAlta as e:
        db.session.rollback()
        parecidos = getattr(e, "parecidos", None)
        if parecidos:
            return jsonify({"error": str(e), "parecidos": parecidos, "confirmar": True}), 409
        return jsonify({"error": str(e)}), 400
    db.session.commit()
    contactos = ContactoAlumno.query.filter_by(alumno_id=alumno.id).order_by(ContactoAlumno.id).all()
    return jsonify({
        "alumno": {"id": alumno.id, "nombre": alumno.nombre, "planilla": alumno.planilla,
                   "categoria": alumno.categoria, "telefono": alumno.telefono,
                   "tarifa_head_coach": bool(alumno.tarifa_head_coach),
                   "contactos": [_contacto_json(c) for c in contactos]},
        "parecidos_confirmados": [p["id"] for p in confirmados],
    }), 201


@alumnos_bp.post("/api/alumnos/<int:alumno_id>/cotizar")
@requiere_login("encargado")
def cotizar(alumno_id):
    """Cuota del mes en vivo con las clases que se van eligiendo (más las que ya tiene).
    No guarda nada. Son los precios de los planes (los del flyer), que el encargado sí ve.
    Sin tarifa exacta, precio vacío: nunca se inventa."""
    alumno = db.session.get(Alumno, alumno_id)
    if not alumno:
        return jsonify({"error": "No encontré el alumno"}), 404
    try:
        ids = [int(x) for x in ((request.get_json(silent=True) or {}).get("clase_ids") or [])]
    except (TypeError, ValueError):
        return jsonify({"error": "Las clases tienen que ser ids"}), 400
    hoy = rec.hoy()
    elegidas = Clase.query.filter(Clase.id.in_(ids), Clase.activa.is_(True)).all() if ids else []
    if any(c.apoyo_de_clase_id for c in elegidas):
        return jsonify({"error": "Una de las clases es fila de apoyo: elegí la titular"}), 400
    ya = cambios_dias.clases_del_alumno(alumno.id, hoy)
    todas = ya + [c for c in elegidas if c not in ya]
    precio, detalle = cambios_dias.precio_de(todas, hoy, tarifa_head_coach=bool(alumno.tarifa_head_coach))
    return jsonify({"mes": hoy.strftime("%Y-%m"), "precio": precio,
                    "detalle": detalle if precio is not None else "",
                    "sin_tarifa": bool(todas) and precio is None,
                    "clases": len(todas)})


# ---------- editar, dar de baja, reactivar y borrar (dueño y encargado; el profe no) ----------

def _alumno_o_404(alumno_id):
    alumno = db.session.get(Alumno, alumno_id)
    return alumno, (None if alumno else (jsonify({"error": "No encontré el alumno"}), 404))


def _error_gestion(e):
    db.session.rollback()
    parecidos = getattr(e, "parecidos", None)
    if parecidos:
        return jsonify({"error": str(e), "parecidos": parecidos, "confirmar": True}), 409
    return jsonify({"error": str(e)}), 400


@alumnos_bp.get("/api/alumnos/<int:alumno_id>/gestion")
@requiere_login("encargado")
def gestion(alumno_id):
    """Para el modal de la ficha: qué cierra la baja y por qué no se puede borrar (si no se puede)."""
    alumno, error = _alumno_o_404(alumno_id)
    if error:
        return error
    no_borrar = alumnos_gestion.motivos_para_no_borrar(alumno)
    return jsonify({
        "id": alumno.id, "nombre": alumno.nombre, "estado": alumno.estado or "activo",
        "motivo_baja": alumno.motivo_baja, "motivos_baja": list(alumnos_gestion.MOTIVOS_BAJA),
        "baja": alumnos_gestion.resumen_baja(alumno),
        "puede_borrar": not no_borrar, "no_borrar": no_borrar,
    })


@alumnos_bp.patch("/api/alumnos/<int:alumno_id>")
@requiere_login("encargado")
def editar_alumno(alumno_id):
    alumno, error = _alumno_o_404(alumno_id)
    if error:
        return error
    d = request.get_json(silent=True) or {}
    try:
        cambios, confirmados = alumnos_gestion.editar_alumno(
            alumno, d.get("nombre"), d.get("planilla"), d.get("nivel") or None, d.get("telefono") or None,
            d.get("contactos") or [], g.usuario.id, confirmar_parecidos=d.get("confirmar") is True)
    except alumnos_alta.ErrorAlta as e:
        return _error_gestion(e)
    db.session.commit()
    return jsonify({"ok": True, "cambios": sorted(cambios), "parecidos_confirmados": [p["id"] for p in confirmados]})


@alumnos_bp.post("/api/alumnos/<int:alumno_id>/baja")
@requiere_login("encargado")
def dar_de_baja(alumno_id):
    alumno, error = _alumno_o_404(alumno_id)
    if error:
        return error
    try:
        r = alumnos_gestion.dar_de_baja(alumno, g.usuario.id, (request.get_json(silent=True) or {}).get("motivo"))
    except alumnos_alta.ErrorAlta as e:
        return _error_gestion(e)
    db.session.commit()
    return jsonify({"ok": True, "estado": "baja", **r})


@alumnos_bp.post("/api/alumnos/<int:alumno_id>/reactivar")
@requiere_login("encargado")
def reactivar(alumno_id):
    alumno, error = _alumno_o_404(alumno_id)
    if error:
        return error
    try:
        alumnos_gestion.reactivar(alumno, g.usuario.id)
    except alumnos_alta.ErrorAlta as e:
        return _error_gestion(e)
    db.session.commit()
    return jsonify({"ok": True, "estado": "activo"})


@alumnos_bp.delete("/api/alumnos/<int:alumno_id>")
@requiere_login("encargado")
def borrar(alumno_id):
    """Solo sin historia. Pide el nombre escrito o la casilla "entiendo que no se puede deshacer"."""
    alumno, error = _alumno_o_404(alumno_id)
    if error:
        return error
    d = request.get_json(silent=True) or {}
    confirmacion = True if d.get("entiendo") is True else d.get("nombre")
    nombre = alumno.nombre
    try:
        alumnos_gestion.borrar_alumno(alumno, g.usuario.id, confirmacion)
    except alumnos_alta.ErrorAlta as e:
        return _error_gestion(e)
    db.session.commit()
    return jsonify({"ok": True, "id": alumno_id, "nombre": nombre})
