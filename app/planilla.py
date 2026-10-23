"""Lógica del bot contra la planilla de Gabi.

Reglas de seguridad:
- Nunca se escribe en la columna AL DIA (es una fórmula).
- En "listado alumnos" solo se escribe la celda del mes de un pago confirmado, y solo si está vacía.
- El resto de los datos va a las pestañas telefonos, contactos nuevos y comprobantes.
"""
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from app.sheets_client import leer_pestana, pestana

TAB_ALUMNOS = "listado alumnos"
TAB_TELEFONOS = "telefonos"
TAB_NUEVOS = "contactos nuevos"
TAB_COMPROBANTES = "comprobantes"

ENC_TELEFONOS = ["TELEFONO", "ALUMNO", "CONFIRMADO", "FECHA"]
ENC_NUEVOS = ["TELEFONO", "NOMBRE", "NIVEL", "CONSULTA", "FECHA", "ESTADO"]
ENC_COMPROBANTES = ["FECHA", "TELEFONO", "ALUMNO", "MONTO", "MES", "ESTADO"]

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
         "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


# ---------- helpers ----------

def _ahora():
    return datetime.now(timezone(timedelta(hours=-3)))


def _fecha():
    return _ahora().strftime("%d/%m/%Y %H:%M")


def _tel(t):
    """Últimos 10 dígitos: 549 261 248-2058 y 2612482058 dan lo mismo."""
    return re.sub(r"\D", "", str(t or ""))[-10:]


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower()).strip()


