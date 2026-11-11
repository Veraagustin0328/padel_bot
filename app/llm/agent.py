import json
import re
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.llm.client import client, MODEL
from app.llm.tools import tools_para_rol
from app import planilla
from app import recuperaciones as rec
from app import cambios_dias as cd
from app.cuotas import (
    DIAS_PROMO_2X1, FRANJA_POR_AMBITO, HORA_PROMO_DESDE, HORA_PROMO_HASTA, cargar_tarifas, precio_bucket,
)
from app.models_academia import AusenciaLapso, Clase, ConfigAcademia, Inscripcion, RecuperacionClase
from app.models_cuotas import CuotaMes, PagoCuota
from app.models import (
    ClaseSuelta, Conversacion, Alumno,
    CambioPendiente, Notificacion, EstadoChat,
)

MAX_HISTORIAL = 10
SESION_HORAS = 24

DATOS_DE_PAGO = (
    "Alias: academiaarenapadel. Se paga por transferencia a ese alias. "
    "Después el alumno te avisa por acá que transfirió, vos lo anotás y "
    "el encargado confirma el pago."
)

# ---------------------------------------------------------------- niveles
# Forma canónica -> todas las formas que aceptamos (1ra y 1era son lo mismo).
_NIVELES = {
    "1era": ["1era", "1ra", "1°", "primera", "1"],
    "2da": ["2da", "2a", "2°", "segunda", "2"],
    "3ra": ["3ra", "3era", "3°", "tercera", "3"],
    "4ta": ["4ta", "4°", "cuarta", "4"],
    "5ta": ["5ta", "5°", "quinta", "5"],
    "6ta": ["6ta", "6°", "sexta", "6"],
    "7ma": ["7ma", "7°", "septima", "séptima", "7"],
    "8va": ["8va", "8°", "octava", "8"],
    "principiante": ["principiante", "inicial", "principiantes"],
}


def _nivel_canonico(texto: str) -> str | None:
    t = (texto or "").strip().lower().replace(" ", "")
    for canonico, formas in _NIVELES.items():
        if t in formas:
            return canonico
    return None


# ---------------------------------------------------------------- precios
# Los precios salen de la tabla tarifas (la misma que usa el panel para las cuotas).
# Acá solo está cómo se traduce modalidad + turno del agente a franja + tipo de tarifa.
INSCRIPCION_DEFAULT = 25000  # si no está en config_academia; se cobra una sola vez

# (modalidad, turno) -> (franja, tipo de tarifa, personas fijas o None si las pide, pide veces, descripción)
# Igual que bucket_de en app/cuotas.py: la tarde no tiene Modo Academia, el grupal paga como particular de 3.
BUCKETS_PRECIO = {
    ("academia", "manana"): ("manana", "academia", 0, True,
                             "Modo Academia, mañana (7 a 12 hs). Los profes arman los grupos según el nivel."),
    ("academia", "tarde"): ("tarde", "particular", 3, True,
                            "Grupo de tarde (14:30, 15:30, 16:30 y 17:30 hs)."),
    ("academia", "sabado"): ("sabado", "academia", 0, False,
                             "Modo Academia del sábado a la mañana (8, 9, 10 y 11 hs)."),
    ("particular", "manana"): ("manana", "particular", None, True,
                               "Clases particulares de mañana (7 a 12 hs). El alumno decide cómo formar el grupo."),
    ("particular", "tarde"): ("tarde", "particular", None, True,
                              "Clases particulares de tarde (14:30, 15:30, 16:30 y 17:30 hs)."),
    ("particular", "sabado"): ("sabado", "particular", None, False,
                               "Particular del sábado a la mañana (8, 9, 10 y 11 hs)."),
}
PROMO_2X1 = ("manana", "promo_2x1", 0, True,
             "Promo 2x1 de mañana, solo lunes, miércoles y viernes de 9 a 12 hs.")

# el tipo viejo, por si el modelo lo sigue mandando: -> (modalidad, turno, extras)
TIPOS_VIEJOS = {
    "modo_academia": ("academia", "manana", {}),
    "particular_manana": ("particular", "manana", {}),
    "particular_manana_2x1": ("particular", "manana", {"promo_2x1": True}),
    "particular_tarde": ("particular", "tarde", {}),
    "particular_head_coach": ("particular", "manana", {"head_coach": True}),
    "sabado_modo_academia": ("academia", "sabado", {}),
    "sabado_particular": ("particular", "sabado", {}),
}

_TURNOS = {"manana": "manana", "mananas": "manana", "tarde": "tarde", "tardes": "tarde",
           "sabado": "sabado", "sabados": "sabado"}

def _politicas() -> str:
    """Las reglas salen de ConfigAcademia: cada club pone las suyas."""
    horas = rec.regla("aviso_horas") or 0
    tope = int(rec.regla("max_recuperaciones_mes") or 0)
    mismo_mes = rec.regla("recupera_mismo_mes")
    texto = "Las clases se pagan por mes adelantado. "
    if horas:
        texto += (f"Si no se puede ir, hay que avisar con al menos {horas} hs de anticipación; "
                  "si no, la clase no se puede recuperar. ")
    if tope:
        texto += f"Se puede recuperar hasta {tope} clase{'s' if tope > 1 else ''} por mes"
    else:
        texto += "Las clases avisadas a tiempo se pueden recuperar"
    texto += ", dentro del mismo mes de la falta." if mismo_mes else "."
    return texto

# ---------------------------------------------------------------- prompts
PROMPT_ALUMNO_PARTE_1 = (
    "Sos el asistente de WhatsApp de Academia Arena Pádel. Hablás como un profe "
    "argentino de confianza: re amable, alegre, con muy buena onda y mucha "
    "energía, como alguien que se alegra de hablar con el alumno.\n\n"
    "Estilo:\n"
    "- Usá SIEMPRE voseo ('querés', 'podés', 'decime', 'contame'). Nunca mezcles "
    "con tuteo ('quieres', 'puedes').\n"
    "- Tratalo de 'amigo' o 'amiga' (si no sabés, 'amigo/a') y usá su nombre si "
    "lo sabés. De vez en cuando, cuando cuenta algo bueno o se anota a una clase, "
    "usá 'bruto' o 'bruta' como piropo de pádel ('¡Qué bruto!', 'Dale, bruto'). "
    "No lo repitas en cada mensaje: tiene que sonar natural.\n"
    "- Al despedirte o cerrar la charla, deseale un lindo día, tarde o noche.\n"
    "- Usá emojis de buena onda y de pádel, 1 o 2 por mensaje, por ejemplo "
    "\U0001F3BE \U0001F4AA \U0001F60A \U0001F64C \U0001F525 \U0001F44F. "
    "No uses emojis numerados ni listas con emojis.\n"
    "- Mensajes cortos y naturales, como en WhatsApp.\n"
    "- Mantené el tono cálido SIEMPRE, incluso cuando tengas que decir que no "
    "podés ayudar con algo.\n"
    "- Cuando hables de plata, deudas, cancelaciones o algo que no se pudo hacer, "
    "seguí siendo amable pero sin chistes ni emojis festivos, y sé clarísimo con "
    "los datos.\n\n"    "Niveles de juego: 1era (también se escribe 1ra, es lo mismo), 2da, 3ra, 4ta, "
    "5ta, 6ta, 7ma, 8va y principiante. Si el alumno los escribe con palabras "
    "(primera, quinta, séptima...) o con número solo, normalizalo al nivel "
    "correspondiente (quinta = 5ta). Un número como '5ta' es un NIVEL, nunca un "
    "día ni una hora.\n\n"
    "Disponibilidad:\n"
    "- Si quiere anotarse o pregunta por clases, lugar u horarios y dijo un día, llamá "
    "consultar_cupos YA con ese día (y el turno y el nivel SOLO si los dijo). NO le "
    "preguntes nivel, turno ni hora antes de consultar. El sábado es siempre a la mañana: "
    "nunca preguntes el turno del sábado.\n"
    "- Mostrale las clases que te devolvió la tool con día, hora y nivel, y que elija. Si no "
    "hay lugar, ofrecele las 'alternativas' que te dio. Nunca inventes clases ni horarios "
    "que no vinieron de la tool.\n"
    "- Si no dijo ningún día, preguntale solo qué día le queda mejor.\n"
    "- Si ya le mostraste opciones y elige una ('dale', 'esa', 'la de las 18'), llamá "
    "anotar_en_clase directo con el día y la hora de esa clase. NO vuelvas a consultar cupos.\n"
    "- Si piden clase particular, preguntá día y hora, y si quieren algún profe "
    "en particular, ANTES de usar agendar_clase_suelta. No agendes con datos que "
    "no te dieron.\n"
    "- Que haya lugar no lo anota. Cuando elija una clase y confirme que quiere anotarse, "
    "usá anotar_en_clase con el clase_id que te dio consultar_cupos (o con el día y la "
    "hora). Solo decile que quedó anotado si la tool devolvió status 'anotado' o 'ya_anotado'.\n\n"
    "Precios:\n"
    "- Para CUALQUIER precio usá la tool consultar_precio. Nunca digas un precio "
    "de memoria ni lo calcules vos.\n"
    "- Cuando pregunten un precio, llamá consultar_precio con lo que el alumno "
    "YA dijo: modalidad (academia o particular), turno (mañana, tarde o sábado), "
    "personas y veces por semana. Si dijo día y hora, mandalos también. Nunca "
    "asumas ni inventes un dato que no dijo.\n"
    "- Si la tool te devuelve 'faltan', NO des ningún número: preguntale todo lo "
    "que falta en UNA sola frase corta y, cuando te conteste, volvé a llamarla.\n"
    "- Los precios son mensuales y cada alumno paga el suyo (por persona).\n"
    "- La inscripción es de $25.000, pago único. Mencionala solo si preguntan o si "
    "se están anotando.\n\n"
    "Confirmaciones:\n"
    "- Nunca digas que una clase quedó agendada, cancelada o que alguien quedó "
    "registrado si no llamaste a la tool correspondiente y devolvió ok.\n"
    "- Si un alumno confirma que quiere anotarse a un grupo y NO está registrado "
    "(más abajo te aviso si lo está), NO le repitas día ni hora: preguntale SOLO "
    "el nombre y apenas te lo diga llamá anotar_en_clase con la clase y ese nombre "
    "(y el nivel si lo mencionó).\n"
    "- Si quiere cancelar una clase particular que ya tenía, usá "
    "cancelar_clase_suelta (con el día si tiene más de una).\n\n"
    "Temas:\n"
    "- Vos manejás: clases grupales y particulares, lugar y horarios, anotarse, precios de "
    "las clases, cuotas y pagos, comprobantes de pago, faltas y recuperaciones, cambios de "
    "días y avisos de viaje. Eso lo resolvés con tus tools: NO lo derives.\n"
    "- Para CUALQUIER otro tema (alquiler de canchas, venta o alquiler de paletas o pelotas, "
    "torneos, eventos, etc.) llamá derivar_al_encargado con el tema y contale solo lo que "
    "diga 'decile'. NUNCA des precios, horarios, plazos ni disponibilidad de esos temas, y "
    "no uses consultar_precio para eso.\n"
)

BLOQUE_PAGOS_CON_DATOS = (
    "Pagos: si preguntan cómo o dónde pagar, respondé con estos datos y nada más: "
    + DATOS_DE_PAGO + "\n"
    "- Escribilo en voseo ('Podés transferir', no 'Podes').\n"
    "- Decile que cuando transfiera te avise con el monto y mande la foto o el PDF "
    "del comprobante por este chat: vos no lo leés, pero se lo pasás al encargado, "
    "que lo revisa y confirma el pago.\n"
    "- NUNCA digas que un pago se cobra, se acredita o se confirma solo, ni "
    "'al instante'. Quien confirma el pago es el encargado.\n"
)
BLOQUE_PAGOS_SIN_DATOS = (
    "Pagos: si preguntan cómo o dónde pagar, decí que el encargado les pasa los "
    "datos de pago. NO inventes alias, CBU, apps, lugares ni medios de pago.\n"
)
BLOQUE_PAGOS = BLOQUE_PAGOS_CON_DATOS if DATOS_DE_PAGO else BLOQUE_PAGOS_SIN_DATOS

