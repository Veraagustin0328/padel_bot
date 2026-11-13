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
from app import contactos
from app import niveles as niveles_mod
from app.cuotas import (
    DIAS_PROMO_2X1, FRANJA_POR_AMBITO, HEAD_COACH_ANTES_QUE_PROMO, HORA_HEAD_COACH_DESDE, HORA_HEAD_COACH_HASTA,
    HORA_PROMO_DESDE, HORA_PROMO_HASTA, cargar_tarifas, precio_bucket,
)
from app.models_plataforma import Profesor
from app.models_tarifas import FRANJA_HEAD_COACH
from app.models_academia import AusenciaLapso, Clase, ConfigAcademia, Inscripcion, RecuperacionClase
from app.models_cuotas import CuotaMes, PagoCuota
from app.models import (
    ClaseSuelta, Conversacion, Alumno,
    CambioPendiente, Notificacion,
)

MAX_HISTORIAL = 10
SESION_HORAS = 24

DATOS_DE_PAGO = (
    "Alias: academiaarenapadel. Se paga por transferencia a ese alias. "
    "Después el alumno te avisa por acá que transfirió, vos lo anotás y "
    "el encargado confirma el pago."
)

# ---------------------------------------------------------------- niveles
# las formas de cada nivel viven en app/niveles.py (las usa también el panel)
_nivel_canonico = niveles_mod.nivel_canonico


# ---------------------------------------------------------------- precios
# Los precios salen de la tabla tarifas (la misma que usa el panel para las cuotas).
# Acá solo está cómo se traduce modalidad + turno del agente a franja + tipo de tarifa.
INSCRIPCION_DEFAULT = 25000  # si no está en config_academia; se cobra una sola vez

