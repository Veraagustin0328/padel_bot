"""Alta de alumnos: una sola puerta para el panel y, más adelante, el importador de Kids y el agente.

crear_alumno() valida, arma el alumno con sus contactos y su nivel, deja la inscripción
marcada (cobrada o "ya estaba") y audita quién lo creó. El commit lo hace quien llama,
así un importador puede cargar varios en una sola transacción.
parecidos() busca posibles duplicados (mismo teléfono o nombre muy parecido) para avisar antes.
Sin teléfono: solo el panel (dueño/encargado) y el script de carga pueden dar de alta así
(sin_telefono_ok=True). Queda Alumno.telefono = "" y sin contactos: no se vincula ni le escribe nadie.
Sin categoría (adultos): lo mismo, solo panel y script de carga (sin_categoria_ok=True). Queda
Alumno.categoria = "" (igual que un chico sin nivel) hasta que gestión la complete en Fichas.
"""
import json
import re
from difflib import SequenceMatcher

from app import niveles, planilla
from app import recuperaciones as rec
from app.contactos import alumnos_de_telefono, tel10
from app.extensions import db
from app.models import PARENTESCOS, Alumno, ContactoAlumno
from app.models_academia import AlumnoPerfil, Auditoria, ConfigAcademia
from app.models_cuotas import CuotaMes

# planillas que se pueden elegir en el alta (Kids Pro se arma desde las clases, no acá)
PLANILLAS_ALTA = ("adultos", "kids")
PLANILLAS_MENORES = ("kids", "kids_pro")
PARENTESCOS_TUTOR = tuple(p for p in PARENTESCOS if p != "propio")
# inscripción en el alta: cobrar = cargo con el monto de la config; ya_estaba = marca en $0
INSCRIPCION = ("cobrar", "ya_estaba")
NOMBRE_MAX = 120
PARECIDO_MINIMO = 0.86  # SequenceMatcher entre nombres normalizados


class ErrorAlta(ValueError):
    """No se puede dar de alta así: el panel muestra el mensaje."""


def es_menor(planilla_txt) -> bool:
    return str(planilla_txt or "").lower() in PLANILLAS_MENORES


def max_tutores() -> int:
    """Cuántos padres/madres/tutores por chico (config tutores_por_menor). Si no está, 2."""
    cfg = db.session.get(ConfigAcademia, "tutores_por_menor")
    try:
        n = int(json.loads(cfg.valor)) if cfg else 2
    except (TypeError, ValueError):
        n = 2
    return max(n, 1)