BLOQUE_PLANILLA = (
    "\nEstado de pago y número de teléfono:\n"
    "- Si preguntan cuánto deben o cuánto es su cuota de este mes, llamá estado_cuota. "
    "Si dice que no lo encuentra, decile que no lo ubicás y ofrecele pasarle la consulta al encargado.\n"
    "- Si preguntan si están al día, qué meses deben o a quién pagar, llamá consultar_estado_pago.\n"
    "- Si la tool dice que el número no está vinculado, pedile nombre y apellido tal "
    "cual lo tiene anotado la academia y llamá vincular_telefono. Si sale ok, contale "
    "que el encargado tiene que confirmar el vínculo antes de pasarle datos de pago.\n"
    "- Si el vínculo está pendiente de confirmación, NO des datos de pago: decile con "
    "buena onda que el encargado todavía no lo confirmó.\n"
    "- Si está vinculado y confirmado, decile si está al día o qué meses figuran sin "
    "pago, y pasale el alias. El monto sacalo de estado_cuota; si no está, decile que el "
    "encargado se lo confirma. Nunca inventes un monto.\n"
    "- Si dice que ya pagó o transfirió, llamá avisar_comprobante (con el monto si lo "
    "dijo) y decile que quedó anotado para que el encargado lo confirme. NUNCA digas "
    "que el pago ya está acreditado.\n"
    "- Si el alumno no dijo el monto, preguntáselo ANTES de llamar avisar_comprobante. "
    "Cuando lo anotes, repetile el monto exacto (por ejemplo 'Anoté $220.000') para "
    "que lo confirme.\n"
    "- Si el alumno dice que se equivocó con el monto, llamá corregir_comprobante con "
    "el monto correcto y confirmale el monto corregido. No le pidas que vuelva a avisar.\n"
    "- Si una persona nueva, que no es alumna, consulta por clases, apenas te diga su "
    "nombre llamá registrar_contacto_nuevo con lo que dijo (nombre, nivel y qué "
    "consulta). Llamala una sola vez por charla, salvo que aporte datos nuevos.\n"
)

PROMPT_ALUMNO_PARTE_2 = (
    "\nReglas estrictas:\n"
    "- Nunca menciones nombres de profesores, salvo si el alumno pidió uno puntual "
    "para una clase particular.\n"
    "- Nunca repitas el nivel de juego que el alumno ya dijo.\n"
    "- Usá el historial de la charla para no repreguntar cosas que ya te dijeron.\n"
    "- No podés cambiar categorías ni confirmar pagos: esas herramientas no las "
    "tenés. Si te lo piden, respondé: 'Ese cambio lo tiene que hacer el encargado "
    "directamente, yo no puedo hacerlo desde acá.' No inventes propuestas "
    "pendientes que no te mencioné más abajo.\n"
    "- Nunca compartas datos de otros alumnos. Decí con buena onda que no podés.\n"
    "- Si el alumno quiere dejar la academia, preguntale el motivo (horario, "
    "lesión u otro) con buena onda antes de usar dar_de_baja, y despedite "
    "dejando la puerta abierta.\n"
    "- Si avisa que no va a una clase ('el jueves no voy'), usá avisar_ausencia con la "
    "fecha tal cual la dijo. Si pide recuperar o reprogramar una clase, preguntale qué día "
    "y horario le queda bien y usá pedir_recuperacion. Si cuenta que se va de viaje, "
    "preguntale desde qué día hasta qué día y usá avisar_viaje.\n"
    "- Esas tres tools primero te devuelven la fecha completa para confirmar: preguntale "
    "si es esa fecha, copiándola tal cual, y cuando te diga que sí volvé a llamarla con "
    "confirmado=true.\n"
    "- Contale SOLO lo que dice el campo 'decile' de la tool, sin cambiar fechas ni "
    "condiciones. Nunca digas que una recuperación está confirmada si la tool no "
    "devolvió status 'confirmada', y nunca prometas excepciones.\n"
    "- Si la tool dice que el número es de varios alumnos, preguntale de quién habla y "
    "volvé a llamarla con alumno=<ese nombre>.\n"
    "- Si más abajo ves un 'cambio pendiente', contale de qué se trata y "
    "preguntale si lo acepta; cuando conteste usá resolver_cambio_pendiente.\n"
    "- Si quiere cambiar los días u horarios fijos que viene ('desde diciembre quiero ir "
    "solo los jueves'), usá pedir_cambio_dias con los días nuevos (y la hora o desde cuándo "
    "si lo dijo). Primero te devuelve el detalle con la fecha y la cuota: pasáselo tal cual "
    "y, cuando diga que sí, volvé a llamarla igual con confirmado=true. Si no hay lugar, "
    "ofrecele las alternativas que te dé. Nunca digas que el cambio ya está hecho: lo "
    "aprueba el encargado.\n"
    "- Aunque lo cuente como afirmación ('en diciembre voy solo los jueves', 'desde el mes "
    "que viene vengo martes y jueves'), es un pedido de cambio: llamá pedir_cambio_dias. "
    "NUNCA digas 'tomo nota', 'lo anoto' ni 'queda registrado' si la tool no devolvió "
    "status 'pendiente': sin la tool no se guarda nada.\n"
    "\nFormato (obligatorio, tiene prioridad sobre todo lo demás):\n"
    "- Escribí en frases cortas, sin listas. NUNCA uses listas numeradas ni emojis "
    "numerados. Si tenés que preguntar varias cosas, hacelo en una sola frase "
    "corrida: '¿Desde qué día y hasta qué día te vas?'\n"
    "- Voseo siempre: 'preferís', 'querés', 'podés', 'tenés', 'decime'. Jamás "
    "'prefieres', 'quieres', 'puedes', 'tienes'.\n"
    "- Si el alumno solo está preguntando, NO le pidas el nombre ni el registro. "
    "Pedilo recién cuando confirme que quiere anotarse.\n"
    "- Respondé primero lo que preguntó, y recién después, si hace falta, "
    "preguntá una sola cosa.\n"
)

SYSTEM_PROMPT_ALUMNO = PROMPT_ALUMNO_PARTE_1 + BLOQUE_PAGOS + BLOQUE_PLANILLA + PROMPT_ALUMNO_PARTE_2

def _saludo_primer_mensaje() -> str:
    """El saludo cambia según la hora de Argentina (UTC-3)."""
    hora = (datetime.utcnow() - timedelta(hours=3)).hour
    if hora < 12:
        momento = "Buen día"
    elif hora < 20:
        momento = "Buenas tardes"
    else:
        momento = "Buenas noches"
    return (
        "Es el primer mensaje de esta conversación (o pasó más de un día desde el "
        "último). Arrancá tu respuesta con un saludo cálido y breve acorde a la hora: "
        f"'¡{momento}, amigo!' o '¡{momento}, amiga!' (si no sabés, '¡{momento}, amigo/a!'). "
        f"Si sabés el nombre del alumno, usalo ('¡{momento}, Lucía!'). "
        "Después respondé lo que preguntó."
    )

SALUDO_YA_SALUDASTE = (
    "Ya saludaste en esta conversación. NO vuelvas a saludar ni a decir 'Hola'; "
    "respondé directo."
)

SYSTEM_PROMPT_JEFE = (
    "Sos el asistente interno de Academia Arena Pádel, hablando con el encargado. "
    "Podés ejecutar cambios administrativos como actualizar la categoría de un "
    "alumno, proponerle un cambio de día/horario con crear_cambio_pendiente (mandá "
    "dias_nuevos si es un cambio de días; queda pendiente de que el alumno lo confirme), "
    "o pausar/reanudar al bot en una conversación puntual. "
    "También podés ver los comprobantes de pago pendientes (comprobantes_pendientes) "
    "y pasar a la planilla los que el encargado marcó como CONFIRMADO "
    "(aplicar_pagos_confirmados). Sé directo y breve, es un canal de trabajo."
)


# ---------------------------------------------------------------- principal
def _inicio_sesion() -> datetime:
    return datetime.utcnow() - timedelta(hours=SESION_HORAS)


def _alumnos_con_telefono(telefono: str) -> list[Alumno]:
    """Todos los que matchean por los últimos 10 dígitos (WhatsApp manda 549..., la base puede no tenerlo)."""
    t = planilla._tel(telefono)
    if not t:
        return []
    return [a for a in Alumno.query.all() if planilla._tel(a.telefono) == t]


def _alumno_por_telefono(telefono: str) -> Alumno | None:
    """Si matchea más de uno, no devuelvo ninguno (mejor no mostrar datos de otro)."""
    alumnos = _alumnos_con_telefono(telefono)
    return alumnos[0] if len(alumnos) == 1 else None


def _nota_registro(telefono: str) -> str:
    alumno = _alumno_por_telefono(telefono)
    if alumno:
        return f"Este número YA está registrado como alumno: {alumno.nombre}. No hace falta registrarlo."
    return (
        "Este número NO está registrado todavía como alumno. Si quiere anotarse "
        "a una clase, pedile el nombre y pasáselo a anotar_en_clase, que lo registra y lo anota."
    )


import re as _re

_TUTEO = {
    "prefieres": "preferís", "quieres": "querés", "puedes": "podés", "tienes": "tenés",
    "necesitas": "necesitás", "sabes": "sabés", "dime": "decime",
    "cuéntame": "contame", "cuentame": "contame",
    "debes": "debés", "avísame": "avisame",
}
_RX_TUTEO = _re.compile(r"\b(" + "|".join(_TUTEO) + r")\b", _re.IGNORECASE)
_RX_NUM_EMOJI = _re.compile(r"[0-9#*]\ufe0f?\u20e3\s*")


def _limpiar_respuesta(texto: str) -> str:
    """Red de seguridad: el modelo a veces tutea o usa emojis numerados aunque se lo prohibimos."""
    def _voseo(m):
        nuevo = _TUTEO[m.group(1).lower()]
        return nuevo.capitalize() if m.group(1)[0].isupper() else nuevo

    texto = _RX_TUTEO.sub(_voseo, texto)
    return _RX_NUM_EMOJI.sub("", texto)


def _respuesta_vacia(mensaje) -> bool:
    """Sin tools y sin texto útil: vacía o el modelo mismo dijo 'No entendí eso'."""
    if mensaje.tool_calls:
        return False
    contenido = (mensaje.content or "").strip()
    return not contenido or contenido.lower().startswith("no entendí eso")


def procesar_mensaje(telefono: str, texto: str, es_jefe: bool = False) -> str:
    return _limpiar_respuesta(_procesar_mensaje_interno(telefono, texto, es_jefe))