def _a_numero(x):
    s = str(x or "").replace("$", "").replace(" ", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _hallar_alumnos(nombre):
    """Filas de 'listado alumnos' que coinciden con el nombre. Exacto primero; si no, por palabras."""
    q = _norm(nombre)
    if not q:
        return []
    filas = [f for f in leer_pestana(TAB_ALUMNOS) if f.get("NOMBRE", "").strip()]
    exactos = [f for f in filas if _norm(f["NOMBRE"]) == q]
    if exactos:
        return exactos
    palabras = q.split()
    return [f for f in filas if all(p in _norm(f["NOMBRE"]).split() for p in palabras)]


def _vinculo(telefono):
    t = _tel(telefono)
    if not t:
        return None
    for f in leer_pestana(TAB_TELEFONOS):
        if _tel(f.get("TELEFONO")) == t:
            return f
    return None


def _meses_sin_pago(fila):
    """Meses entre MES DE INICIO y el actual con la celda vacía (igual criterio que la fórmula)."""
    mes_hoy = _ahora().month - 1
    inicio = _norm(fila.get("MES DE INICIO")).upper()
    desde = MESES.index(inicio) if inicio in MESES else 0
    return [MESES[i].capitalize() for i in range(desde, mes_hoy + 1)
            if not str(fila.get(MESES[i], "")).strip()]


# ---------- herramientas del alumno ----------

def estado_de_pago(telefono):
    v = _vinculo(telefono)
    if not v:
        return {"conocido": False,
                "mensaje": "Este número no está vinculado a ningún alumno. Pedile el nombre completo y usá vincular_telefono."}
    if _norm(v.get("CONFIRMADO")) != "si":
        return {"conocido": True, "confirmado": False, "alumno": v.get("ALUMNO"),
                "mensaje": "El vínculo está pendiente de que lo confirme el encargado. No des datos de pago todavía."}
    filas = _hallar_alumnos(v.get("ALUMNO"))
    if len(filas) != 1:
        return {"conocido": True, "confirmado": True, "alumno": v.get("ALUMNO"),
                "mensaje": "No pude ubicar al alumno en la planilla. Avisale que el encargado lo revisa."}
    f = filas[0]
    return {
        "conocido": True, "confirmado": True, "alumno": f["NOMBRE"].strip(),
        "estado_pago": f.get("AL DIA"),
        "estado_alumno": f.get("ESTADO") or "Activo",
        "meses_sin_pago": _meses_sin_pago(f),
        "monto": "No lo tenemos cargado en la planilla: decile que el encargado le confirma el monto exacto.",
    }


def vincular_telefono(telefono, nombre):
    if _vinculo(telefono):
        return {"ok": False, "mensaje": "Este número ya tiene un vínculo registrado."}
    filas = _hallar_alumnos(nombre)
    if not filas:
        return {"ok": False, "mensaje": "No encontré ese nombre en la lista. Pedile nombre y apellido tal cual lo anotó la academia."}
    if len(filas) > 1:
        return {"ok": False, "mensaje": "Hay más de un alumno con ese nombre. Pedile el apellido completo."}
    real = filas[0]["NOMBRE"].strip()
    pestana(TAB_TELEFONOS, ENC_TELEFONOS).append_row(
        [str(telefono), real, "NO", _fecha()], value_input_option="USER_ENTERED")
    return {"ok": True, "alumno": real,
            "mensaje": "Quedó anotado. El encargado lo tiene que confirmar antes de darle datos de pago."}


def registrar_contacto_nuevo(telefono, nombre="", nivel="", consulta=""):
    ws = pestana(TAB_NUEVOS, ENC_NUEVOS)
    t = _tel(telefono)
    for f in leer_pestana(TAB_NUEVOS):
        if _tel(f.get("TELEFONO")) == t:
            # ya estaba: completo lo que falte
            for col, val in ((2, nombre), (3, nivel), (4, consulta)):
                if val and not str(f.get(ENC_NUEVOS[col - 1], "")).strip():
                    ws.update_cell(f["_fila"], col, val)
            return {"ok": True, "mensaje": "Contacto actualizado."}
    ws.append_row([str(telefono), nombre, nivel, consulta, _fecha(), "NUEVO"],
                  value_input_option="USER_ENTERED")
    return {"ok": True, "mensaje": "Contacto nuevo agendado."}


def avisar_comprobante(telefono, monto=None):
    """El alumno dice que ya pagó. Queda PENDIENTE hasta que Gabi lo confirme en la hoja."""
    v = _vinculo(telefono)
    nombre = v.get("ALUMNO") if v else ""
    n = _a_numero(monto)
    mes_actual = MESES[_ahora().month - 1].capitalize()
    t = _tel(telefono)
    # si ya hay uno pendiente de este mes, lo actualizo en vez de duplicar
    previos = [f for f in leer_pestana(TAB_COMPROBANTES)
               if _tel(f.get("TELEFONO")) == t and _norm(f.get("ESTADO")) == "pendiente"
               and _norm(f.get("MES")) == _norm(mes_actual)]
    if previos:
        f = previos[-1]
        if n is not None:
            pestana(TAB_COMPROBANTES, ENC_COMPROBANTES).update_cell(
                f["_fila"], ENC_COMPROBANTES.index("MONTO") + 1, n)
        monto_final = n if n is not None else _a_numero(f.get("MONTO"))
        return {"ok": True, "monto_anotado": int(monto_final) if monto_final is not None and monto_final == int(monto_final) else monto_final,
                "mensaje": "Ya había un comprobante pendiente de este mes, lo actualicé en vez de duplicarlo. Repetile el monto al alumno. El encargado lo confirma."}
    pestana(TAB_COMPROBANTES, ENC_COMPROBANTES).append_row(
        [_fecha(), str(telefono), nombre, n if n is not None else "",
         MESES[_ahora().month - 1].capitalize(), "PENDIENTE"],
        value_input_option="USER_ENTERED")
    return {"ok": True, "monto_anotado": int(n) if n is not None and n == int(n) else n,
            "mensaje": "Anotado. Repetile al alumno el monto anotado (si es null, preguntale cuánto fue). El encargado revisa y confirma el pago. No digas que ya está acreditado."}


def corregir_comprobante(telefono, monto):
    """Cambia el monto de un comprobante que sigue PENDIENTE. Uno ya confirmado no se toca."""
    n = _a_numero(monto)
    if n is None:
        return {"ok": False, "mensaje": "Falta el monto correcto. Preguntaselo al alumno."}
    t = _tel(telefono)
    pend = [f for f in leer_pestana(TAB_COMPROBANTES)
            if _tel(f.get("TELEFONO")) == t and _norm(f.get("ESTADO")) == "pendiente"]
    if not pend:
        return {"ok": False, "mensaje": "No hay un comprobante pendiente para corregir. Si ya lo confirmaron, lo cambia el encargado."}
    f = pend[-1]
    pestana(TAB_COMPROBANTES, ENC_COMPROBANTES).update_cell(
        f["_fila"], ENC_COMPROBANTES.index("MONTO") + 1, n)
    return {"ok": True, "monto_anterior": f.get("MONTO"),
            "monto_nuevo": int(n) if n == int(n) else n,
            "mensaje": "Corregido. Repetile al alumno el monto nuevo."}


# ---------- herramientas del jefe ----------

def comprobantes_pendientes():
    pend = [f for f in leer_pestana(TAB_COMPROBANTES) if _norm(f.get("ESTADO")) == "pendiente"]
    return {"cantidad": len(pend),
            "pendientes": [{"fecha": f["FECHA"], "alumno": f["ALUMNO"] or f["TELEFONO"],
                            "monto": f["MONTO"] or "sin monto", "mes": f["MES"]} for f in pend]}


def aplicar_pagos_confirmados():
    """Pasa a 'listado alumnos' los comprobantes que Gabi marcó CONFIRMADO."""
    comp = pestana(TAB_COMPROBANTES, ENC_COMPROBANTES)
    alum = pestana(TAB_ALUMNOS)
    enc_alum = alum.row_values(1)
    aplicados, saltados = [], []
    for f in leer_pestana(TAB_COMPROBANTES):
        if _norm(f.get("ESTADO")) != "confirmado":
            continue
        quien = f.get("ALUMNO") or f.get("TELEFONO")
        monto = _a_numero(f.get("MONTO"))
        mes = (f.get("MES") or "").upper()
        if monto is None:
            saltados.append(f"{quien}: falta el monto"); continue
        if mes not in MESES or mes not in enc_alum:
            saltados.append(f"{quien}: mes inválido"); continue
        filas = _hallar_alumnos(f.get("ALUMNO"))
        if len(filas) != 1:
            saltados.append(f"{quien}: no lo ubico en la lista"); continue
        fila = filas[0]["_fila"]
        col = enc_alum.index(mes) + 1
        if alum.cell(fila, col).value:
            saltados.append(f"{quien}: ya tenía algo anotado en {mes.capitalize()}"); continue
        alum.update_cell(fila, col, monto)
        comp.update_cell(f["_fila"], ENC_COMPROBANTES.index("ESTADO") + 1, "APLICADO")
        aplicados.append(f"{filas[0]['NOMBRE'].strip()} ({mes.capitalize()})")
    return {"aplicados": aplicados, "saltados": saltados}


# ---------- definición de tools (formato OpenAI) ----------

def _tool(nombre, desc, props=None, req=None):
    return {"type": "function", "function": {
        "name": nombre, "description": desc,
        "parameters": {"type": "object", "properties": props or {}, "required": req or []}}}


TOOLS_PLANILLA_ALUMNO = [
    _tool("consultar_estado_pago",
          "Mira en la planilla si quien escribe está al día o debe. Usala cuando pregunte cuánto debe, si está al día o a quién pagar. No lleva parámetros."),
    _tool("vincular_telefono",
          "Vincula el número de quien escribe con un alumno de la lista. Usala cuando el número no esté vinculado y la persona diga su nombre completo.",
          {"nombre": {"type": "string", "description": "Nombre y apellido que dijo la persona"}}, ["nombre"]),
    _tool("registrar_contacto_nuevo",
          "Agenda a una persona nueva que no es alumno. Usala cuando consulte por clases y no esté en la lista. Cargá solo lo que dijo.",
          {"nombre": {"type": "string"}, "nivel": {"type": "string"}, "consulta": {"type": "string", "description": "Qué quiere, en pocas palabras"}}),
    _tool("avisar_comprobante",
          "Anota que el alumno dice que ya pagó, para que el encargado lo confirme. Usala cuando diga que transfirió o mande un comprobante.",
          {"monto": {"type": "string", "description": "Monto si lo dijo, si no vacío"}}),
    _tool("corregir_comprobante",
          "Corrige el monto de un comprobante que el alumno ya avisó, cuando dice que se equivocó. Solo sirve si el encargado todavía no lo confirmó.",
          {"monto": {"type": "string", "description": "Monto correcto"}}, ["monto"]),
]

TOOLS_PLANILLA_JEFE = [
    _tool("comprobantes_pendientes", "Lista los comprobantes de pago que esperan confirmación."),
    _tool("aplicar_pagos_confirmados",
          "Pasa a la planilla los pagos que el encargado marcó CONFIRMADO en la pestaña comprobantes."),
]


def ejecutar(nombre, args, telefono):
    """Devuelve el resultado de la tool, o None si no es una tool de la planilla."""
    args = args or {}
    if nombre == "consultar_estado_pago":
        return estado_de_pago(telefono)
    if nombre == "vincular_telefono":
        return vincular_telefono(telefono, args.get("nombre", ""))
    if nombre == "registrar_contacto_nuevo":
        return registrar_contacto_nuevo(telefono, args.get("nombre", ""), args.get("nivel", ""), args.get("consulta", ""))
    if nombre == "avisar_comprobante":
        return avisar_comprobante(telefono, args.get("monto"))
    if nombre == "corregir_comprobante":
        return corregir_comprobante(telefono, args.get("monto"))
    if nombre == "comprobantes_pendientes":
        return comprobantes_pendientes()
    if nombre == "aplicar_pagos_confirmados":
        return aplicar_pagos_confirmados()
    return None
