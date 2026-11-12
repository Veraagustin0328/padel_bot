"""Alumnos para el panel.
/api/alumnos lee la pestaña "listado alumnos" de la planilla de Gabi (solo lectura).
Las fichas salen de Neon: alumnos con sus teléfonos de contacto, que sí se editan.
"""
import json
import re

from flask import Blueprint, g, jsonify, request

from app import niveles, planilla
from app.contactos import alumnos_de_telefono, tel10
from app.extensions import db
from app.models import PARENTESCOS, Alumno, ContactoAlumno
from app.models_academia import ConfigAcademia
from app.routes.auth import requiere_login
from app.sheets_client import pestana

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
    try:
        filas = pestana(planilla.TAB_ALUMNOS).get_all_values()
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

    salida = []
    for n, fila in enumerate(filas[1:], start=2):
        nombre = val(fila, "NOMBRE")
        if not nombre:
            continue
        meses = {}
        for m in planilla.MESES:
            texto = val(fila, m)
            meses[m] = {"texto": texto, "monto": _dinero(texto)}
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
    cfg = db.session.get(ConfigAcademia, "tutores_por_menor")
    try:
        n = int(json.loads(cfg.valor)) if cfg else 2
    except (TypeError, ValueError):
        n = 2
    return max(n, 1)


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
        "colores_nivel": niveles.colores(),
        "alumnos": [
            {
                "id": a.id,
                "nombre": a.nombre,
                "telefono": a.telefono,
                "categoria": a.categoria,
                "nivel_declarado": nivel_de.get(a.id, {}).get("nivel_declarado", ""),
                "clasificar": nivel_de.get(a.id, {}).get("clasificar", False),
                "planilla": a.planilla,
                "estado": a.estado or "activo",
                "contactos": contactos.get(a.id, []),
            }
            for a in alumnos
        ],
    })


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
                    "max_contactos": _max_contactos(), "avisos": avisos}), status


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
    tope = _max_contactos()
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
    tope = _max_contactos()
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