def _procesar_mensaje_interno(telefono: str, texto: str, es_jefe: bool = False) -> str:
    _guardar_mensaje(telefono, "user", texto)

    # Avisos de pago: los resuelve el código, no el modelo (es plata)
    if not es_jefe:
        respuesta_pago = _responder_pago(telefono, texto)
        if respuesta_pago:
            _guardar_mensaje(telefono, "assistant", respuesta_pago)
            return respuesta_pago

    system_prompt = SYSTEM_PROMPT_JEFE if es_jefe else SYSTEM_PROMPT_ALUMNO
    tools = tools_para_rol(es_jefe)

    mensajes = [{"role": "system", "content": system_prompt}]

    if not es_jefe:
        ya_hablo_bot = (
            Conversacion.query.filter(
                Conversacion.telefono == telefono,
                Conversacion.rol == "assistant",
                Conversacion.creado_en >= _inicio_sesion(),
            ).first()
            is not None
        )
        mensajes.append({
            "role": "system",
            "content": SALUDO_YA_SALUDASTE if ya_hablo_bot else _saludo_primer_mensaje(),
        })
        mensajes.append({"role": "system", "content": _nota_registro(telefono)})
        mensajes.append({"role": "system", "content": "Reglas de faltas y recuperaciones: " + _politicas()})

    mensajes.extend(_historial(telefono))

    if not es_jefe:
        pendiente = _cambio_pendiente_de(telefono)
        if pendiente:
            mensajes.append({
                "role": "system",
                "content": (
                    f"IMPORTANTE - ACCIÓN OBLIGATORIA: este alumno tiene un cambio "
                    f"pendiente sin resolver (id={pendiente.id}): '{pendiente.propuesta}'. "
                    "SIN IMPORTAR lo que diga en su mensaje, tu respuesta DEBE "
                    "mencionar esta propuesta y preguntarle si la acepta, ANTES de "
                    "cualquier otra cosa."
                ),
            })
        pedido = _pedido_propio_de(telefono)
        if pedido:
            mensajes.append({
                "role": "system",
                "content": (
                    f"Este alumno ya pidió un cambio de días que espera la aprobación del "
                    f"encargado: '{pedido.propuesta}'. Si pregunta, decile que está pendiente. "
                    "NO digas que está aprobado ni que ya cambió."
                ),
            })

    # si vuelve vacía o con el "No entendí eso", pruebo una vez más variando un poco
    for intento in range(2):
        respuesta = client.chat.completions.create(
            model=MODEL,
            messages=mensajes,
            tools=tools,
            tool_choice="auto",
            temperature=0.2 + 0.3 * intento,
        )
        mensaje_modelo = respuesta.choices[0].message
        if not _respuesta_vacia(mensaje_modelo):
            break
        print(f"[llm] respuesta vacía o 'no entendí' (intento {intento + 1}/2)", flush=True)

    if not mensaje_modelo.tool_calls:
        print(f"[llm] sin tools para: {texto!r}", flush=True)
        texto_final = mensaje_modelo.content or "No entendí eso, ¿podés reformularlo?"
        _guardar_mensaje(telefono, "assistant", texto_final)
        return texto_final

    mensajes.append(mensaje_modelo.model_dump())

    # si en el mismo turno derivó, no hay precio que dar de ese tema (ej. "cuánto sale el torneo")
    derivada = any(re.sub(r"[^A-Za-z_]", "", tc.function.name or "") == "derivar_al_encargado"
                   for tc in mensaje_modelo.tool_calls)

    conocidas = {t["function"]["name"] for t in tools}  # solo las de su rol
    for tool_call in mensaje_modelo.tool_calls:
        nombre = re.sub(r"[^A-Za-z_]", "", tool_call.function.name or "")
        nombre, error_nombre = _corregir_nombre_tool(nombre, conocidas)
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        if error_nombre:
            resultado = error_nombre
        elif nombre == "buscar_grupo_disponible":
            # la tool vieja: por si el modelo la sigue mandando, va a consultar_cupos
            resultado = _consultar_cupos({"dia": args.get("dia"), "nivel": args.get("nivel_juego")})
        elif nombre == "consultar_precio":
            resultado = PRECIO_DERIVADO if derivada else _consultar_precio(args)
        elif nombre == "consultar_cupos":
            resultado = _consultar_cupos(args)
        elif nombre == "derivar_al_encargado":
            resultado = _derivar_al_encargado(telefono, args, texto)
        elif nombre == "anotar_en_clase":
            resultado = _anotar_en_clase(telefono, args)  # el alumno sale del número, nunca de args
        elif nombre == "estado_cuota":
            resultado = _estado_cuota(telefono)  # nunca con args: solo el que escribe
        elif nombre == "agendar_clase_suelta":
            resultado = _agendar_clase_suelta(telefono, args)
        elif nombre == "cancelar_clase_suelta":
            resultado = _cancelar_clase_suelta(telefono, args)
        elif nombre in NOMBRES_PLANILLA:
            resultado = _usar_planilla(nombre, args, telefono, es_jefe, texto)
        elif nombre == "actualizar_categoria":
            resultado = _actualizar_categoria(args, es_jefe)
        elif nombre == "crear_cambio_pendiente":
            resultado = _crear_cambio_pendiente(args, es_jefe)
        elif nombre == "resolver_cambio_pendiente":
            resultado = _resolver_cambio_pendiente(telefono, args)
        elif nombre == "pedir_cambio_dias":
            resultado = _pedir_cambio_dias(telefono, args)  # el alumno sale del número
        elif nombre == "registrar_alumno":
            resultado = _registrar_alumno(telefono, args)
        elif nombre == "dar_de_baja":
            resultado = _dar_de_baja(telefono, args)
        # el alumno sale siempre del número que escribe, nunca de lo que diga el modelo
        elif nombre == "avisar_ausencia":
            resultado = _avisar_ausencia(telefono, args)
        elif nombre in ("pedir_recuperacion", "reprogramar_clase"):  # el nombre viejo, por las dudas
            resultado = _pedir_recuperacion(telefono, args)
        elif nombre == "avisar_viaje":
            resultado = _avisar_viaje(telefono, args)
        elif nombre == "pausar_bot":
            resultado = _pausar_bot(args, es_jefe)
        elif nombre == "reanudar_bot":
            resultado = _reanudar_bot(args, es_jefe)
        else:
            print(f"[tool?] nombre={tool_call.function.name!r} limpio={nombre!r} conocidas={sorted(NOMBRES_PLANILLA)}", flush=True)
            resultado = {"error": f"Tool desconocida: {nombre}"}

        print(f"[tool] {nombre} {args} -> {resultado}", flush=True)
        mensajes.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(resultado, ensure_ascii=False),
        })

    texto_final = None
    for intento in range(3):
        respuesta_final = client.chat.completions.create(
            model=MODEL,
            messages=mensajes,
            temperature=0.2 + 0.3 * intento,  # si vino vacía, la próxima vez varía un poco
        )
        eleccion = respuesta_final.choices[0]
        texto_final = eleccion.message.content
        if texto_final and texto_final.strip():
            break
        print(f"[llm] respuesta final vacía después de usar tools "
              f"(intento {intento + 1}/3, finish_reason={eleccion.finish_reason})", flush=True)
    if not texto_final or not texto_final.strip():
        texto_final = "Perdón, tuve un problema para responderte. ¿Me lo repetís?"
    _guardar_mensaje(telefono, "assistant", texto_final)
    return texto_final


def esta_pausado(telefono: str) -> bool:
    estado = EstadoChat.query.filter_by(telefono=telefono).first()
    return bool(estado and estado.modo == "humano")


def _guardar_mensaje(telefono: str, rol: str, contenido: str) -> None:
    db.session.add(Conversacion(telefono=telefono, rol=rol, contenido=contenido))
    db.session.commit()


# ---------------------------------------------------------------- nombre de tool mal escrito
# Solo las de lectura se pueden adivinar: si le pifia, no se rompe nada.
# Las que escriben (anotar, ausencias, recuperaciones, cambios, comprobantes...) nunca se adivinan.
TOOLS_LECTURA = {"consultar_cupos", "consultar_precio", "estado_cuota", "consultar_estado_pago"}
NOMBRES_VIEJOS = {"buscar_grupo_disponible", "reprogramar_clase"}  # el despacho los sigue aceptando
UMBRAL_NOMBRE = 0.85   # bien alto: 'consult_cupos' da 0.93
UMBRAL_PARECIDO = 0.7  # de acá para arriba es un intento de una tool que escribe


def _corregir_nombre_tool(nombre: str, conocidas: set[str]) -> tuple[str, dict | None]:
    """(nombre a usar, None) o (nombre, error para el modelo) si se parece a una tool que escribe."""
    if nombre in conocidas or nombre in NOMBRES_VIEJOS:
        return nombre, None
    parecidos = sorted(((SequenceMatcher(None, nombre, c).ratio(), c) for c in conocidas), reverse=True)
    if not parecidos:
        return nombre, None
    ratio, mejor = parecidos[0]
    segundo = parecidos[1][0] if len(parecidos) > 1 else 0
    if mejor in TOOLS_LECTURA and ratio >= UMBRAL_NOMBRE and ratio - segundo >= 0.05:
        print(f"[tool] nombre corregido: {nombre!r} -> {mejor!r} ({ratio:.2f})", flush=True)
        return mejor, None
    if ratio >= UMBRAL_PARECIDO:
        return nombre, {"error": f"La tool '{nombre}' no existe (la correcta es '{mejor}'). NO se hizo nada. "
                                 "No le digas al alumno que quedó hecho: pedile que te lo confirme de nuevo."}
    return nombre, None  # cae en 'Tool desconocida'


def _notificar(mensaje: str, tipo: str) -> None:
    db.session.add(Notificacion(mensaje=mensaje, tipo=tipo))
    db.session.commit()


def _historial(telefono: str) -> list[dict]:
    mensajes = (
        Conversacion.query.filter(
            Conversacion.telefono == telefono,
            Conversacion.creado_en >= _inicio_sesion(),
        )
        .order_by(Conversacion.creado_en.desc())
        .limit(MAX_HISTORIAL)
        .all()
    )
    return [{"role": m.rol, "content": m.contenido} for m in reversed(mensajes)]


def _cambio_pendiente_de(telefono: str) -> CambioPendiente | None:
    """Por los últimos 10 dígitos: se guarda con el teléfono de la base (sin 549) y WhatsApp manda con 549."""
    t = planilla._tel(telefono)
    if not t:
        return None
    # solo los que esperan la respuesta del alumno (los viejos no tienen 'espera')
    pendientes = (
        CambioPendiente.query.filter_by(estado="pendiente")
        .filter(db.or_(CambioPendiente.espera.is_(None), CambioPendiente.espera == "alumno"))
        .order_by(CambioPendiente.creado_en.desc(), CambioPendiente.id.desc())
        .all()
    )
    return next((c for c in pendientes if planilla._tel(c.alumno_telefono) == t), None)


def _pedido_propio_de(telefono: str) -> CambioPendiente | None:
    """El cambio de días que pidió el alumno y todavía no resolvió el encargado."""
    alumno = _alumno_por_telefono(telefono)
    if not alumno:
        return None
    pedidos = cd.pendientes_del_alumno(alumno.id, espera="encargado")
    return pedidos[0] if pedidos else None


# ---------------------------------------------------------------- tools
def _inscripcion() -> int:
    cfg = db.session.get(ConfigAcademia, "inscripcion")
    try:
        return int(json.loads(cfg.valor)) if cfg else INSCRIPCION_DEFAULT
    except (TypeError, ValueError):
        return INSCRIPCION_DEFAULT


_DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2, "jueves": 3,
         "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6}


def _fuera_de_promo(args: dict) -> bool:
    """True solo si el alumno dijo un día u hora que NO entra en el 2x1."""
    dia = (args.get("dia") or "").strip().lower()
    if dia and _DIAS.get(dia) not in DIAS_PROMO_2X1:
        return True
    m = re.match(r"\s*(\d{1,2})", str(args.get("hora") or ""))
    return bool(m) and not (HORA_PROMO_DESDE <= int(m.group(1)) < HORA_PROMO_HASTA)


def _en_promo(args: dict) -> bool:
    """True solo si dijo día Y hora y los dos entran en el 2x1 (igual que el panel)."""
    return bool((args.get("dia") or "").strip() and re.match(r"\s*\d", str(args.get("hora") or ""))) \
        and not _fuera_de_promo(args)


def _al_encargado(motivo: str) -> dict:
    # nunca inventar: si no está en la base, lo ve el encargado
    return {"error": f"{motivo} NO des ningún número ni estimes. Decile al alumno con buena onda "
                     "que ese precio lo consultás con el encargado y que te lo confirma."}


def _si(valor) -> bool:
    # el modelo a veces manda "true" como texto
    return valor is True or planilla._norm(valor) in ("true", "si", "1")


def _entero(valor):
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def _modalidad_y_turno(args: dict) -> tuple[str | None, str | None, dict]:
    """Saca modalidad y turno de lo que mandó el modelo, aceptando el tipo viejo."""
    extras = {}
    modalidad = planilla._norm(args.get("modalidad"))
    turno = _TURNOS.get(planilla._norm(args.get("turno")).replace(" ", ""))
    tipo = planilla._norm(args.get("tipo")).replace(" ", "_")
    if tipo in TIPOS_VIEJOS:
        m_vieja, t_vieja, extras = TIPOS_VIEJOS[tipo]
        modalidad = modalidad or m_vieja
        turno = turno or t_vieja
    if not turno and _DIAS.get(planilla._norm(args.get("dia"))) == 5:
        turno = "sabado"  # el sábado es siempre a la mañana: no hay turno que preguntar
    if "academia" in modalidad or "grupal" in modalidad:
        modalidad = "academia"
    elif "particular" in modalidad:
        modalidad = "particular"
    else:
        modalidad = None
    return modalidad, turno, extras


