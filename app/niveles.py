"""Nivel de juego del alumno.

El alumno nuevo declara su nivel por WhatsApp y queda "a clasificar" hasta que un profe,
el encargado o el dueño le pone el real desde el panel. Ese mismo cambio sirve después
para recategorizar a cualquiera. Todo queda en Auditoria.

Pendiente de clasificar = tiene perfil con nivel_declarado y sin nivel_confirmado.
Los alumnos viejos no tienen perfil, así que no quedan marcados.
"""
import json
import unicodedata
from datetime import datetime

from app.extensions import db
from app.models import Alumno
from app.models_academia import AlumnoPerfil, Auditoria, ConfigAcademia

# todas las formas que aceptamos de cada nivel (1ra y 1era son lo mismo).
# Sirven para reconocer lo que escriben; el nombre que se guarda sale de la config.
FORMAS = [
    ["1era", "1ra", "1°", "primera", "1"],
    ["2da", "2a", "2°", "segunda", "2"],
    ["3ra", "3era", "3°", "tercera", "3"],
    ["4ta", "4°", "cuarta", "4"],
    ["5ta", "5°", "quinta", "5"],
    ["6ta", "6°", "sexta", "6"],
    ["7ma", "7°", "septima", "7"],
    ["8va", "8°", "octava", "8"],
    ["principiante", "principiantes", "inicial"],
]
# si el club no cargó 'orden_niveles': mismo formato que las clases, de menor a mayor
NIVELES_DEFAULT = ["PRINCIPIANTES", "8VA", "7MA", "6TA", "5TA", "4TA", "3RA", "2DA", "1ERA"]


def _clave(texto) -> str:
    """Para comparar: minúsculas, sin tildes ni espacios."""
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.lower().replace(" ", "").strip()


def nivel_canonico(texto) -> str | None:
    """'6ta', 'sexta', '6TA' -> '6TA' (tal cual está en orden_niveles). Si no es un nivel, None."""
    t = _clave(texto)
    if not t:
        return None
    lista = niveles()
    for n in lista:
        if _clave(n) == t:
            return n
    grupo = next((formas for formas in FORMAS if t in formas), None)
    if grupo:
        for n in lista:
            if _clave(n) in grupo:
                return n
    return None


def _config(clave):
    fila = db.session.get(ConfigAcademia, clave)
    if not fila:
        return None
    try:
        return json.loads(fila.valor)
    except (TypeError, ValueError):
        return None


def niveles() -> list[str]:
    """Los niveles del selector, con el formato y el orden de config_academia 'orden_niveles'."""
    lista = _config("orden_niveles")
    if isinstance(lista, list):
        limpios = [str(n).strip() for n in lista if str(n).strip()]
        if limpios:
            return limpios
    return list(NIVELES_DEFAULT)


def colores() -> dict:
    valor = _config("colores_nivel")
    return valor if isinstance(valor, dict) else {}


def _perfil(alumno_id: int, crear=False) -> AlumnoPerfil | None:
    perfil = db.session.get(AlumnoPerfil, alumno_id)
    if not perfil and crear:
        perfil = AlumnoPerfil(alumno_id=alumno_id, es_menor=False)
        db.session.add(perfil)
    return perfil


def registrar_declarado(alumno: Alumno, nivel: str) -> None:
    """Alumno nuevo: lo que dijo va a categoría y a nivel_declarado, y queda a clasificar.
    No hace commit: lo hace el que llama, junto con el alta."""
    nivel = nivel_canonico(nivel) or nivel  # mismo formato que las clases ("6TA")
    alumno.categoria = nivel
    perfil = _perfil(alumno.id, crear=True)
    perfil.nivel_declarado = nivel
    perfil.nivel_confirmado = None
    perfil.nivel_confirmado_por = None
    perfil.nivel_confirmado_en = None


def clasificar(alumno: Alumno, nivel, usuario_id: int | None,
               origen: str = "panel") -> tuple[dict | None, str | None]:
    """Pone el nivel real (clasificar al nuevo o recategorizar a cualquiera).
    origen: panel o whatsapp (el encargado por el agente no tiene usuario del panel).
    Devuelve (datos, None) o (None, error). Hace commit."""
    nuevo = nivel_canonico(nivel)
    if not nuevo or nuevo not in niveles():
        return None, "Ese nivel no existe"
    perfil = _perfil(alumno.id, crear=True)
    antes = {"categoria": alumno.categoria, "nivel_confirmado": perfil.nivel_confirmado}
    era_pendiente = bool(perfil.nivel_declarado) and not perfil.nivel_confirmado

    alumno.categoria = nuevo
    perfil.nivel_confirmado = nuevo
    perfil.nivel_confirmado_por = usuario_id
    perfil.nivel_confirmado_en = datetime.utcnow()
    db.session.add(Auditoria(
        entidad="alumno",
        entidad_id=alumno.id,
        accion="clasificar_nivel" if era_pendiente else "cambiar_nivel",
        antes=json.dumps(antes, ensure_ascii=False),
        despues=json.dumps({"categoria": nuevo, "nivel_declarado": perfil.nivel_declarado,
                            "origen": origen}, ensure_ascii=False),
        usuario_id=usuario_id,
    ))
    db.session.commit()
    return datos_de([alumno.id])[alumno.id], None


def datos_de(alumno_ids) -> dict[int, dict]:
    """Para el panel: {alumno_id: {nivel, nivel_declarado, clasificar}} en dos consultas."""
    ids = list({i for i in alumno_ids if i})
    if not ids:
        return {}
    categorias = dict(db.session.query(Alumno.id, Alumno.categoria).filter(Alumno.id.in_(ids)).all())
    perfiles = {p.alumno_id: p for p in AlumnoPerfil.query.filter(AlumnoPerfil.alumno_id.in_(ids))}
    salida = {}
    for aid in ids:
        p = perfiles.get(aid)
        cat = categorias.get(aid) or ""
        declarado = (p.nivel_declarado or "") if p else ""
        salida[aid] = {
            # por si quedó alguno viejo en minúscula, el panel siempre lo ve como la config
            "nivel": nivel_canonico(cat) or cat,
            "nivel_declarado": nivel_canonico(declarado) or declarado,
            "clasificar": bool(p and p.nivel_declarado and not p.nivel_confirmado),
        }
    return salida