# (modalidad, turno) -> (franja, tipo de tarifa, personas fijas o None si las pide, pide veces, descripción)
# Igual que bucket_de en app/cuotas.py: el grupal busca la tarifa de academia de su franja.
# Si no hay (hoy la tarde), no se da precio y se deriva al encargado; nunca se cobra como particular.
BUCKETS_PRECIO = {
    ("academia", "manana"): ("manana", "academia", 0, True,
                             "Modo Academia, mañana (7 a 12 hs). Los profes arman los grupos según el nivel."),
    ("academia", "tarde"): ("tarde", "academia", 0, True,
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
    "consultar_cupos YA con ese día (y el turno SOLO si lo dijo). Si ya es alumno, NO le "
    "preguntes el nivel: lo pone el sistema. Si NO es alumno, primero preguntale el nivel "
    "(más abajo te explico cómo). No preguntes turno ni hora antes de consultar. El sábado "
    "es siempre a la mañana: nunca preguntes el turno del sábado.\n"
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
    "el nombre y apenas te lo diga llamá anotar_en_clase con la clase, ese nombre "
    "y el nivel que te dijo.\n"
    "- Si anotar_en_clase te dice que la clase es de otro nivel, preguntale si quiere que "
    "lo consultes con el encargado. Si dice que sí, llamá derivar_al_encargado con "
    "tema='clase de otro nivel' y en consulta la clase (día, hora y nivel) y su nivel.\n"
    "- Si quiere cancelar una clase particular que ya tenía, usá "
    "cancelar_clase_suelta (con el día si tiene más de una).\n\n"
    "Temas:\n"
    "- Vos manejás: clases grupales y particulares, lugar y horarios, anotarse, precios de "
    "las clases, cuotas y pagos, comprobantes de pago, faltas y recuperaciones, cambios de "
    "días y avisos de viaje. Eso lo resolvés con tus tools: NO lo derives.\n"
    "- Alquiler o reserva de canchas NO lo maneja la academia, lo maneja el club: llamá "
    "contacto_club y contale solo lo que diga 'decile'. NO lo derives al encargado, NO "
    "inventes números de teléfono y NUNCA des precios, horarios ni disponibilidad de canchas.\n"
    "- Para CUALQUIER otro tema (venta o alquiler de paletas o pelotas, "
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
    "- Si avisar_comprobante te pide elegir de quién es el pago, preguntale con el texto de "
    "'decile' y volvé a llamarla con alumno=<el nombre> o alumno='los dos'.\n"
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
    """Todos los alumnos de este número (los contactos: propio, padre, madre, tutor)."""
    return contactos.alumnos_de_telefono(telefono)


def _alumno_por_telefono(telefono: str) -> Alumno | None:
    """El único del número, o el que quedó elegido en la charla si es de varios. Si no, ninguno."""
    alumnos = _alumnos_con_telefono(telefono)
    if len(alumnos) == 1:
        return alumnos[0]
    return contactos.alumno_activo(telefono, alumnos, SESION_HORAS) if alumnos else None


# ---- nombres: "Sofi" encuentra a "Sofía Pérez", y el apellido compartido no sirve para elegir
def _palabras(texto) -> list[str]:
    return [p for p in planilla._norm(texto).split() if len(p) >= 3]


def _menciona(palabra: str, token: str) -> bool:
    return palabra == token or (len(palabra) >= 4 and token.startswith(palabra))


def _mencionados(texto, alumnos: list[Alumno]) -> list[Alumno]:
    """Los alumnos nombrados en el texto, mirando solo las palabras que los distinguen entre sí."""
    tokens = {a.id: set(_palabras(a.nombre)) for a in alumnos}
    palabras = _palabras(texto)
    salida = []
    for a in alumnos:
        otros = set().union(*(t for i, t in tokens.items() if i != a.id))
        propios = tokens[a.id] - otros
        if any(_menciona(p, t) for p in palabras for t in propios):
            salida.append(a)
    return salida


def _es_otro_alumno(nombre, alumnos: list[Alumno]) -> bool:
    """El nombre (la primera palabra) no se parece a ninguno de los del número: es otra persona."""
    palabras = _palabras(nombre)
    return bool(palabras) and not any(_menciona(palabras[0], t) for a in alumnos for t in _palabras(a.nombre))


def _detectar_alumno_en_texto(telefono: str, texto: str) -> None:
    """Si el número es de varios y el mensaje nombra a uno solo, pasa a ser el alumno activo."""
    alumnos = _alumnos_con_telefono(telefono)
    if len(alumnos) < 2:
        return
    nombrados = _mencionados(texto, alumnos)
    if len(nombrados) == 1:
        contactos.fijar_alumno_activo(telefono, nombrados[0].id)


def _nombres(alumnos: list[Alumno]) -> str:
    nombres = [a.nombre for a in alumnos]
    return ", ".join(nombres[:-1]) + " y " + nombres[-1] if len(nombres) > 1 else "".join(nombres)


def _nota_registro(telefono: str) -> str:
    alumnos = _alumnos_con_telefono(telefono)
    if not alumnos:
        return (
            "Este número NO está registrado todavía como alumno. Lo PRIMERO, antes de ofrecerle "
            "o buscarle clases, es preguntarle en una sola frase su nivel de juego con ejemplos "
            "y si quiere clase grupal o particular, por ejemplo: 'Decime tu nivel de juego (por "
            "ejemplo 8va, 7ma, 6ta...) y si buscás clase grupal o particular'. Sin el nivel NO "
            "llames consultar_cupos ni le ofrezcas nada. Si ya lo dijo en la charla, no lo vuelvas "
            "a preguntar.\n"
            "- Grupal: con el nivel llamá consultar_cupos con el día (si no dijo día, preguntale "
            "cuál le queda mejor) y el nivel, y proponele una clase de las que vinieron, por "
            "ejemplo 'Tengo el miércoles a las 10, ¿te sirve?'. Cuando confirme, pedile el nombre "
            "y llamá anotar_en_clase con la clase, el nombre y el nivel que dijo, que lo registra "
            "y lo anota.\n"
            "- Particular: seguí como siempre con agendar_clase_suelta."
        )
    otro = ("Si quiere anotar a otra persona que no es ninguno de estos (por ejemplo otro hijo o hija), "
            "llamá anotar_en_clase con nombre=<el nombre que te dijo>: la tool se lo pasa al encargado.")
    if len(alumnos) == 1:
        return f"Este número YA está registrado como alumno: {alumnos[0].nombre}. No hace falta registrarlo. " + otro
    nota = (f"Este número es contacto de varios alumnos: {_nombres(alumnos)} (escribe el papá, la mamá o "
            "un tutor). No hace falta registrar a nadie. " + otro)
    activo = contactos.alumno_activo(telefono, alumnos, SESION_HORAS)
    if activo:
        nota += (f" Ahora están hablando de {activo.nombre}: las tools ya lo usan a él o ella, salvo que "
                 "nombre a otro.")
    else:
        nota += (" Si pregunta o pide algo de uno de ellos y no queda claro de cuál, preguntale de quién "
                 "habla antes de llamar la tool.")
    return nota


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
    if not es_jefe:
        _detectar_alumno_en_texto(telefono, texto)  # si nombra a uno de los hijos, queda ese

    # Avisos de pago: los resuelve el código, no el modelo (es plata)
    if not es_jefe:
        respuesta_pago = _responder_de_quien(telefono, texto) or _responder_pago(telefono, texto)
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
        varios = len(_alumnos_con_telefono(telefono)) > 1
        pendientes = _cambios_pendientes_de(telefono)
        if pendientes:
            detalle = "; ".join(
                f"id={c.id}" + (f", de {_nombre_de(c)}" if varios else "") + f": '{c.propuesta}'"
                for c in pendientes)
            mensajes.append({
                "role": "system",
                "content": (
                    f"IMPORTANTE - ACCIÓN OBLIGATORIA: hay {'cambios pendientes' if len(pendientes) > 1 else 'un cambio pendiente'} "
                    f"sin resolver ({detalle}). "
                    "SIN IMPORTAR lo que diga en su mensaje, tu respuesta DEBE "
                    "mencionar esta propuesta y preguntarle si la acepta, ANTES de "
                    "cualquier otra cosa."
                    + (" Cuando conteste, usá resolver_cambio_pendiente con el cambio_id que corresponde."
                       if len(pendientes) > 1 else "")
                ),
            })
        for alumno, pedido in _pedidos_propios_de(telefono):
            de_quien = f" para {alumno.nombre}" if varios else ""
            mensajes.append({
                "role": "system",
                "content": (
                    f"Ya hay un pedido de cambio de días{de_quien} que espera la aprobación del "
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
    # lo mismo si es de canchas: eso lo cobra el club, no hay precio nuestro
    del_club = any(re.sub(r"[^A-Za-z_]", "", tc.function.name or "") == "contacto_club"
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
            resultado = _consultar_cupos_de(telefono, {"dia": args.get("dia"), "nivel": args.get("nivel_juego")})
        elif nombre == "consultar_precio":
            resultado = (PRECIO_CLUB if del_club else PRECIO_DERIVADO if derivada
                         else _consultar_precio(args))
        elif nombre == "consultar_cupos":
            resultado = _consultar_cupos_de(telefono, args)  # el nivel del alumno lo pone el código
        elif nombre == "contacto_club":
            resultado = _contacto_club()
        elif nombre == "derivar_al_encargado":
            # si el modelo igual deriva algo de canchas, va al club y no le llega al encargado
            if es_tema_club(args.get("tema"), args.get("consulta"), texto):
                resultado = _contacto_club()
            else:
                resultado = _derivar_al_encargado(telefono, args, texto)
        elif nombre == "anotar_en_clase":
            resultado = _anotar_en_clase(telefono, args)  # el alumno sale del número, nunca de args
        elif nombre == "estado_cuota":
            resultado = _estado_cuota(telefono, args)  # del número que escribe; args solo elige entre sus hijos
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
    return contactos.esta_pausado(telefono)  # por tel10 y con vencimiento


def _guardar_mensaje(telefono: str, rol: str, contenido: str) -> None:
    db.session.add(Conversacion(telefono=telefono, rol=rol, contenido=contenido))
    db.session.commit()


# ---------------------------------------------------------------- nombre de tool mal escrito
# Solo las de lectura se pueden adivinar: si le pifia, no se rompe nada.
# Las que escriben (anotar, ausencias, recuperaciones, cambios, comprobantes...) nunca se adivinan.
TOOLS_LECTURA = {"consultar_cupos", "consultar_precio", "estado_cuota", "consultar_estado_pago", "contacto_club"}
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


def _notificar(mensaje: str, tipo: str, telefono: str = None, tema: str = None) -> None:
    # telefono y tema solo los pasan las que van a la solapa Consultas
    db.session.add(Notificacion(mensaje=mensaje, tipo=tipo, telefono=telefono,
                                tema=(tema or None) and tema[:80]))
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


def _cambios_pendientes_de(telefono: str) -> list[CambioPendiente]:
    """Los que esperan respuesta de quien escribe, de todos los alumnos del número (más nuevo primero).
    Los viejos sin alumno_id se buscan por los últimos 10 dígitos del teléfono guardado."""
    t = planilla._tel(telefono)
    if not t:
        return []
    ids = {a.id for a in _alumnos_con_telefono(telefono)}
    # solo los que esperan la respuesta del alumno (los viejos no tienen 'espera')
    pendientes = (
        CambioPendiente.query.filter_by(estado="pendiente")
        .filter(db.or_(CambioPendiente.espera.is_(None), CambioPendiente.espera == "alumno"))
        .order_by(CambioPendiente.creado_en.desc(), CambioPendiente.id.desc())
        .all()
    )
    return [c for c in pendientes
            if c.alumno_id in ids or (c.alumno_id is None and planilla._tel(c.alumno_telefono) == t)]


def _nombre_de(cambio: CambioPendiente) -> str:
    alumno = db.session.get(Alumno, cambio.alumno_id) if cambio.alumno_id else None
    return alumno.nombre if alumno else (cambio.alumno_telefono or "?")


def _pedidos_propios_de(telefono: str) -> list[tuple[Alumno, CambioPendiente]]:
    """El cambio de días que pidió cada alumno del número y todavía no resolvió el encargado."""
    salida = []
    for alumno in _alumnos_con_telefono(telefono):
        pedidos = cd.pendientes_del_alumno(alumno.id, espera="encargado")
        if pedidos:
            salida.append((alumno, pedidos[0]))
    return salida


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


def _fuera_de_head_coach(args: dict) -> bool:
    """True solo si el alumno dijo una hora que no entra en la franja del head coach (7 a 12)."""
    m = re.match(r"\s*(\d{1,2})", str(args.get("hora") or ""))
    return bool(m) and not (HORA_HEAD_COACH_DESDE <= int(m.group(1)) < HORA_HEAD_COACH_HASTA)


def _bucket_head_coach():
    """Como BUCKETS_PRECIO, con el nombre del profe sacado de la base. None si nadie está marcado."""
    profe = Profesor.query.filter(Profesor.es_head_coach.is_(True), Profesor.activo.is_(True)).first()
    if not profe:
        return None
    return (FRANJA_HEAD_COACH, "particular", None, True,
            f"Clase particular con {profe.nombre}, el Head Coach, de mañana "
            f"({HORA_HEAD_COACH_DESDE} a {HORA_HEAD_COACH_HASTA} hs). El alumno decide cómo formar el grupo.")


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

    # el head coach tiene precio propio solo en particulares: el Modo Academia sale igual con cualquier profe
    if head_coach and modalidad == "academia":
        head_coach = False
    # PROVISORIO (falta confirmar con la dueña): si pide las dos cosas, gana lo que diga HEAD_COACH_ANTES_QUE_PROMO
    if head_coach and promo:
        if HEAD_COACH_ANTES_QUE_PROMO:
            promo = False
        else:
            head_coach = False

    # la promo y el head coach son siempre particulares de mañana
    if promo or head_coach:
        modalidad = modalidad or "particular"
        turno = turno or "manana"
    if head_coach and (turno != "manana" or _fuera_de_head_coach(args)):
        return _al_encargado(f"El head coach tiene precio propio solo en particulares de mañana "
                             f"({HORA_HEAD_COACH_DESDE} a {HORA_HEAD_COACH_HASTA} hs) y esto no entra.")
    if promo:
        if turno != "manana" or modalidad != "particular" or _fuera_de_promo(args):
            return {"error": "La promo 2x1 es solo lunes, miércoles y viernes de 9 a 12 hs, y lo que pidió "
                             "el alumno no entra. Contale eso con buena onda y, si quiere ese horario igual, "
                             "consultá de nuevo con modalidad particular, turno mañana y 2 personas, sin promo_2x1."}

    if head_coach:
        bucket = _bucket_head_coach()
        if bucket is None:
            return _al_encargado("No hay ningún profe marcado como head coach.")
        franja, tipo_tarifa, personas_fijas, pide_veces, descripcion = bucket
    elif modalidad and turno and not promo:
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
    # con el head coach, la prioridad la marca HEAD_COACH_ANTES_QUE_PROMO (provisorio)
    if ((modalidad, turno, personas) == ("particular", "manana", 2) and _en_promo(args)
            and not (head_coach and HEAD_COACH_ANTES_QUE_PROMO)):
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
    return canonico in _niveles_de_texto(nivel_clase)


def _niveles_de_texto(texto) -> set[str]:
    """'6TA/7MA' -> {'6ta', '7ma'}. Lo que no es nivel (ej. PRESURIZACION) se ignora."""
    partes = re.split(r"[/,\s-]+", (texto or "").lower())
    return {n for n in (_nivel_canonico(p) for p in partes if p) if n}


def _coincide(nivel_clase, niveles: set[str] | None) -> bool:
    """Para buscar cupos: sin niveles no filtro; con niveles, la clase tiene que tener uno de esos
    (una clase sin nivel cargado no se ofrece, como antes)."""
    if not niveles:
        return True
    return bool(_niveles_de_texto(nivel_clase) & niveles)


def _es_de_otro_nivel(clase: Clase, niveles: set[str] | None) -> bool:
    """Para anotar: solo frena si los dos niveles se conocen y no se cruzan."""
    de_clase = _niveles_de_texto(clase.nivel)
    return bool(niveles) and bool(de_clase) and not (de_clase & niveles)


def _niveles_del_alumno(alumno: Alumno) -> set[str]:
    """Por código, nunca de lo que diga el modelo: su categoría y, si está vacía, el nivel
    de su clase fija (solo para filtrar, no se guarda)."""
    canonico = _nivel_canonico(alumno.categoria or "")
    if canonico:
        return {canonico}
    hoy = planilla._ahora().date()
    clases = (Clase.query.join(Inscripcion, Inscripcion.clase_id == Clase.id)
              .filter(Inscripcion.alumno_id == alumno.id, cd.vigente_en(hoy),
                      Clase.activa.is_(True), Clase.tipo == "grupal").all())
    niveles = set()
    for c in clases:
        niveles |= _niveles_de_texto(c.nivel)
    return niveles


PEDIR_NIVEL = {"status": "falta_nivel",
               "decile": "Decime tu nivel de juego (por ejemplo 8va, 7ma, 6ta...).",
               "mensaje": "Todavía no sabés su nivel: NO le ofrezcas ni anotes nada. Preguntale eso y, "
                          "cuando te lo diga, volvé a llamar con el nivel."}


def _niveles_para(telefono: str, nivel_dicho) -> tuple[set[str] | None, dict | None]:
    """(niveles para filtrar, None) o (None, error para el modelo).
    Alumno: sale de su ficha. Número nuevo: lo que dijo, y si no dijo, hay que preguntarlo."""
    alumnos = _alumnos_con_telefono(telefono)
    if not alumnos:
        canonico = _nivel_canonico(nivel_dicho or "")
        return ({canonico}, None) if canonico else (None, PEDIR_NIVEL)
    if len(alumnos) == 1:
        return _niveles_del_alumno(alumnos[0]), None
    activo = contactos.alumno_activo(telefono, alumnos, SESION_HORAS)
    if activo:
        return _niveles_del_alumno(activo), None
    todos = [_niveles_del_alumno(a) for a in alumnos]
    if all(n == todos[0] for n in todos):
        return todos[0], None  # los hermanos juegan en lo mismo: da igual de cuál habla
    return None, {"status": "elegir_alumno", "alumnos": [a.nombre for a in alumnos],
                  "decile": f"Este número lo tengo con {_nombres(alumnos)}. ¿Para quién buscás lugar?",
                  "mensaje": "NO buscaste nada. Preguntale para cuál de ellos y volvé a llamar."}


def _consultar_cupos_de(telefono: str, args: dict) -> dict:
    if planilla._norm(args.get("tipo")) == "particular":
        return {"status": "particular",
                "mensaje": "Las particulares no se buscan con esta tool: preguntale día, hora y si quiere "
                           "algún profe, y usá agendar_clase_suelta."}
    niveles, error = _niveles_para(telefono, args.get("nivel"))
    if error:
        return error
    return _consultar_cupos({**args, "_niveles": niveles})


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


def _alternativas(dia: int, franja: str | None, niveles: set[str] | None, ya_vistas: set[int], fecha) -> list[dict]:
    """Lo más cercano con lugar: primero otro horario del mismo día, después los días más
    cercanos (mismo turno antes que otro). Mismo nivel si se sabe."""
    franjas = ("kids",) if franja == "kids" else _FRANJAS_ADULTOS
    clases = Clase.query.filter(
        Clase.activa.is_(True), Clase.tipo == "grupal", Clase.ambito.in_(_ambitos_de(franjas)),
    ).all()
    clases = [c for c in clases if c.id not in ya_vistas and _coincide(c.nivel, niveles)]

    def _cercania(c):
        otro_turno = bool(franja) and FRANJA_POR_AMBITO.get(c.ambito) != franja
        return (abs(c.dia_semana - dia), otro_turno, c.dia_semana, c.hora_inicio)

    return _con_lugar(sorted(clases, key=_cercania), fecha)[:MAX_ALTERNATIVAS]


def _consultar_cupos(args: dict) -> dict:
    """Busca lugar. Los niveles vienen ya resueltos en '_niveles' (ver _consultar_cupos_de)."""
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
    nivel = args.get("_niveles") or None  # set de niveles; vacío = sin filtro

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
        clases = [c for c in clases if _coincide(c.nivel, nivel)]
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
PRECIO_CLUB = {"error": "Eso lo maneja el club, no la academia. NO des ningún precio ni le preguntes "
                        "datos para un precio: pasale solo lo que dijo contacto_club."}

_RX_CANCHA = re.compile(r"\bcanchas?\b")


def es_tema_club(*textos) -> bool:
    """Alquiler o reserva de canchas: lo maneja el club, no la academia."""
    return any(_RX_CANCHA.search(planilla._norm(str(t or ""))) for t in textos)


def respuesta_contacto_club(contacto) -> dict:
    """Arma lo que le dice el agente. El número sale de la config, nunca del modelo."""
    contacto = str(contacto or "").strip()
    if contacto:
        decile = (f"El alquiler de canchas no lo maneja la academia, lo maneja el club. "
                  f"Escribiles a este WhatsApp: {contacto}")
        extra = f"Pasale el número tal cual: {contacto}. No inventes otro."
    else:
        decile = "El alquiler de canchas no lo maneja la academia, lo maneja el club directamente."
        extra = "No tenés el número del club: NO inventes ninguno ni digas que se lo pasás a alguien."
    return {"ok": True, "decile": decile,
            "mensaje": "Contale solo eso, con buena onda. " + extra + " NO des precios, horarios ni "
                       "disponibilidad de canchas, y no le preguntes nada más de este tema."}


def _contacto_club() -> dict:
    """Sin notificación: el encargado no tiene nada que hacer con esto."""
    return respuesta_contacto_club(rec.regla("contacto_club_alquiler"))


def _derivar_al_encargado(telefono: str, args: dict, texto: str) -> dict:
    """Temas que el agente no maneja: le llega al encargado con el tema y la consulta tal cual."""
    tema = str(args.get("tema") or "").strip()[:80] or "otro tema"
    # la consulta es el mensaje real del alumno; lo que resumió el modelo va solo si aporta
    consulta = (texto or "").strip()[:500]
    resumen = str(args.get("consulta") or "").strip()[:200]
    if resumen and planilla._norm(resumen) != planilla._norm(consulta):
        consulta = f"{consulta} (resumen: {resumen})" if consulta else resumen
    # el nombre lo arma el panel con el teléfono; en el mensaje va la consulta tal cual
    _notificar(consulta or "(sin detalle)", tipo="consulta_derivada", telefono=telefono, tema=tema)
    return {"ok": True,
            "decile": "Eso lo maneja el encargado: ya le pasé tu consulta y se comunica con vos.",
            "mensaje": "Contale solo eso, con buena onda. NO des precios, horarios, disponibilidad ni "
                       "plazos de este tema, ni prometas cuándo le responde. No le preguntes nada más "
                       "de este tema (ni modalidad, ni turno, ni personas)."}


def _estado_cuota(telefono: str, args: dict) -> dict:
    """Siempre con el número que escribe. 'alumno' solo elige entre los hijos de ese número."""
    a, error = _elegir_alumno(telefono, (args or {}).get("alumno"))
    if error and error.get("status") == "no_alumno":
        return {"encontrado": False,
                "mensaje": "No encuentro a ningún alumno con este número. Decile con buena onda que no lo "
                           "ubicás y ofrecele pasarle la consulta al encargado. No des montos ni datos de nadie."}
    if error:
        return error
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
    alumno = None
    if alumnos:
        dicho = (args.get("alumno") or args.get("nombre") or "").strip()
        if _es_otro_alumno(dicho, alumnos):
            # un hermano que todavía no es alumno: lo da de alta el encargado, no el agente
            return _alta_de_hermano(telefono, dicho, alumnos, args)
        alumno, error = _elegir_alumno(telefono, dicho)
        if error:
            return error
        niveles = _niveles_del_alumno(alumno)  # por código, nunca lo que mande el modelo
    else:
        # número nuevo: el nivel es el que dijo él, nunca el de la clase
        canonico = _nivel_canonico(args.get("nivel") or "")
        if not canonico:
            return PEDIR_NIVEL
        niveles = {canonico}
    nivel = next(iter(niveles)) if len(niveles) == 1 else ""  # para elegir entre clases a la misma hora

    clase, error = _buscar_clase(args, nivel)
    if error:
        return error
    datos = _datos_clase(clase)
    hoy = planilla._ahora().date()

    if _es_de_otro_nivel(clase, niveles):
        return {"status": "otro_nivel", **datos,
                "decile": "Esa clase es de otro nivel, ¿querés que lo consulte con el encargado?",
                "mensaje": "NO lo anotaste. Preguntale eso. Si dice que sí, llamá derivar_al_encargado "
                           "con tema='clase de otro nivel' y en consulta la clase (día, hora y nivel) y "
                           "el nivel del alumno."}

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
        otras = _consultar_cupos({"dia": datos["dia"], "_niveles": niveles,
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
        reg = _registrar_alumno(telefono, {"nombre": nombre, "categoria": nivel})
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


# ---- de quién es el pago, cuando el número es de varios hijos
PREGUNTA_DE_QUIEN = "¿De quién es el pago"  # marca para reconocer la respuesta en el mensaje siguiente
_RE_TODOS = re.compile(r"\b(los|las) (dos|tres|cuatro)\b|\b(ambos|ambas|todos|todas)\b")


def _alumno_del_pago(telefono: str, texto) -> tuple[list[Alumno], str | None]:
    """(alumnos del número, nombre para el comprobante). Con uno solo o ninguno el nombre no importa
    (sigue como siempre). Con varios: el nombrado, 'A y B' si es de los dos, o None si no se sabe."""
    alumnos = _alumnos_con_telefono(telefono)
    if len(alumnos) < 2:
        return alumnos, None
    if _RE_TODOS.search(planilla._norm(texto)):
        return alumnos, _nombres(alumnos)
    nombrados = _mencionados(texto, alumnos)
    return alumnos, (_nombres(nombrados) if nombrados else None)


def _pregunta_de_quien(alumnos: list[Alumno]) -> str:
    nombres = [a.nombre.split()[0] for a in alumnos]
    todos = "los dos" if len(nombres) == 2 else "todos"
    return f"{PREGUNTA_DE_QUIEN}, de {', de '.join(nombres)} o de {todos}?"


def _responder_de_quien(telefono: str, texto: str) -> str | None:
    """Si recién preguntamos de quién era el pago y contesta con un nombre (o 'los dos'), lo anota
    en ese comprobante sin pasar por el modelo."""
    ultima = (Conversacion.query.filter(Conversacion.telefono == telefono, Conversacion.rol == "assistant",
                                        Conversacion.creado_en >= _inicio_sesion())
              .order_by(Conversacion.creado_en.desc(), Conversacion.id.desc()).first())
    if not ultima or PREGUNTA_DE_QUIEN not in (ultima.contenido or ""):
        return None
    alumnos, nombre = _alumno_del_pago(telefono, texto)
    if len(alumnos) < 2 or not nombre:
        return None  # contestó otra cosa: que siga el modelo
    montos = _montos_en(texto) or [m for h in _historial(telefono) if h["role"] == "user"
                                   for m in _montos_en(h["content"])]
    monto = str(int(montos[-1])) if montos else None
    try:
        r = planilla.avisar_comprobante(telefono, monto, alumno=nombre, por_alumno=True)
        print(f"[pago] de quién: {nombre} {monto} -> {r}", flush=True)
    except Exception as e:
        print(f"[pago] error: {e!r}", flush=True)
        return "Perdón, no pude anotarlo en este momento. Avisale al encargado así lo revisa."
    anotado = r.get("monto_anotado")
    if anotado is None:
        return f"Listo, lo anoté a nombre de {nombre}. Decime también cuánto fue así lo anoto."
    return (f"Listo, anoté {_pesos(anotado)} a nombre de {nombre}. "
            "El encargado lo revisa y te confirma el pago.")


def _responder_pago(telefono: str, texto: str) -> str | None:
    """Si el mensaje avisa o corrige un pago con monto, lo anota y responde sin pasar por el modelo."""
    montos = _montos_en(texto)
    if not montos:
        return None
    monto = montos[-1]  # si corrige, el último número es el bueno
    alumnos, nombre = _alumno_del_pago(telefono, texto)
    varios = len(alumnos) > 1
    extra = {"_alumno": nombre, "_por_alumno": varios}
    try:
        if _RE_CORRIGE.search(texto):
            r = planilla.ejecutar("corregir_comprobante", {"monto": str(int(monto)), **extra}, telefono)
            print(f"[pago] corregir_comprobante {int(monto)} -> {r}", flush=True)
            if r and r.get("ok"):
                return (f"Listo, corregí el monto: quedó anotado {_pesos(monto)}. "
                        "El encargado lo revisa y te confirma el pago.")
        if _RE_PAGO.search(texto):
            r = planilla.ejecutar("avisar_comprobante", {"monto": str(int(monto)), **extra}, telefono)
            print(f"[pago] avisar_comprobante {int(monto)} -> {r}", flush=True)
            if r and r.get("ok"):
                if varios and not r.get("alumno"):
                    return (f"Anoté {_pesos(monto)}. {_pregunta_de_quien(alumnos)} Mandame también la "
                            "foto o el PDF del comprobante por acá así queda guardado.")
                de = f" a nombre de {r['alumno']}" if varios else ""
                return (f"Anoté {_pesos(monto)}{de}. Mandame también la foto o el PDF del "
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
        # de quién es: lo que eligió en la charla o lo que dice el mensaje, nunca un nombre inventado
        alumnos, quien = _alumno_del_pago(telefono, args.get("alumno") or "")
        if len(alumnos) > 1 and not quien:
            alumnos, quien = _alumno_del_pago(telefono, texto)
        if nombre == "avisar_comprobante" and len(alumnos) > 1 and not quien:
            return {"status": "elegir_alumno", "alumnos": [a.nombre for a in alumnos],
                    "decile": _pregunta_de_quien(alumnos),
                    "mensaje": "NO anotaste nada. Preguntale de quién es el pago con el texto de 'decile' "
                               "y volvé a llamar avisar_comprobante con alumno=<ese nombre> o alumno='los dos'."}
        args["_alumno"], args["_por_alumno"] = quien, len(alumnos) > 1
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

    # mismo camino que el panel: queda en Auditoria y, si era nuevo, ya no queda a clasificar
    _, error = niveles_mod.clasificar(alumno, args.get("nueva_categoria"), None, origen="whatsapp")
    if error:
        return {"error": f"{error}. Los niveles válidos son: {', '.join(niveles_mod.niveles())}"}
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
    precio, _ = cd.precio_de(armado["quedan"], fecha)
    cambio = cd.crear(alumno, armado["deja"], armado["nuevas"], fecha, origen="encargado",
                      espera="alumno", pedido_por="encargado", precio=precio)
    resultado = {"status": "propuesta creada", "cambio_id": cambio.id, "alumno": alumno.nombre,
                 "propuesta": cambio.propuesta}
    if precio is None:
        resultado["aviso"] = "No hay tarifa exacta para cómo le quedan las clases: la cuota la tenés que ver vos."
    return resultado


def _resolver_cambio_pendiente(telefono: str, args: dict) -> dict:
    cambios = _cambios_pendientes_de(telefono)
    if not cambios:
        return {"error": "No hay ningún cambio pendiente para vos"}

    cambio_id = _entero(args.get("cambio_id"))
    if cambio_id:
        cambio = next((c for c in cambios if c.id == cambio_id), None)
        if not cambio:
            return {"error": "Ese cambio_id no es de este número. Usá uno de los que te pasé."}
    elif len(cambios) == 1:
        cambio = cambios[0]
    else:
        # varios: si hay un hijo elegido en la charla y tiene uno solo, es ese
        activo = _alumno_por_telefono(telefono)
        del_activo = [c for c in cambios if activo and c.alumno_id == activo.id]
        if len(del_activo) != 1:
            return {"status": "elegir_cambio",
                    "cambios": [{"cambio_id": c.id, "alumno": _nombre_de(c), "propuesta": c.propuesta}
                                for c in cambios],
                    "mensaje": "NO resolviste nada. Hay más de un cambio pendiente: preguntale de cuál "
                               "habla y volvé a llamar con ese cambio_id."}
        cambio = del_activo[0]

    acepta = args.get("decision") == "si_acepto"
    nombre = _nombre_de(cambio)

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
            # no queda pedido: va a Consultas para que el encargado le conteste
            _notificar(f"Quiere cambiar de días desde el {cd.fecha_corta(pedida)}, fuera de plazo. "
                       f"Días que pidió: {', '.join(map(str, args.get('dias_nuevos') or [])) or '?'}",
                       tipo="consulta_derivada", telefono=telefono, tema="cambio de dias")
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
    precio, _ = cd.precio_de(armado["quedan"], fecha)
    if precio is None:
        # nunca inventar precios: sin tarifa exacta lo ve el encargado
        _notificar(f"Quiere cambiar de días ({resumen}), pero no hay tarifa exacta para quedar con "
                   f"{quedan}. Lo tenés que ver vos.",
                   tipo="consulta_derivada", telefono=telefono, tema="cambio de dias")
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
    if existentes:
        if _es_otro_alumno(nombre, existentes):
            return _alta_de_hermano(telefono, nombre, existentes, args)
        nombrados = _mencionados(nombre, existentes)
        if len(nombrados) == 1:
            return {"status": "ya_registrado", "alumno": nombrados[0].nombre}
        return {"status": "ya_registrado", "alumnos": [a.nombre for a in existentes]}

    # el nivel es el que dijo el alumno; sin eso no se registra (nunca se copia el de la clase)
    categoria = _nivel_canonico(args.get("categoria") or "")
    if not categoria:
        return PEDIR_NIVEL

    alumno = Alumno(
        nombre=nombre,
        telefono=telefono,
        categoria=categoria,
        planilla="adultos",
    )
    db.session.add(alumno)
    db.session.flush()  # para tener el id del contacto y del perfil
    contactos.crear_contacto(alumno, telefono, "propio")
    niveles_mod.registrar_declarado(alumno, categoria)  # queda "nuevo, nivel a clasificar"
    db.session.commit()

    _notificar(f"Nuevo alumno registrado: {nombre} ({telefono}), dijo categoría {categoria} "
               "(a clasificar en sus clases)", tipo="alta_alumno")
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
    # varios: primero el nombre que vino, después el que quedó elegido en la charla
    activo = contactos.alumno_activo(telefono, alumnos, SESION_HORAS)
    if _palabras(nombre):
        elegidos = _mencionados(nombre, alumnos)
        if len(elegidos) == 1:
            contactos.fijar_alumno_activo(telefono, elegidos[0].id)
            return elegidos[0], None
        # dijo solo el apellido que comparten (no distingue a nadie): sigo con el de la charla
        if activo and (activo in elegidos or (not elegidos and not _es_otro_alumno(nombre, alumnos))):
            return activo, None
    elif activo:
        return activo, None
    return None, {"status": "elegir_alumno", "alumnos": [a.nombre for a in alumnos],
                  "decile": f"Este número lo tengo con {_nombres(alumnos)}. ¿De quién me hablás?",
                  "mensaje": "NO registraste nada. Preguntale de cuál de ellos habla y volvé a llamar "
                             "la tool con alumno=<ese nombre>."}


def _alta_de_hermano(telefono: str, nombre: str, alumnos: list[Alumno], args: dict) -> dict:
    """Quieren sumar a alguien que no es ninguno de los alumnos del número: va al encargado."""
    detalle = ""
    if args.get("clase_id") or args.get("dia"):
        clase, error = _buscar_clase(args, (args.get("nivel") or "").strip())
        if clase and not error:
            d = _datos_clase(clase)
            detalle = f" Quiere la clase del {d['dia']} {d['hora']} ({d['nivel']})."
    _notificar(f"Quiere sumar a {nombre} (hermano/a de {_nombres(alumnos)}).{detalle} "
               "Hay que darlo de alta y cargarle el contacto.",
               tipo="consulta_derivada", telefono=telefono, tema="alta de hermano")
    return {"status": "derivado",
            "decile": f"Para sumar a {nombre} se lo paso al encargado, que lo da de alta y te confirma \U0001F60A",
            "mensaje": "NO anotaste ni registraste a nadie. " + _RESPUESTA_TOOL}


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
    alumno, error = _elegir_alumno(telefono, args.get("alumno"))
    if error and error.get("status") == "no_alumno":
        return {"error": "No encontré tu registro como alumno."}
    if error:
        return error

    alumno.estado = "baja"
    alumno.motivo_baja = args["motivo"]
    db.session.commit()

    _notificar(f"{alumno.nombre} se dio de baja. Motivo: {args['motivo']}", tipo="baja_alumno")
    return {"status": "baja registrada", "alumno": alumno.nombre}


def _alumno_para_pausa(nombre: str):
    """(alumno, error). Si el nombre coincide con varios no elijo: devuelvo la lista para que precise.
    Si uno coincide justo con el nombre completo, ese."""
    nombre = (nombre or "").strip()
    if not nombre:
        return None, {"error": "Decime de qué alumno."}
    candidatos = Alumno.query.filter(Alumno.nombre.ilike(f"%{nombre}%")).order_by(Alumno.nombre).all()
    if not candidatos:
        return None, {"error": f"No encontré ningún alumno llamado '{nombre}'"}
    if len(candidatos) == 1:
        return candidatos[0], None
    exactos = [a for a in candidatos if a.nombre.strip().lower() == nombre.lower()]
    if len(exactos) == 1:
        return exactos[0], None
    return None, {"error": "Hay varios alumnos con ese nombre, no pausé ni reanudé nada. Preguntale cuál.",
                  "coincidencias": [a.nombre for a in candidatos]}


def _cambiar_modo_alumno(args: dict, modo: str) -> dict:
    """Pone el modo en todos los números del alumno (propio, papá, mamá...)."""
    alumno, error = _alumno_para_pausa(args.get("alumno_nombre"))
    if error:
        return error
    telefonos = contactos.telefonos_de_alumno(alumno)
    if not telefonos:
        return {"error": f"{alumno.nombre} no tiene ningún teléfono cargado."}
    for t, _ in telefonos:
        contactos.poner_modo(t, modo)
    db.session.commit()
    r = {"status": "pausado" if modo == "humano" else "reanudado", "alumno": alumno.nombre,
         "telefonos": [f"{t} ({etiqueta})" for t, etiqueta in telefonos]}
    if modo == "humano":
        horas = contactos.horas_pausa()
        r["vence"] = f"el agente vuelve solo en {horas} hs si no lo reanudás antes" if horas else "no vence sola"
    return r


def _pausar_bot(args: dict, es_jefe: bool) -> dict:
    if not es_jefe:
        return {"error": "No autorizado."}
    return _cambiar_modo_alumno(args, "humano")


def _reanudar_bot(args: dict, es_jefe: bool) -> dict:
    if not es_jefe:
        return {"error": "No autorizado."}
    return _cambiar_modo_alumno(args, "bot")