def _consultar_precio(args: dict) -> dict:
    modalidad, turno, extras = _modalidad_y_turno(args)
    promo = _si(args.get("promo_2x1")) or extras.get("promo_2x1", False)
    head_coach = _si(args.get("head_coach")) or extras.get("head_coach", False)

    # la promo y el head coach son siempre particulares de mañana
    if promo or head_coach:
        modalidad = modalidad or "particular"
    if promo:
        turno = turno or "manana"
        if turno != "manana" or modalidad != "particular" or _fuera_de_promo(args):
            return {"error": "La promo 2x1 es solo lunes, miércoles y viernes de 9 a 12 hs, y lo que pidió "
                             "el alumno no entra. Contale eso con buena onda y, si quiere ese horario igual, "
                             "consultá de nuevo con modalidad particular, turno mañana y 2 personas, sin promo_2x1."}

    if head_coach:
        return _al_encargado("Las clases con el head coach no tienen tarifa cargada.")

    if modalidad and turno and not promo:
        franja, tipo_tarifa, personas_fijas, pide_veces, descripcion = BUCKETS_PRECIO[(modalidad, turno)]
    elif promo:
        franja, tipo_tarifa, personas_fijas, pide_veces, descripcion = PROMO_2X1
    else:
        # falta modalidad o turno: igual juntamos lo demás que falte
        personas_fijas = None if modalidad == "particular" else 0
        pide_veces = turno != "sabado"

    personas = personas_fijas if personas_fijas is not None else _entero(args.get("personas"))
    veces = _entero(args.get("veces") or args.get("veces_por_semana")) if pide_veces else 1

    # todo lo que falta junto, para que lo pregunte en una sola frase
    faltan = []
    if not modalidad:
        faltan.append("si quiere grupo armado por los profes (modo academia) o clase particular con su propio grupo")
    if not turno:
        faltan.append("si prefiere mañana, tarde o sábado")
    if personas is None:
        faltan.append("cuántas personas van a la clase")
    if pide_veces and veces is None:
        faltan.append("cuántas veces por semana")
    if faltan:
        return {"faltan": faltan,
                "error": "Todavía no podés dar un precio. NO des ningún número. Preguntale al alumno, "
                         "en UNA sola frase corta: " + "; ".join(faltan) + "."}

    # 2 personas de mañana en día y hora de promo: el panel lo cobra como 2x1
    if (modalidad, turno, personas) == ("particular", "manana", 2) and _en_promo(args):
        franja, tipo_tarifa, personas, _, descripcion = PROMO_2X1

    if personas >= 3:
        personas = 3  # 3 y 4 personas pagan igual

    tarifas = cargar_tarifas()
    precio, nota = precio_bucket(tarifas, franja, tipo_tarifa, personas, veces)
    if precio is None:
        return _al_encargado("Esa combinación no tiene tarifa cargada.")
    if nota:
        # salió de sumar tarifas, no hay una exacta: no damos el número
        return _al_encargado("Esa combinación no tiene una tarifa exacta cargada.")

    return {
        "descripcion": descripcion,
        "precio_mensual": precio,
        "por_persona": True,
        "inscripcion_pago_unico": _inscripcion(),
        "politicas": _politicas(),
    }


# ---------------------------------------------------------------- cupos y cuota (solo lectura)
_NOMBRE_DIA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _nivel_de_clase(nivel_clase: str, canonico: str) -> bool:
    """'6TA/7MA' sirve para 6ta y para 7ma; 'PRINCIPIANTES' para principiante."""
    partes = re.split(r"[/,\s-]+", (nivel_clase or "").lower())
    return any(_nivel_canonico(p) == canonico for p in partes if p)


def _vigente(hoy):
    # mismo criterio que Mis clases: 'hasta' es el primer día que ya no va
    return cd.vigente_en(hoy)


def _anotados_hoy(clase_ids: list[int], hoy) -> dict[int, int]:
    if not clase_ids:
        return {}
    return dict(
        db.session.query(Inscripcion.clase_id, db.func.count(Inscripcion.id))
        .filter(Inscripcion.clase_id.in_(clase_ids), _vigente(hoy))
        .group_by(Inscripcion.clase_id).all()
    )


MAX_CLASES_CUPOS = 10  # para no inflar tokens cuando pide el día entero
MAX_ALTERNATIVAS = 4
_FRANJAS_ADULTOS = ("manana", "tarde", "sabado")  # kids solo si lo pide


def _ambitos_de(franjas) -> list[str]:
    return [a for a, f in FRANJA_POR_AMBITO.items() if f in franjas]


def _con_lugar(clases: list[Clase], fecha) -> list[dict]:
    """Compacto: sin profe ni alumnos, solo lo que el alumno necesita (el id es para anotar_en_clase)."""
    anotados = _anotados_hoy([c.id for c in clases], fecha)
    vistas = {}  # mismo día, hora y nivel en otra cancha: para el alumno es la misma, dejo la de más lugares
    for c in clases:
        libres = c.cupo - anotados.get(c.id, 0)
        clave = (c.dia_semana, c.hora_inicio, planilla._norm(c.nivel))
        if libres > 0 and (clave not in vistas or libres > vistas[clave]["lugares"]):
            vistas[clave] = {"clase_id": c.id, "dia": _NOMBRE_DIA[c.dia_semana],
                             "hora": c.hora_inicio.strftime("%H:%M"), "nivel": c.nivel or "sin nivel",
                             "lugares": libres}
    return list(vistas.values())  # dict mantiene el orden de entrada


def _alternativas(dia: int, franja: str | None, nivel: str | None, ya_vistas: set[int], fecha) -> list[dict]:
    """Lo más cercano con lugar: primero otro horario del mismo día, después los días más
    cercanos (mismo turno antes que otro). Mismo nivel si lo dijo."""
    franjas = ("kids",) if franja == "kids" else _FRANJAS_ADULTOS
    clases = Clase.query.filter(
        Clase.activa.is_(True), Clase.tipo == "grupal", Clase.ambito.in_(_ambitos_de(franjas)),
    ).all()
    clases = [c for c in clases if c.id not in ya_vistas and (not nivel or _nivel_de_clase(c.nivel, nivel))]

    def _cercania(c):
        otro_turno = bool(franja) and FRANJA_POR_AMBITO.get(c.ambito) != franja
        return (abs(c.dia_semana - dia), otro_turno, c.dia_semana, c.hora_inicio)

    return _con_lugar(sorted(clases, key=_cercania), fecha)[:MAX_ALTERNATIVAS]


def _consultar_cupos(args: dict) -> dict:
    dia = _DIAS.get(planilla._norm(args.get("dia")))
    if dia is None:
        return {"error": "Falta el día. Preguntale solo qué día le queda mejor y volvé a buscar."}
    franja = planilla._norm(args.get("franja")).replace(" ", "") or None
    franja = {"mananas": "manana", "tardes": "tarde"}.get(franja, franja)
    if franja not in (None, "manana", "tarde", "kids"):
        franja = None
    if dia == 5 and franja != "kids":
        franja = "sabado"  # el sábado es siempre a la mañana
    franjas = (franja,) if franja else _FRANJAS_ADULTOS
    nivel = _nivel_canonico(args.get("nivel") or "")

    # si pregunta por más adelante, cuento los anotados en esa fecha (nunca antes de hoy)
    hoy = planilla._ahora().date()
    desde = cd.leer_fecha(args.get("desde"), hoy)
    if desde and desde > hoy:
        hoy = desde
    fecha = {"desde": cd.fecha_corta(hoy)} if desde and desde == hoy else {}

    clases = Clase.query.filter(
        Clase.activa.is_(True), Clase.tipo == "grupal",
        Clase.dia_semana == dia, Clase.ambito.in_(_ambitos_de(franjas)),
    ).order_by(Clase.hora_inicio).all()
    if nivel:
        clases = [c for c in clases if _nivel_de_clase(c.nivel, nivel)]
    con_lugar = _con_lugar(clases, hoy)

    if con_lugar:
        res = {"clases_con_lugar": con_lugar[:MAX_CLASES_CUPOS], **fecha,
               "mensaje": "Pasale estas opciones con día, hora y nivel y que elija. Que haya lugar no lo "
                          "anota: no digas que quedó reservado."}
        if len(con_lugar) > MAX_CLASES_CUPOS:
            res["mensaje"] += " Hay más: si no le sirve ninguna, preguntale turno o nivel para achicar."
        return res

    # no hay lugar (o no hay clases): ofrezco lo más cercano en vez de un "no hay" seco
    motivo = "están llenas" if clases else "no hay clases grupales"
    que = "ese día" + (" y turno" if franja and franja != "sabado" else "") + (" para ese nivel" if nivel else "")
    alternativas = _alternativas(dia, franja, nivel, {c.id for c in clases}, hoy)
    if alternativas:
        return {"clases_con_lugar": [], "alternativas": alternativas, **fecha,
                "mensaje": f"Para {que} {motivo}. Contale eso y ofrecele estas alternativas con día, hora y "
                           "nivel para que elija. No inventes otras."}
    return {"clases_con_lugar": [], "alternativas": [], **fecha,
            "mensaje": f"Para {que} {motivo} y no hay lugar en otros días"
                       + (" para ese nivel" if nivel else "") + ". Contale eso con buena onda y ofrecele "
                       "pasarle la consulta al encargado. No inventes clases."}


PRECIO_DERIVADO = {"error": "Esta consulta ya se la pasaste al encargado. NO des ningún precio ni le "
                            "preguntes datos para un precio: decile solo que el encargado le responde."}


def _derivar_al_encargado(telefono: str, args: dict, texto: str) -> dict:
    """Temas que el agente no maneja: le llega al encargado con el tema y la consulta tal cual."""
    tema = str(args.get("tema") or "").strip()[:80] or "otro tema"
    # la consulta es el mensaje real del alumno; lo que resumió el modelo va solo si aporta
    consulta = (texto or "").strip()[:500]
    resumen = str(args.get("consulta") or "").strip()[:200]
    if resumen and planilla._norm(resumen) != planilla._norm(consulta):
        consulta = f"{consulta} (resumen: {resumen})" if consulta else resumen
    a = _alumno_por_telefono(telefono)
    quien = f"{a.nombre} ({telefono})" if a else telefono
    _notificar(f"Consulta para el encargado de {quien}. Tema: {tema}. Consulta: {consulta or '(sin detalle)'}",
               tipo="consulta_derivada")
    return {"ok": True,
            "decile": "Eso lo maneja el encargado: ya le pasé tu consulta y se comunica con vos.",
            "mensaje": "Contale solo eso, con buena onda. NO des precios, horarios, disponibilidad ni "
                       "plazos de este tema, ni prometas cuándo le responde. No le preguntes nada más "
                       "de este tema (ni modalidad, ni turno, ni personas)."}


def _estado_cuota(telefono: str) -> dict:
    """Siempre con el número que escribe, nunca con uno que diga el modelo."""
    a = _alumno_por_telefono(telefono)
    if not a:
        return {"encontrado": False,
                "mensaje": "No encuentro a ningún alumno con este número. Decile con buena onda que no lo "
                           "ubicás y ofrecele pasarle la consulta al encargado. No des montos ni datos de nadie."}
    mes = planilla._ahora().date().replace(day=1)
    cuota = db.session.query(db.func.coalesce(db.func.sum(CuotaMes.monto), 0)).filter(
        CuotaMes.alumno_id == a.id, CuotaMes.mes == mes).scalar()
    pagado = db.session.query(db.func.coalesce(db.func.sum(PagoCuota.monto), 0)).filter(
        PagoCuota.alumno_id == a.id, PagoCuota.mes == mes).scalar()
    nombre_mes = planilla.MESES[mes.month - 1].capitalize()
    if not cuota:
        return {"encontrado": True, "alumno": a.nombre, "mes": nombre_mes, "cuota_generada": False,
                "pagado": int(pagado),
                "mensaje": "La cuota de este mes todavía no está cargada. No inventes un monto: decile que el encargado se la confirma."}
    return {"encontrado": True, "alumno": a.nombre, "mes": nombre_mes, "cuota_generada": True,
            "cuota": int(cuota), "pagado": int(pagado), "debe": max(int(cuota) - int(pagado), 0),
            "a_favor": max(int(pagado) - int(cuota), 0)}


# ---------------------------------------------------------------- anotar en clase (escribe en Neon)
_RX_HORA = re.compile(r"(\d{1,2})(?:\s*[:.h]\s*(\d{2}))?")