def normalizar_telefono(texto) -> str | None:
    """Al formato del agente (el que manda WhatsApp): 549 + característica + número, 13 dígitos.
    Acepta 2614567890, 0261 4567890, +54 9 261 456-7890, 54 261 4567890. None si no sirve.
    El 15 no se adivina: se pide sin 15."""
    d = re.sub(r"\D", "", str(texto or ""))
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 13 and d.startswith("549"):
        return d
    if len(d) == 12 and d.startswith("54"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    # las características de Argentina arrancan con 1, 2 o 3 (11, 261, 341...)
    if len(d) == 10 and d[0] in "123":
        return "549" + d
    return None


def _norm_nombre(nombre) -> str:
    return re.sub(r"[^a-z ]", "", planilla._norm(nombre)).strip()


def _palabras(nombre) -> list[str]:
    return [p for p in _norm_nombre(nombre).split() if len(p) >= 2]


def nombres_parecidos(a, b) -> bool:
    """Mismo nombre escrito distinto: tildes, orden, un segundo nombre de más o un error de tipeo."""
    na, nb = _norm_nombre(a), _norm_nombre(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    pa, pb = _palabras(a), _palabras(b)
    if sorted(pa) == sorted(pb):
        return True  # "Perez Juan" y "Juan Perez"
    corto, largo = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    if len(corto) >= 2 and all(any(w == x or (len(w) >= 4 and x.startswith(w)) for x in largo) for w in corto):
        return True  # "Juan Perez" y "Juan Ignacio Perez"
    return SequenceMatcher(None, na, nb).ratio() >= PARECIDO_MINIMO


def parecidos(nombre, telefonos=(), excluir_id=None) -> list[dict]:
    """Alumnos que podrían ser el mismo: comparten un teléfono o tienen un nombre muy parecido.
    Cada uno con sus motivos. Los hermanos comparten el teléfono de los papás: se avisa, no se frena."""
    salida = {}

    def sumar(a, motivo):
        if a.id == excluir_id:
            return
        item = salida.setdefault(a.id, {"id": a.id, "nombre": a.nombre, "planilla": a.planilla or "",
                                        "estado": a.estado or "activo", "motivos": []})
        if motivo not in item["motivos"]:
            item["motivos"].append(motivo)

    for t in {tel10(x) for x in telefonos if x}:
        if len(t) == 10:
            for a in alumnos_de_telefono(t):
                sumar(a, "mismo_telefono")
    if _norm_nombre(nombre):
        for a in Alumno.query.with_entities(Alumno.id, Alumno.nombre, Alumno.planilla, Alumno.estado).all():
            if nombres_parecidos(nombre, a.nombre):
                sumar(a, "nombre_parecido")
    # primero los que coinciden en las dos cosas
    return sorted(salida.values(), key=lambda x: (-len(x["motivos"]), x["nombre"].lower()))


def parecidos_sin_telefono(nombre) -> list[Alumno]:
    """Alumnos cargados sin ningún teléfono con un nombre muy parecido (para el agente:
    si escribe uno de estos, no se lo da de alta de nuevo ni se lo vincula solo)."""
    from app.contactos import tiene_telefono
    ids = [p["id"] for p in parecidos(nombre)]
    if not ids:
        return []
    return [a for a in Alumno.query.filter(Alumno.id.in_(ids)).order_by(Alumno.nombre) if not tiene_telefono(a)]


def _leer_contactos(planilla_txt, telefono, contactos, tutores_en_adultos=False,
                    sin_telefono_ok=False) -> list[tuple[str, str, str | None]]:
    """[(telefono 549..., parentesco, nombre)] validados, el propio primero.
    tutores_en_adultos: al editar se dejan los que ya tenía un adulto (cargados antes del alta del panel).
    sin_telefono_ok: deja la lista vacía (panel y script de carga; el agente y el registro no)."""
    salida = []
    if telefono not in (None, ""):
        t = normalizar_telefono(telefono)
        if not t:
            raise ErrorAlta("El teléfono del alumno no es válido: poné característica y número, sin 0 ni 15 (ej. 2614567890)")
        salida.append((t, "propio", None))
    lista = contactos or []
    if not isinstance(lista, list):
        raise ErrorAlta("Los contactos vinieron mal")
    lista = [c for c in lista if isinstance(c, dict) and any(str(c.get(k) or "").strip() for k in ("telefono", "nombre"))]
    if lista and not es_menor(planilla_txt) and not tutores_en_adultos:
        raise ErrorAlta("Los contactos de padre, madre o tutor son solo para Kids")
    tope = max_tutores()
    if len(lista) > tope:
        raise ErrorAlta(f"Como mucho {tope} contactos de padre, madre o tutor")
    for i, c in enumerate(lista, start=1):
        if not str(c.get("telefono") or "").strip():
            raise ErrorAlta(f"Al contacto {i} le falta el teléfono: ponelo o sacá ese contacto")
        t = normalizar_telefono(c.get("telefono"))
        if not t:
            raise ErrorAlta(f"El teléfono del contacto {i} no es válido: característica y número, sin 0 ni 15")
        parentesco = str(c.get("parentesco") or "").strip().lower()
        if parentesco not in PARENTESCOS_TUTOR:
            raise ErrorAlta(f"Elegí el parentesco del contacto {i} (padre, madre o tutor)")
        nombre = str(c.get("nombre") or "").strip()[:80] or None
        salida.append((t, parentesco, nombre))
    vistos = set()
    for t, _, _ in salida:
        if t in vistos:
            raise ErrorAlta("Pusiste el mismo teléfono dos veces")
        vistos.add(t)
    if not salida and not sin_telefono_ok:
        raise ErrorAlta("Poné el teléfono del alumno" if not es_menor(planilla_txt)
                        else "Poné al menos un teléfono: el del chico o el de un padre, madre o tutor")
    return salida


def _marcar_inscripcion(alumno, modo, usuario_id):
    """Así en Cuotas no le sale "Agregar inscripción": la inscripción ya queda cargada este mes.
    cobrar: con el monto de la config (el mismo del agente). ya_estaba: en $0, no suma deuda."""
    mes = rec.hoy().replace(day=1)
    if modo == "cobrar":
        try:
            monto = int(rec.regla("inscripcion"))
        except (TypeError, ValueError):
            monto = 0
        if monto <= 0:
            raise ErrorAlta("No está cargado el monto de la inscripción en la configuración: "
                            "elegí \"Ya estaba inscripto\" o avisale al dueño")
        db.session.add(CuotaMes(alumno_id=alumno.id, mes=mes, concepto="inscripcion", monto=monto,
                                monto_calculado=monto, detalle="Inscripción (pago único, de la configuración)"))
    else:
        db.session.add(CuotaMes(alumno_id=alumno.id, mes=mes, concepto="inscripcion", monto=0, monto_calculado=0,
                                nota="Ya estaba inscripto (no se cobra)", detalle="Inscripción marcada en el alta"))


def crear_alumno(nombre, planilla_txt, nivel=None, telefono=None, contactos=None, tarifa_head_coach=False,
                 inscripcion="cobrar", usuario_id=None, origen="panel", confirmar_parecidos=False,
                 sin_telefono_ok=False, sin_categoria_ok=False) -> tuple[Alumno, list]:
    """Da de alta un alumno. Devuelve (alumno, parecidos que se confirmaron).
    - nivel: el que dice el alumno o el encargado; queda "a clasificar" hasta que lo confirme un profe.
      En adultos es obligatorio salvo sin_categoria_ok (panel y script de carga); en Kids puede ir vacío.
    - telefono: el propio. contactos: solo Kids, [{telefono, parentesco, nombre}] de padre/madre/tutor.
    - sin_telefono_ok: se puede dar de alta sin ningún teléfono (solo panel y script de carga).
      Sin teléfono los parecidos van solo por nombre.
    - inscripcion: cobrar / ya_estaba / None (no la toca: para quien la maneje aparte).
    - Si hay parecidos y no se confirmó, ErrorAlta con .parecidos (el panel los muestra y pide confirmar).
    No hace commit."""
    nombre = re.sub(r"\s+", " ", str(nombre or "")).strip()
    if len(nombre) < 3 or len(nombre) > NOMBRE_MAX or not re.search(r"[^\W\d_]", nombre):
        raise ErrorAlta(f"Poné nombre y apellido (hasta {NOMBRE_MAX} letras)")
    planilla_txt = str(planilla_txt or "").strip().lower()
    if planilla_txt not in PLANILLAS_ALTA:
        raise ErrorAlta("Elegí la planilla: " + " o ".join(PLANILLAS_ALTA))
    nivel_ok = niveles.nivel_canonico(nivel) if nivel else None
    if nivel and (not nivel_ok or nivel_ok not in niveles.niveles()):
        raise ErrorAlta("Ese nivel no existe")
    if not nivel_ok and not es_menor(planilla_txt) and not sin_categoria_ok:
        raise ErrorAlta("Elegí el nivel (categoría)")
    if inscripcion is not None and inscripcion not in INSCRIPCION:
        raise ErrorAlta("Elegí qué pasa con la inscripción")
    if not isinstance(tarifa_head_coach, bool):
        raise ErrorAlta("Tarifa Head Coach tiene que ser sí o no")
    tels = _leer_contactos(planilla_txt, telefono, contactos, sin_telefono_ok=sin_telefono_ok)

    dudosos = parecidos(nombre, [t for t, _, _ in tels])
    if dudosos and not confirmar_parecidos:
        e = ErrorAlta("Hay alumnos parecidos: fijate que no esté cargado")
        e.parecidos = dudosos
        raise e

    alumno = Alumno(nombre=nombre, telefono=tels[0][0] if tels else "", categoria=nivel_ok or "", planilla=planilla_txt,
                    estado="activo", tarifa_head_coach=tarifa_head_coach)
    db.session.add(alumno)
    db.session.flush()
    for t, parentesco, nom in tels:
        db.session.add(ContactoAlumno(alumno_id=alumno.id, telefono=t, tel10=tel10(t),
                                      parentesco=parentesco, nombre=nom))
    if nivel_ok:
        niveles.registrar_declarado(alumno, nivel_ok)  # crea el perfil, queda a clasificar
    perfil = db.session.get(AlumnoPerfil, alumno.id)
    if not perfil:
        perfil = AlumnoPerfil(alumno_id=alumno.id)
        db.session.add(perfil)
    perfil.es_menor = es_menor(planilla_txt)
    if inscripcion is not None:
        _marcar_inscripcion(alumno, inscripcion, usuario_id)
    db.session.add(Auditoria(
        entidad="alumno", entidad_id=alumno.id, accion="alta", usuario_id=usuario_id,
        despues=json.dumps({
            "nombre": nombre, "planilla": planilla_txt, "nivel": nivel_ok, "origen": origen,
            "contactos": [{"telefono": t, "parentesco": p, "nombre": n} for t, p, n in tels],
            "tarifa_head_coach": tarifa_head_coach, "inscripcion": inscripcion,
            "parecidos_confirmados": [d["id"] for d in dudosos],
            "sin_telefono": not tels,
            # adulto sin categoría: queda quién lo creó así (usuario_id) para que alguien la complete
            "sin_categoria": not nivel_ok and not es_menor(planilla_txt),
        }, ensure_ascii=False),
    ))
    db.session.flush()
    return alumno, dudosos