def _parsear_hora(texto) -> tuple[int, int | None] | None:
    """'18:30' -> (18, 30), '10' o '10hs' -> (10, None)."""
    m = _RX_HORA.search(str(texto or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), (int(m.group(2)) if m.group(2) else None)
    if h > 23 or (mi is not None and mi > 59):
        return None
    return h, mi


def _datos_clase(c: Clase) -> dict:
    return {"clase_id": c.id, "dia": _NOMBRE_DIA[c.dia_semana],
            "hora": c.hora_inicio.strftime("%H:%M"), "nivel": c.nivel or "sin nivel"}


def _buscar_clase(args: dict, nivel: str) -> tuple[Clase | None, dict | None]:
    """Devuelve (clase, None) o (None, error para el modelo). Solo grupales activas."""
    base = Clase.query.filter(Clase.activa.is_(True), Clase.tipo == "grupal")
    clase_id = _entero(args.get("clase_id"))
    if clase_id:
        clase = base.filter(Clase.id == clase_id).first()
        if clase:
            return clase, None
        # id inventado o de otra cosa: pruebo con día y hora si vinieron

    dia = _DIAS.get(planilla._norm(args.get("dia")))
    hora = _parsear_hora(args.get("hora"))
    if dia is None or not hora:
        return None, {"error": "No sé a qué clase anotarlo. Preguntale día y hora (o buscá con "
                               "consultar_cupos) y volvé a llamar. NO le digas que quedó anotado."}

    candidatas = base.filter(Clase.dia_semana == dia).all()
    h, mi = hora

    def _de_hora(hh):
        return [c for c in candidatas
                if c.hora_inicio.hour == hh and (mi is None or c.hora_inicio.minute == mi)]

    clases = _de_hora(h) or (_de_hora(h + 12) if h < 12 else [])  # "a las 5" puede ser 17
    canonico = _nivel_canonico(nivel or "")
    if len(clases) > 1 and canonico:
        clases = [c for c in clases if _nivel_de_clase(c.nivel, canonico)] or clases
    if not clases:
        return None, {"error": "No hay ninguna clase grupal ese día a esa hora. NO lo anotaste. "
                               "Ofrecele buscar otra con consultar_cupos."}
    if len(clases) > 1:
        return None, {"error": "Hay más de una clase ese día y hora. Preguntale cuál (por nivel) y "
                               "volvé a llamar con el clase_id. NO lo anotaste todavía.",
                      "opciones": [_datos_clase(c) for c in clases]}
    return clases[0], None


def _esta_llena(clase: Clase, hoy) -> bool:
    # también mira más adelante: si ya hay gente que entra el 1 del mes, no la pisamos
    return cd.lleno_desde(clase, hoy)


def _anotar_en_clase(telefono: str, args: dict) -> dict:
    """Anota al que escribe (sale del número de WhatsApp, nunca de lo que diga el modelo).
    Idempotente: si ya está anotado no se duplica."""
    alumnos = _alumnos_con_telefono(telefono)
    if len(alumnos) > 1:
        return {"error": "Este número figura en más de un alumno. NO anotes a nadie: decile que "
                         "se lo pasás al encargado para que lo revise."}
    alumno = alumnos[0] if alumnos else None
    nivel = (args.get("nivel") or "").strip() or (alumno.categoria if alumno else "")

    clase, error = _buscar_clase(args, nivel)
    if error:
        return error
    datos = _datos_clase(clase)
    hoy = planilla._ahora().date()

    def _ya_anotado(a):
        return Inscripcion.query.filter(
            Inscripcion.clase_id == clase.id, Inscripcion.alumno_id == a.id,
            db.or_(Inscripcion.hasta.is_(None), Inscripcion.hasta > hoy),  # hasta = primer día que no va
        ).first() is not None

    ya_anotado = {"status": "ya_anotado", **datos,
                  "mensaje": "Ya está anotado en esa clase, no se anotó de nuevo. Si lo acabás de "
                             "anotar vos en esta charla, confirmale que quedó."}
    if alumno and _ya_anotado(alumno):
        return ya_anotado

    # el cupo lo miro antes de pedir el nombre: no tiene sentido registrarlo para una clase llena
    if _esta_llena(clase, hoy):
        otras = _consultar_cupos({"dia": datos["dia"], "nivel": nivel,
                                  "franja": FRANJA_POR_AMBITO.get(clase.ambito, "manana")})
        return {"status": "sin_cupo", **datos, "otras_opciones": otras.get("clases_con_lugar", []),
                "mensaje": "Esa clase está llena y NO lo anotaste. Contale con buena onda y ofrecele "
                           "las otras opciones; si no hay, proponele buscar otro día."}

    nuevo = False
    if not alumno:
        nombre = (args.get("nombre") or "").strip()
        if not nombre:
            return {"status": "falta_nombre", **datos,
                    "mensaje": "Este número todavía no es alumno y NO está anotado. Preguntale SOLO el "
                               "nombre y volvé a llamar anotar_en_clase con la misma clase y el nombre."}
        reg = _registrar_alumno(telefono, {"nombre": nombre, "categoria": nivel or clase.nivel or ""})
        if "error" in reg:
            return reg
        alumno = _alumno_por_telefono(telefono)
        if not alumno:
            return {"error": "No pude registrarlo. Decile que se lo pasás al encargado."}
        nuevo = reg.get("status") == "registrado"
        if _ya_anotado(alumno):
            return ya_anotado

    # bloqueo la clase y vuelvo a contar, por si dos se anotan a la vez (en SQLite no hace nada)
    db.session.query(Clase).filter(Clase.id == clase.id).with_for_update().first()
    if _esta_llena(clase, hoy):
        db.session.rollback()
        return {"status": "sin_cupo", **datos,
                "mensaje": "Justo se llenó esa clase y NO lo anotaste. Ofrecele buscar otra con consultar_cupos."}
    db.session.add(Inscripcion(clase_id=clase.id, alumno_id=alumno.id, desde=hoy))
    try:
        db.session.commit()
    except IntegrityError:  # el índice único de Postgres: otra llamada lo anotó recién
        db.session.rollback()
        return ya_anotado

    _notificar(f"{alumno.nombre} ({telefono}) se anotó por WhatsApp en la clase del "
               f"{datos['dia']} {datos['hora']} ({datos['nivel']})", tipo="inscripcion")
    resultado = {"status": "anotado", "alumno": alumno.nombre, **datos,
                 "mensaje": "Quedó anotado. Confirmale día y hora."}
    if nuevo:
        resultado["inscripcion_pago_unico"] = _inscripcion()
        resultado["mensaje"] += " Es alumno nuevo: contale que la inscripción es un pago único."
    return resultado


def _agendar_clase_suelta(telefono: str, args: dict) -> dict:
    clase = ClaseSuelta(
        telefono=telefono,
        tipo="particular",
        dia=args["dia"],
        horario=args["horario"],
        profesor=args.get("profesor"),
    )
    db.session.add(clase)
    db.session.commit()

    _notificar(
        f"Nueva clase particular agendada: {telefono}, {args['dia']} {args['horario']}"
        + (f" con {args.get('profesor')}" if args.get("profesor") else ""),
        tipo="clase_agendada",
    )
    return {"status": "agendada", "clase_id": clase.id}


def _cancelar_clase_suelta(telefono: str, args: dict) -> dict:
    dia = (args.get("dia") or "").strip().lower()

    query = ClaseSuelta.query.filter(
        ClaseSuelta.telefono == telefono,
        ClaseSuelta.estado != "cancelada",
    )
    if dia:
        query = query.filter(db.func.lower(ClaseSuelta.dia) == dia)

    clases = query.all()
    if not clases:
        return {"error": "No encontré ninguna clase particular agendada para cancelar."}
    if len(clases) > 1 and not dia:
        return {
            "error": "Tiene más de una clase agendada, preguntale cuál quiere cancelar (por día).",
            "clases": [{"dia": c.dia, "horario": c.horario} for c in clases],
        }

    clase = clases[0]
    clase.estado = "cancelada"
    db.session.commit()

    _notificar(f"Clase particular cancelada: {telefono}, {clase.dia} {clase.horario}", tipo="clase_cancelada")
    return {"status": "cancelada", "dia": clase.dia, "horario": clase.horario}


NOMBRES_PLANILLA = {
    t["function"]["name"]
    for t in planilla.TOOLS_PLANILLA_ALUMNO + planilla.TOOLS_PLANILLA_JEFE
}
SOLO_JEFE = {t["function"]["name"] for t in planilla.TOOLS_PLANILLA_JEFE}


_RE_PAGO = re.compile(
    r"pagu[eé]|\bpag[oó]\b|transfer[ií]|transfiri|deposit[eé]|"
    r"mand[eé] (la )?(plata|transferencia|comprobante)", re.I)
_RE_CORRIGE = re.compile(
    r"equivoq|confund|correg|quise decir|en realidad|me falt[oó]|me sobr[oó]", re.I)


def _pesos(n: float) -> str:
    return "$" + f"{int(n):,}".replace(",", ".")


def _responder_pago(telefono: str, texto: str) -> str | None:
    """Si el mensaje avisa o corrige un pago con monto, lo anota y responde sin pasar por el modelo."""
    montos = _montos_en(texto)
    if not montos:
        return None
    monto = montos[-1]  # si corrige, el último número es el bueno
    try:
        if _RE_CORRIGE.search(texto):
            r = planilla.ejecutar("corregir_comprobante", {"monto": str(int(monto))}, telefono)
            print(f"[pago] corregir_comprobante {int(monto)} -> {r}", flush=True)
            if r and r.get("ok"):
                return (f"Listo, corregí el monto: quedó anotado {_pesos(monto)}. "
                        "El encargado lo revisa y te confirma el pago.")
        if _RE_PAGO.search(texto):
            r = planilla.ejecutar("avisar_comprobante", {"monto": str(int(monto))}, telefono)
            print(f"[pago] avisar_comprobante {int(monto)} -> {r}", flush=True)
            if r and r.get("ok"):
                return (f"Anoté {_pesos(monto)}. Mandame también la foto o el PDF del "
                        "comprobante por acá así queda guardado. El encargado lo revisa "
                        "y te confirma el pago. ¡Gracias!")
    except Exception as e:
        print(f"[pago] error: {e!r}", flush=True)
        return "Perdón, no pude anotarlo en este momento. Avisale al encargado así lo revisa."
    return None


def _montos_en(texto: str) -> list[float]:
    montos = []
    for m in re.findall(r"\d[\d.,]*", texto or ""):
        n = planilla._a_numero(m)
        if n and n >= 1000:
            montos.append(n)
    return montos


def _monto_confiable(telefono: str, texto: str, propuesto) -> str:
    """El monto no se lo dejamos al modelo: sale de lo que escribió el alumno."""
    en_mensaje = _montos_en(texto)
    if en_mensaje:
        return str(int(en_mensaje[-1]))  # si corrige, el último número es el bueno
    # sin número en este mensaje: solo vale si el alumno ya lo dijo antes en la charla
    n = planilla._a_numero(propuesto)
    if n:
        dichos = [m for h in _historial(telefono) if h["role"] == "user"
                  for m in _montos_en(h["content"])]
        if n in dichos:
            return str(int(n))
    return ""


def _usar_planilla(nombre: str, args: dict, telefono: str, es_jefe: bool, texto: str = "") -> dict:
    if nombre in SOLO_JEFE and not es_jefe:
        return {"error": "No autorizado. Solo el encargado puede hacer esto."}
    if nombre in ("avisar_comprobante", "corregir_comprobante"):
        args = dict(args or {})
        elegido = _monto_confiable(telefono, texto, args.get("monto"))
        if str(args.get("monto") or "") != elegido:
            print(f"[monto] el modelo mandó {args.get('monto')!r}, uso {elegido!r}", flush=True)
        args["monto"] = elegido
    try:
        return planilla.ejecutar(nombre, args, telefono)
    except Exception as e:  # la planilla no tiene que tumbar al bot
        print(f"[planilla] error en {nombre}: {e!r}", flush=True)
        return {"error": "No pude acceder a la planilla en este momento. Decile que el encargado lo revisa."}


def _actualizar_categoria(args: dict, es_jefe: bool) -> dict:
    if not es_jefe:
        return {"error": "No autorizado. Solo el encargado puede hacer esto."}

    alumno = Alumno.query.filter(Alumno.nombre.ilike(f"%{args['alumno_nombre']}%")).first()
    if not alumno:
        return {"error": f"No encontré ningún alumno llamado '{args['alumno_nombre']}'"}

    nueva = args["nueva_categoria"]
    alumno.categoria = _nivel_canonico(nueva) or nueva
    db.session.commit()
    return {"status": "actualizado", "alumno": alumno.nombre, "categoria": alumno.categoria}


def _crear_cambio_pendiente(args: dict, es_jefe: bool) -> dict:
    """El encargado le propone algo a un alumno; queda esperando que el alumno conteste.
    Si es un cambio de días usa la misma estructura que pedir_cambio_dias."""
    if not es_jefe:
        return {"error": "No autorizado. Solo el encargado puede proponer cambios."}

    nombre = (args.get("alumno_nombre") or "").strip()
    alumno = Alumno.query.filter(Alumno.nombre.ilike(f"%{nombre}%")).first() if nombre else None
    if not alumno:
        return {"error": f"No encontré ningún alumno llamado '{nombre}'"}

    if not (args.get("dias_nuevos") or args.get("clase_ids")):
        propuesta = (args.get("propuesta") or "").strip()
        if not propuesta:
            return {"error": "Falta qué le propongo: los días nuevos (dias_nuevos) o el detalle en texto."}
        cambio = CambioPendiente(alumno_telefono=alumno.telefono, alumno_id=alumno.id, tipo="reasignacion",
                                 propuesta=propuesta, origen="encargado", espera="alumno",
                                 pedido_por="encargado")
        db.session.add(cambio)
        db.session.commit()
        return {"status": "propuesta creada", "cambio_id": cambio.id, "alumno": alumno.nombre}

    hoy = rec.hoy()
    fecha = cd.leer_fecha(args.get("desde"), hoy) or cd.primero_del_mes_siguiente(hoy)
    if fecha < hoy:
        return {"error": f"El {cd.fecha_corta(fecha)} ya pasó: el cambio tiene que arrancar de hoy en adelante."}
    armado, error = _armar_cambio(alumno, args, fecha)
    if error:
        return {**error, "mensaje": "NO se creó la propuesta. Contale esto al encargado con tus palabras."}
    precio, _ = cd.precio_de(armado["quedan"])
    cambio = cd.crear(alumno, armado["deja"], armado["nuevas"], fecha, origen="encargado",
                      espera="alumno", pedido_por="encargado", precio=precio)
    resultado = {"status": "propuesta creada", "cambio_id": cambio.id, "alumno": alumno.nombre,
                 "propuesta": cambio.propuesta}
    if precio is None:
        resultado["aviso"] = "No hay tarifa exacta para cómo le quedan las clases: la cuota la tenés que ver vos."
    return resultado


def _resolver_cambio_pendiente(telefono: str, args: dict) -> dict:
    cambio = _cambio_pendiente_de(telefono)
    if not cambio:
        return {"error": "No hay ningún cambio pendiente para vos"}

    acepta = args.get("decision") == "si_acepto"
    alumno = _alumno_por_telefono(telefono)
    nombre = alumno.nombre if alumno else telefono

    if acepta and cambio.tipo == "cambio_dias":
        # sigue pendiente, ahora del encargado: lo aplica desde el panel (vuelve a mirar el cupo)
        cambio.espera = "encargado"
        db.session.commit()
        _notificar(f"{nombre} aceptó el cambio de días: {cambio.propuesta} Falta aplicarlo en el panel.",
                   tipo="cambio_resuelto")
        return {"status": "aceptado", "propuesta": cambio.propuesta,
                "mensaje": "Aceptó. Decile que se lo pasás al encargado para que lo deje cargado. "
                           "NO digas que ya cambió."}

    cambio.estado = "aceptado" if acepta else "rechazado"
    if not acepta:
        cambio.motivo_rechazo = "no lo aceptó el alumno"
    cambio.resuelto_en = datetime.utcnow()
    db.session.commit()

    _notificar(f"{nombre} {cambio.estado} el cambio propuesto: {cambio.propuesta}", tipo="cambio_resuelto")
    return {"status": cambio.estado, "propuesta": cambio.propuesta}


# ---------------------------------------------------------------- cambio de días (lo pide el alumno)
# La lógica (cupos a fecha, precio, guardar) está en app/cambios_dias.py. Acá solo se traduce
# lo que dice el alumno y se arma el 'decile'. No toca inscripciones: lo aprueba el encargado.
def _dias_de(valor) -> list[int]:
    if isinstance(valor, str):
        valor = re.split(r"[,\s]+(?:y\s+)?", valor)
    if not isinstance(valor, list):
        return []
    return [d for d in (_DIAS.get(planilla._norm(v)) for v in valor) if d is not None]


def _ids_de(valor) -> list[int]:
    if not isinstance(valor, list):
        valor = [valor] if valor else []
    return [n for n in (_entero(v) for v in valor) if n]


def _filtro_nivel(alumno: Alumno):
    canonico = _nivel_canonico(alumno.categoria or "")
    if not canonico:
        return None
    return lambda c: not c.nivel or _nivel_de_clase(c.nivel, canonico)


def _opciones_txt(clases: list[Clase]) -> str:
    return ", ".join(f"{cd.texto_clase(c)} ({c.nivel or 'sin nivel'})" for c in clases)


def _armar_cambio(alumno: Alumno, args: dict, fecha: date) -> tuple[dict | None, dict | None]:
    """(armado, None) si está todo; (None, respuesta para el modelo) si falta algo o no hay lugar."""
    hora = _parsear_hora(args.get("hora")) if args.get("hora") else None
    r = cd.armar(alumno.id, fecha, _dias_de(args.get("dias_nuevos")), hora=hora,
                 dias_deja=_dias_de(args.get("dias_que_deja")) or None,
                 clase_ids=_ids_de(args.get("clase_ids")), nivel_ok=_filtro_nivel(alumno))
    st = r["status"]
    desde = f"desde el {cd.fecha_corta(fecha)}"
    nada = "NO quedó ningún pedido. "
    if st == "ok":
        return r, None
    if st == "sin_clases":
        return None, {"status": st,
                      "decile": f"No te encuentro con clases fijas {desde}, así que no tengo días para "
                                "cambiarte. Si querés te busco lugar para anotarte.",
                      "mensaje": nada + _RESPUESTA_TOOL}
    if st == "faltan_dias":
        return None, {"status": st, "mensaje": nada + "No sé a qué días quiere pasar: preguntale qué "
                                                      "días quiere venir y volvé a llamar."}
    if st == "no_tiene_dia":
        dias = " ni los ".join(_NOMBRE_DIA[d] for d in r["dias"])
        return None, {"status": st,
                      "decile": f"No te tengo anotado los {dias}. Hoy venís {cd.texto_clases(r['actuales'])}. "
                                "¿Cuáles querés cambiar?",
                      "mensaje": nada + _RESPUESTA_TOOL}
    if st == "elegir_hora":
        return None, {"status": st, "opciones": [_datos_clase(c) for c in r["opciones"]],
                      "decile": f"El {_NOMBRE_DIA[r['dia']]} {desde} tengo lugar en {_opciones_txt(r['opciones'])}. "
                                "¿Cuál te queda mejor?",
                      "mensaje": nada + "Cuando elija, volvé a llamar con los mismos datos y "
                                        "clase_ids=[el clase_id que eligió]."}
    if st == "sin_cupo":
        alts = r["alternativas"][:6]
        decile = f"El {_NOMBRE_DIA[r['dia']]} no hay lugar {desde}. "
        decile += (f"Con lugar tengo {_opciones_txt(alts)}. ¿Te sirve alguno?" if alts else
                   "Y en tu turno no me queda otro día con lugar: si querés le paso tu consulta al encargado.")
        return None, {"status": st, "alternativas": [_datos_clase(c) for c in alts], "decile": decile,
                      "mensaje": nada + "No hay lista de espera. Si elige una alternativa, volvé a llamar "
                                        "con esos días (o clase_ids=[el clase_id])."}
    return None, {"status": st,
                  "decile": f"Con eso te quedan los mismos días que ya tenés ({cd.texto_clases(r['actuales'])}), "
                            "no hay nada para cambiar.",
                  "mensaje": nada + _RESPUESTA_TOOL}


def _resumen_cambio(armado: dict, fecha: date) -> str:
    partes = []
    if armado["deja"]:
        partes.append(f"dejás {cd.texto_clases(armado['deja'])}")
    if armado["nuevas"]:
        partes.append(f"pasás a {cd.texto_clases(armado['nuevas'])}")
    return f"desde el {cd.fecha_corta(fecha)} " + " y ".join(partes)


def _pedir_cambio_dias(telefono: str, args: dict) -> dict:
    alumno, error = _elegir_alumno(telefono, args.get("alumno"))
    if error:
        return error

    hoy = rec.hoy()
    minima = cd.vigencia_minima(hoy)
    fecha = minima
    pedida = cd.leer_fecha(args.get("desde"), hoy)
    if pedida:
        pedida = pedida.replace(day=1)  # los cambios arrancan a principio de mes
        if pedida < minima:
            # ya pasó el plazo para ese mes: no se promete nada, lo ve el encargado
            _notificar(f"{alumno.nombre} ({telefono}) quiere cambiar de días desde el {cd.fecha_corta(pedida)}, "
                       f"fuera de plazo. Días que pidió: {', '.join(map(str, args.get('dias_nuevos') or [])) or '?'}",
                       tipo="cambio_dias")
            return {"status": "fuera_de_plazo",
                    "decile": f"El plazo para cambiar los días desde el {cd.fecha_corta(pedida)} ya pasó, así que "
                              "eso no te lo puedo confirmar yo. Ya le pasé tu pedido al encargado para que lo vea "
                              "y te escriba.",
                    "mensaje": "NO quedó ningún pedido y no prometas nada. " + _RESPUESTA_TOOL}
        fecha = pedida

    armado, error = _armar_cambio(alumno, args, fecha)
    if error:
        return error

    resumen = _resumen_cambio(armado, fecha)
    quedan = cd.texto_clases(armado["quedan"])
    precio, _ = cd.precio_de(armado["quedan"])
    if precio is None:
        # nunca inventar precios: sin tarifa exacta lo ve el encargado
        _notificar(f"{alumno.nombre} ({telefono}) quiere cambiar de días ({resumen}), pero no hay tarifa "
                   f"exacta para quedar con {quedan}. Lo tenés que ver vos.", tipo="cambio_dias")
        return {"status": "derivado",
                "decile": f"Para quedar con {quedan} no tengo un precio cargado, así que se lo paso al "
                          "encargado para que te confirme el cambio y la cuota.",
                "mensaje": "NO quedó ningún pedido y NO des ningún precio. " + _RESPUESTA_TOOL}

    que = f"{resumen}. Te quedarían {quedan} y la cuota pasa a {_pesos(precio)} por mes"
    if not (_si(args.get("confirmado")) and _fecha_ya_dicha(telefono, fecha)):
        return {"status": "confirmar", "vigente_desde": cd.fecha_corta(fecha), "cuota_nueva": precio,
                "decile": f"Te lo dejo así: {que}. ¿Lo confirmo? Después lo aprueba el encargado \U0001F60A",
                "mensaje": "Todavía NO quedó ningún pedido. Pasale el detalle tal cual, con la fecha. Si dice "
                           "que sí, volvé a llamar con los mismos datos y confirmado=true."}

    cambio = cd.crear(alumno, armado["deja"], armado["nuevas"], fecha, origen="alumno",
                      espera="encargado", pedido_por=telefono, precio=precio)
    _notificar(f"{alumno.nombre} pidió un cambio de días. {cambio.propuesta} Aprobalo o rechazalo en el panel.",
               tipo="cambio_dias")
    return {"status": "pendiente", "cambio_id": cambio.id,
            "decile": f"¡Listo! Le pasé tu pedido al encargado: {que}. Cuando lo apruebe te avisamos; "
                      "mientras tanto seguís con tus días de siempre.",
            "mensaje": "El pedido quedó PENDIENTE, no aprobado. " + _RESPUESTA_TOOL}


def _registrar_alumno(telefono: str, args: dict) -> dict:
    nombre = (args.get("nombre") or "").strip()

    if not nombre or nombre.startswith("[") or nombre.lower() in ("nombre", "name", "nombre del alumno"):
        return {
            "error": (
                "El nombre recibido no es válido (parece un placeholder). "
                "Preguntale de nuevo al alumno cuál es su nombre completo antes "
                "de volver a intentar registrar."
            )
        }

    existentes = _alumnos_con_telefono(telefono)
    if len(existentes) > 1:
        return {"error": "Este número ya figura en más de un alumno. No registres a nadie: "
                         "decile que se lo pasás al encargado."}
    if existentes:
        return {"status": "ya_registrado", "alumno": existentes[0].nombre}

    categoria_cruda = args.get("categoria", "")
    categoria = _nivel_canonico(categoria_cruda) or categoria_cruda

    alumno = Alumno(
        nombre=nombre,
        telefono=telefono,
        categoria=categoria,
        planilla="adultos",
    )
    db.session.add(alumno)
    db.session.commit()

    _notificar(f"Nuevo alumno registrado: {nombre} ({telefono}), categoría {categoria}", tipo="alta_alumno")
    return {"status": "registrado", "alumno": alumno.nombre}


# ---------------------------------------------------------------- faltas, recuperaciones y viajes
# Las reglas viven en app/recuperaciones.py. Acá solo se traduce lo que dice el alumno
# a alumno + clase + fecha, se pide que confirme la fecha y se arma un texto claro
# ('decile') para que el modelo no invente nada.
_RX_FECHA_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_RX_FECHA = re.compile(r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?!\d)")
_RESPUESTA_TOOL = ("Pasale al alumno el texto de 'decile' con tus palabras, en voseo, sin cambiar "
                   "fechas, horas ni condiciones. No agregues promesas.")


def _mes_nombre(f: date) -> str:
    return planilla.MESES[f.month - 1].lower()


def _fecha_corta(f: date) -> str:
    return f"{_NOMBRE_DIA[f.weekday()]} {f.day}/{f.month}"


def _hora_txt(clase: Clase) -> str:
    return clase.hora_inicio.strftime("%H:%M")


def _parsear_fecha(texto) -> tuple[date | None, int | None]:
    """'jueves', 'el jueves 12/11', '12/11', '2026-11-12', 'hoy', 'mañana' -> (fecha, día de la semana).
    fecha None si solo vino el día; los dos None si no se entiende."""
    t = planilla._norm(texto)
    hoy = rec.hoy()
    fecha = None
    m = _RX_FECHA_ISO.search(t)
    try:
        if m:
            fecha = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif (m := _RX_FECHA.search(t)):
            anio = int(m.group(3)) if m.group(3) else None
            if anio is not None and anio < 100:
                anio += 2000
            fecha = date(anio or hoy.year, int(m.group(2)), int(m.group(1)))
            if anio is None and fecha < hoy - timedelta(days=60):
                fecha = fecha.replace(year=hoy.year + 1)  # "5/1" dicho en noviembre es enero que viene
    except ValueError:
        return None, None
    dia = next((n for nombre, n in _DIAS.items() if re.search(rf"\b{nombre}\b", t)), None)
    if fecha is None and dia is None:
        if "pasado manana" in t:
            fecha = hoy + timedelta(days=2)
        elif "manana" in t:
            fecha = hoy + timedelta(days=1)
        elif "hoy" in t:
            fecha = hoy
    return fecha, dia


def _resolver_fecha(texto) -> tuple[date | None, bool, dict | None]:
    """Devuelve (fecha, vino_solo_el_dia, error). Solo el día -> el próximo (hoy cuenta)."""
    fecha, dia = _parsear_fecha(texto)
    if fecha is None and dia is None:
        return None, False, {"status": "falta_fecha",
                             "mensaje": "No entendí la fecha. NO registraste nada. Preguntale qué día "
                                        "(por ejemplo 'el jueves' o '12/11') y volvé a llamar."}
    if fecha and dia is not None and fecha.weekday() != dia:
        return None, False, {"status": "fecha_no_coincide",
                             "mensaje": f"El {fecha.day}/{fecha.month} no es {_NOMBRE_DIA[dia]}, es "
                                        f"{_NOMBRE_DIA[fecha.weekday()]}. NO registraste nada. Preguntale "
                                        "cuál de los dos es y volvé a llamar."}
    if fecha:
        return fecha, False, None
    hoy = rec.hoy()
    return hoy + timedelta(days=(dia - hoy.weekday()) % 7), True, None


def _fecha_ya_dicha(telefono: str, f: date) -> bool:
    """La fecha completa ya apareció en la charla (se la mostramos o la escribió él)."""
    mes = planilla._norm(_mes_nombre(f))
    rx = re.compile(rf"(?<!\d)0?{f.day}\s*/\s*0?{f.month}(?!\d)|\b{f.day} de {mes}\b")
    textos = Conversacion.query.filter(
        Conversacion.telefono == telefono, Conversacion.creado_en >= _inicio_sesion()).all()
    return any(rx.search(planilla._norm(c.contenido)) for c in textos)


def _falta_confirmar(telefono: str, args: dict, fechas: list[date], que: str) -> dict | None:
    """None si ya confirmó la fecha completa; si no, la respuesta que le pide confirmarla."""
    if _si(args.get("confirmado")) and all(_fecha_ya_dicha(telefono, f) for f in fechas):
        return None
    return {"status": "confirmar_fecha", "fecha_completa": que,
            "decile": f"¿Te referís al {que}? Confirmame así lo anoto \U0001F60A",
            "mensaje": f"Todavía NO registraste nada. Preguntale si es el {que}, escribiendo la fecha "
                       "tal cual. Cuando te diga que sí, volvé a llamar la tool con los mismos datos "
                       "y confirmado=true."}


def _elegir_alumno(telefono: str, nombre) -> tuple[Alumno | None, dict | None]:
    """Siempre por el número que escribe. Si el número es de varios, el nombre solo elige entre esos."""
    alumnos = _alumnos_con_telefono(telefono)
    if not alumnos:
        return None, {"status": "no_alumno",
                      "decile": "No encuentro ningún alumno con este número, así que no puedo anotarlo. "
                                "Si querés le paso tu consulta al encargado, o escribime desde el número "
                                "que tiene anotado la academia.",
                      "mensaje": "NO registraste nada. " + _RESPUESTA_TOOL}
    if len(alumnos) == 1:
        return alumnos[0], None
    palabras = set(planilla._norm(nombre).split())
    if palabras:
        elegidos = [a for a in alumnos if palabras <= set(planilla._norm(a.nombre).split())]
        if len(elegidos) == 1:
            return elegidos[0], None
    nombres = [a.nombre for a in alumnos]
    return None, {"status": "elegir_alumno", "alumnos": nombres,
                  "decile": f"Este número lo tengo con {' y '.join(nombres)}. ¿De quién me hablás?",
                  "mensaje": "NO registraste nada. Preguntale de cuál de ellos habla y volvé a llamar "
                             "la tool con alumno=<ese nombre>."}


def _clases_del_alumno_el(alumno_id: int, fecha: date) -> list[Clase]:
    clases = (Clase.query.join(Inscripcion, Inscripcion.clase_id == Clase.id)
              .filter(Inscripcion.alumno_id == alumno_id, Clase.activa.is_(True),
                      Clase.dia_semana == fecha.weekday())
              .order_by(Clase.hora_inicio).distinct().all())
    return [c for c in clases if rec.inscripto(alumno_id, c.id, fecha)]


def _dias_del_alumno(alumno_id: int) -> list[str]:
    hoy = rec.hoy()
    clases = (Clase.query.join(Inscripcion, Inscripcion.clase_id == Clase.id)
              .filter(Inscripcion.alumno_id == alumno_id, Clase.activa.is_(True))
              .order_by(Clase.dia_semana, Clase.hora_inicio).distinct().all())
    return [f"{_NOMBRE_DIA[c.dia_semana]} {_hora_txt(c)}" for c in clases
            if rec.inscripto(alumno_id, c.id, hoy + timedelta(days=(c.dia_semana - hoy.weekday()) % 7))]


def _texto_recupero(alumno_id: int, fecha: date, a_tiempo: bool) -> tuple[bool, str]:
    horas = rec.regla("aviso_horas") or 0
    tope = int(rec.regla("max_recuperaciones_mes") or 0)
    en_mes = f" en {_mes_nombre(fecha)}" if rec.regla("recupera_mismo_mes") else ""
    if not a_tiempo:
        return False, (f"Como avisaste con menos de {horas} hs, la falta queda anotada pero la "
                       "recuperación no entra en la regla. Si querés te la pido igual y la decide el encargado.")
    if tope and rec._usadas_en_mes(alumno_id, fecha) >= tope:
        return False, (f"Ya usaste {'tu recuperación' if tope == 1 else f'tus {tope} recuperaciones'} "
                       f"de {_mes_nombre(fecha)}, así que esta no entra en la regla. Si querés te la "
                       "pido igual y la decide el encargado.")
    return True, (f"Como avisaste a tiempo, la podés recuperar{en_mes}. Decime qué día y horario te "
                  "queda bien y me fijo si hay lugar.")


def _avisar_ausencia(telefono: str, args: dict) -> dict:
    alumno, error = _elegir_alumno(telefono, args.get("alumno"))
    if error:
        return error
    fecha, solo_dia, error = _resolver_fecha(args.get("fecha"))
    if error:
        return error

    clases = _clases_del_alumno_el(alumno.id, fecha)
    if solo_dia and clases and all(rec.inicio_clase(c, fecha) <= rec.ahora() for c in clases):
        # "el jueves" dicho un jueves después de la clase: es el que viene
        fecha += timedelta(days=7)
        clases = _clases_del_alumno_el(alumno.id, fecha)
    if not clases:
        dias = _dias_del_alumno(alumno.id)
        return {"status": "sin_clase", "dias_de_clase": dias,
                "decile": f"El {_fecha_corta(fecha)} no tenés clase"
                          + (f": tus clases son {', '.join(dias)}." if dias else ".")
                          + " ¿Me decís qué día es el que no venís?",
                "mensaje": "NO registraste nada. " + _RESPUESTA_TOOL}

    if len(clases) > 1:
        hora = _parsear_hora(args.get("horario"))
        if hora:
            clases = [c for c in clases if c.hora_inicio.hour in (hora[0], hora[0] + 12)
                      and (hora[1] is None or c.hora_inicio.minute == hora[1])] or clases
        if len(clases) > 1:
            horas = [_hora_txt(c) for c in clases]
            return {"status": "elegir_horario", "horarios": horas,
                    "decile": f"El {_fecha_corta(fecha)} tenés clase a las {' y a las '.join(horas)}. ¿A cuál no venís?",
                    "mensaje": "NO registraste nada. Preguntale el horario y volvé a llamar con horario."}
    clase = clases[0]
    que = f"{_fecha_corta(fecha)} a las {_hora_txt(clase)}"

    if rec.inicio_clase(clase, fecha) <= rec.ahora():
        return {"status": "ya_paso",
                "decile": f"La clase del {que} ya empezó o ya pasó, así que no la puedo anotar desde acá. "
                          "Si querés le paso al encargado que no pudiste ir.",
                "mensaje": "NO registraste nada. " + _RESPUESTA_TOOL}

    pedir = _falta_confirmar(telefono, args, [fecha], que)
    if pedir:
        return pedir

    try:
        aus, nueva = rec.avisar_ausencia(alumno.id, clase.id, fecha, origen="agente", motivo=args.get("motivo"))
        db.session.commit()
    except rec.ErrorRegla as e:
        db.session.rollback()
        return {"status": "no_registrada", "decile": f"No pude anotar la falta del {que} ({e}). Se lo paso al encargado.",
                "mensaje": "NO registraste la falta. " + _RESPUESTA_TOOL}
    except IntegrityError:  # otra llamada la cargó recién
        db.session.rollback()
        aus, nueva = rec.avisar_ausencia(alumno.id, clase.id, fecha, origen="agente")

    puede, texto = _texto_recupero(alumno.id, fecha, aus.a_tiempo)
    if nueva:
        _notificar(f"{alumno.nombre} avisó por WhatsApp que falta el {que} "
                   f"({'a tiempo' if aus.a_tiempo else 'tarde'})", tipo="ausencia")
    inicio = "Listo, anoté que" if nueva else "Ya lo tenía anotado:"
    return {"status": "registrada" if nueva else "ya_estaba_registrada",
            "alumno": alumno.nombre, "fecha": que, "a_tiempo": bool(aus.a_tiempo), "puede_recuperar": puede,
            "decile": f"{inicio} el {que} no venís. {texto}",
            "mensaje": _RESPUESTA_TOOL}


_MOTIVOS_ALUMNO = [
    (re.compile(r"no tiene una falta"), lambda m: "no encontré una falta tuya anotada para recuperar"),
    (re.compile(r"la falta del (\S+) fue sin aviso"), lambda m: f"la falta del {m.group(1)} fue sin aviso o con aviso tarde"),
    (re.compile(r"la falta es del (\S+) y quiere recuperar en otro mes"),
     lambda m: f"la falta es del {m.group(1)} y la recuperación cae en otro mes"),
    (re.compile(r"ya tiene (\d+) recuperaci.n\(es\) ese mes y el tope es (\d+)"),
     lambda m: f"ya usaste las recuperaciones de ese mes (el máximo es {m.group(2)})"),
]


def _motivos_para_alumno(fuera_de_regla: str | None) -> str:
    """Los motivos de recuperaciones.py están en tercera persona (son para el encargado)."""
    partes = []
    for parte in (fuera_de_regla or "").split("; "):
        for rx, armar in _MOTIVOS_ALUMNO:
            m = rx.search(parte)
            if m:
                partes.append(armar(m))
                break
        else:
            if parte:
                partes.append(parte)
    return " y ".join(partes)


def _otras_con_lugar(clase: Clase, fecha: date) -> list[str]:
    otras = Clase.query.filter(Clase.activa.is_(True), Clase.tipo == "grupal",
                               Clase.dia_semana == fecha.weekday(), Clase.id != clase.id).all()
    return [f"{_hora_txt(c)} ({c.nivel or 'sin nivel'})" for c in sorted(otras, key=lambda c: c.hora_inicio)
            if rec.inicio_clase(c, fecha) > rec.ahora() and rec.lugares_libres(c, fecha) > 0]


def _recuperacion_ya_pedida(alumno: Alumno, clase: Clase, fecha: date, que: str) -> dict | None:
    recu = RecuperacionClase.query.filter(
        RecuperacionClase.alumno_id == alumno.id, RecuperacionClase.clase_id == clase.id,
        RecuperacionClase.fecha == fecha, RecuperacionClase.estado.in_(rec.ACTIVAS)).first()
    if not recu:
        return None
    if recu.estado == "confirmada":
        texto = f"Ya tenés confirmada la recuperación del {que}. ¡Te esperamos! \U0001F3BE"
    else:
        texto = f"Ya tenés pedida la recuperación del {que}: está pendiente, la ve el encargado y te avisa."
    return {"status": "ya_pedida", "estado": recu.estado, "fecha": que, "decile": texto,
            "mensaje": "No se pidió de nuevo. " + _RESPUESTA_TOOL}


def _pedir_recuperacion(telefono: str, args: dict) -> dict:
    alumno, error = _elegir_alumno(telefono, args.get("alumno"))
    if error:
        return error

    texto_dia = f"{args.get('dia') or args.get('dia_nuevo') or ''} {args.get('fecha') or ''}"
    horario = args.get("horario") or args.get("horario_nuevo")
    fecha, dia = _parsear_fecha(texto_dia)
    if dia is None and fecha:
        dia = fecha.weekday()
    if fecha and dia is not None and fecha.weekday() != dia:
        return _resolver_fecha(texto_dia)[2]
    if dia is None and not _entero(args.get("clase_id")):
        return {"status": "falta_dia", "mensaje": "NO pediste nada. Preguntale qué día y a qué hora quiere "
                                                  "recuperar y volvé a llamar."}

    clase, error = _buscar_clase({"clase_id": args.get("clase_id"), "hora": horario,
                                  "dia": _NOMBRE_DIA[dia] if dia is not None else ""}, alumno.categoria or "")
    if error:
        if error.get("opciones"):
            return {"status": "elegir_clase", "opciones": error["opciones"],
                    "mensaje": "NO pediste nada. Hay más de una clase ese día y hora: preguntale cuál (por "
                               "nivel) y volvé a llamar con el clase_id."}
        return {"status": "sin_clase",
                "decile": "No encuentro una clase grupal ese día a esa hora. ¿Querés que te busque otro horario?",
                "mensaje": "NO pediste nada. Si quiere, buscá opciones con consultar_cupos. " + _RESPUESTA_TOOL}

    if fecha is None:
        hoy = rec.hoy()
        fecha = hoy + timedelta(days=(clase.dia_semana - hoy.weekday()) % 7)
        if rec.inicio_clase(clase, fecha) <= rec.ahora():
            fecha += timedelta(days=7)
    elif fecha.weekday() != clase.dia_semana:
        return {"status": "fecha_no_coincide",
                "mensaje": f"Esa clase es los {_NOMBRE_DIA[clase.dia_semana]} y el {fecha.day}/{fecha.month} es "
                           f"{_NOMBRE_DIA[fecha.weekday()]}. NO pediste nada. Preguntale qué día quiere."}
    que = f"{_fecha_corta(fecha)} a las {_hora_txt(clase)}"

    ya = _recuperacion_ya_pedida(alumno, clase, fecha, que)
    if ya:
        return ya
    # la llena la aviso antes de confirmar la fecha: no tiene sentido hacerle confirmar algo imposible
    if rec.inicio_clase(clase, fecha) > rec.ahora() and rec.lugares_libres(clase, fecha) <= 0:
        return _clase_llena(clase, fecha, que)

    pedir = _falta_confirmar(telefono, args, [fecha], que)
    if pedir:
        return pedir

    # bloqueo la clase para que dos no se metan en el último lugar (en SQLite no hace nada)
    db.session.query(Clase).filter(Clase.id == clase.id).with_for_update().first()
    try:
        recu = rec.pedir_recuperacion(alumno.id, clase.id, fecha, pedida_por="agente")
        db.session.commit()
    except rec.ErrorRegla as e:
        db.session.rollback()
        motivo = str(e)
        if "llena" in motivo:
            return _clase_llena(clase, fecha, que)
        if "Ya tiene una recuperación" in motivo:
            return _recuperacion_ya_pedida(alumno, clase, fecha, que) or {"status": "ya_pedida", "mensaje": motivo}
        if "clase fija" in motivo or "Ya está en esa clase" in motivo:
            texto = f"El {que} ya estás en esa clase, así que no hace falta recuperar ahí. ¿Querés otro día u horario?"
        elif "ya pasó" in motivo:
            texto = f"La clase del {que} ya empezó o ya pasó. ¿Querés otro día u horario?"
        else:
            texto = f"No pude pedir la recuperación del {que}. Se lo paso al encargado para que lo vea."
        return {"status": "no_pedida", "decile": texto, "mensaje": "NO pediste nada. " + _RESPUESTA_TOOL}

    _notificar(f"{alumno.nombre} pidió por WhatsApp recuperar el {que}: {recu.estado}"
               + (f" ({recu.fuera_de_regla})" if recu.fuera_de_regla else ""), tipo="recuperacion")
    if recu.estado == "confirmada":
        return {"status": "confirmada", "alumno": alumno.nombre, "fecha": que,
                "decile": f"¡Listo! Quedó confirmada tu recuperación el {que}. ¡Te esperamos! \U0001F3BE",
                "mensaje": "Quedó CONFIRMADA. " + _RESPUESTA_TOOL}
    motivo = _motivos_para_alumno(recu.fuera_de_regla)
    return {"status": "pendiente", "alumno": alumno.nombre, "fecha": que, "motivo": motivo,
            "decile": f"Te dejé pedida la recuperación del {que}, pero queda pendiente porque {motivo}. "
                      "Lo ve el encargado y te avisa si se puede.",
            "mensaje": "Quedó PENDIENTE, NO confirmada: no digas que tiene lugar ni que se va a aprobar. "
                       + _RESPUESTA_TOOL}


def _clase_llena(clase: Clase, fecha: date, que: str) -> dict:
    otras = _otras_con_lugar(clase, fecha)
    texto = f"Uh, la clase del {que} está llena."
    texto += (f" Ese mismo día hay lugar a las {', '.join(otras)}. ¿Te sirve alguna?" if otras
              else " ¿Querés probar otro día u horario?")
    return {"status": "clase_llena", "otras_con_lugar": otras, "decile": texto,
            "mensaje": "NO pediste nada, la clase está llena. " + _RESPUESTA_TOOL}


def _avisar_viaje(telefono: str, args: dict) -> dict:
    alumno, error = _elegir_alumno(telefono, args.get("alumno"))
    if error:
        return error
    desde, _, error = _resolver_fecha(args.get("desde"))
    if error:
        return error
    hasta, solo_dia, error = _resolver_fecha(args.get("hasta"))
    if error:
        return error
    if solo_dia:
        while hasta < desde:  # "del 20/11 al martes": el martes después de la ida
            hasta += timedelta(days=7)
    if hasta < desde:
        return {"status": "fechas_al_reves",
                "mensaje": "La vuelta quedó antes que la ida. NO registraste nada. Preguntale de nuevo las fechas."}
    if hasta < rec.hoy():
        return {"status": "ya_paso", "decile": "Esas fechas ya pasaron, así que no lo puedo anotar desde acá. "
                                               "Si querés se lo paso al encargado.",
                "mensaje": "NO registraste nada. " + _RESPUESTA_TOOL}
    que = f"{_fecha_corta(desde)} al {_fecha_corta(hasta)} inclusive"

    pedir = _falta_confirmar(telefono, args, [desde, hasta], "viaje del " + que)
    if pedir:
        return pedir

    try:
        rec.crear_lapso(alumno.id, desde, hasta, motivo=args.get("motivo") or "viaje", origen="agente")
        db.session.commit()
    except rec.ErrorRegla as e:
        db.session.rollback()
        if "se pisa" in str(e):
            igual = AusenciaLapso.query.filter(
                AusenciaLapso.alumno_id == alumno.id, AusenciaLapso.estado != "cancelado",
                AusenciaLapso.desde == desde, AusenciaLapso.hasta == hasta).first()
            if igual:
                estado = "ya está confirmado" if igual.estado == "confirmado" else "está pendiente de que lo confirme el encargado"
                return {"status": "ya_cargado", "estado": igual.estado,
                        "decile": f"Ya tenía anotado tu viaje del {que}, {estado}.",
                        "mensaje": "No se cargó de nuevo. " + _RESPUESTA_TOOL}
            texto = (f"Ya tenés otro viaje anotado que se cruza con el {que}. "
                     "Se lo paso al encargado para que lo acomode.")
        else:
            texto = f"No pude anotar el viaje del {que}. Se lo paso al encargado."
        return {"status": "no_registrado", "decile": texto, "mensaje": "NO registraste nada. " + _RESPUESTA_TOOL}

    _notificar(f"{alumno.nombre} avisó por WhatsApp un viaje del {que}. Falta confirmarlo en el panel.",
               tipo="viaje")
    return {"status": "pendiente", "alumno": alumno.nombre, "fecha": que,
            "decile": f"Listo, le pasé al encargado tu viaje del {que}. Queda pendiente hasta que él lo "
                      "confirme y te avisa. ¡Buen viaje! ✈️",
            "mensaje": "Quedó PENDIENTE de confirmar por el encargado. " + _RESPUESTA_TOOL}


def _dar_de_baja(telefono: str, args: dict) -> dict:
    alumno = _alumno_por_telefono(telefono)
    if not alumno:
        return {"error": "No encontré tu registro como alumno."}

    alumno.estado = "baja"
    alumno.motivo_baja = args["motivo"]
    db.session.commit()

    _notificar(f"{alumno.nombre} se dio de baja. Motivo: {args['motivo']}", tipo="baja_alumno")
    return {"status": "baja registrada", "alumno": alumno.nombre}


def _pausar_bot(args: dict, es_jefe: bool) -> dict:
    if not es_jefe:
        return {"error": "No autorizado."}

    alumno = Alumno.query.filter(Alumno.nombre.ilike(f"%{args['alumno_nombre']}%")).first()
    if not alumno:
        return {"error": f"No encontré ningún alumno llamado '{args['alumno_nombre']}'"}

    estado = EstadoChat.query.filter_by(telefono=alumno.telefono).first()
    if not estado:
        estado = EstadoChat(telefono=alumno.telefono)
        db.session.add(estado)
    estado.modo = "humano"
    db.session.commit()
    return {"status": "pausado", "alumno": alumno.nombre}


def _reanudar_bot(args: dict, es_jefe: bool) -> dict:
    if not es_jefe:
        return {"error": "No autorizado."}

    alumno = Alumno.query.filter(Alumno.nombre.ilike(f"%{args['alumno_nombre']}%")).first()
    if not alumno:
        return {"error": f"No encontré ningún alumno llamado '{args['alumno_nombre']}'"}

    estado = EstadoChat.query.filter_by(telefono=alumno.telefono).first()
    if estado:
        estado.modo = "bot"
        db.session.commit()
    return {"status": "reanudado", "alumno": alumno.nombre}