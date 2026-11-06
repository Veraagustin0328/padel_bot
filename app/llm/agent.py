import json
import re
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.llm.client import client, MODEL
from app.llm.tools import tools_para_rol
from app import planilla
from app.cuotas import (
    DIAS_PROMO_2X1, FRANJA_POR_AMBITO, HORA_PROMO_DESDE, HORA_PROMO_HASTA, cargar_tarifas, precio_bucket,
)
from app.models_academia import Clase, ConfigAcademia, Inscripcion
from app.models_cuotas import CuotaMes, PagoCuota
from app.models import (
    Grupo, ClaseSuelta, Conversacion, Alumno,
    CambioPendiente, Recuperacion, Notificacion, EstadoChat,
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


def _variantes_nivel(texto: str) -> list[str]:
    canonico = _nivel_canonico(texto)
    if not canonico:
        return [(texto or "").strip().lower()]
    return _NIVELES[canonico]



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

POLITICAS = (
    "Las clases se pagan por mes adelantado. Hay que avisar con al menos 24 hs "
    "de anticipación si no se puede ir, si no se pierde la clase. Se puede "
    "recuperar 1 clase por mes."
)

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
    "- Para buscar_grupo_disponible solo hacen falta el nivel de juego y, si lo "
    "dijo, el día. NO inventes que falta otro dato ('tipo de clase', 'categoría "
    "de torneo'): eso no existe.\n"
    "- Si piden clase particular, preguntá día y hora, y si quieren algún profe "
    "en particular, ANTES de usar agendar_clase_suelta. No agendes con datos que "
    "no te dieron.\n"
    "- Si preguntan si hay lugar o cupo en una clase, usá consultar_cupos con el día y el "
    "turno (y el nivel si lo dijo). Que haya lugar no lo anota.\n"
    "- Si confirma que quiere anotarse a una clase grupal, usá anotar_en_clase con el "
    "clase_id que te dio consultar_cupos (o con el día y la hora). Solo decile que quedó "
    "anotado si la tool devolvió status 'anotado' o 'ya_anotado'.\n\n"
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
    "cancelar_clase_suelta (con el día si tiene más de una).\n"
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
    "- Si pide reprogramar o recuperar una clase, preguntale a qué día y horario "
    "y usá reprogramar_clase. Tiene derecho a 1 recuperación por mes; si la tool "
    "dice que ya la usó, contale con buena onda, sin prometer excepciones.\n"
    "- Si más abajo ves un 'cambio pendiente', contale de qué se trata y "
    "preguntale si lo acepta; cuando conteste usá resolver_cambio_pendiente.\n"
    "\nFormato (obligatorio, tiene prioridad sobre todo lo demás):\n"
    "- Escribí en frases cortas, sin listas. NUNCA uses listas numeradas ni emojis "
    "numerados. Si tenés que preguntar varias cosas, hacelo en una sola frase "
    "corrida: '¿Te interesa grupo armado o clase particular, qué turno te queda "
    "mejor y cuántas veces por semana querés venir?'\n"
    "- Voseo siempre: 'preferís', 'querés', 'podés', 'tenés', 'decime'. Jamás "
    "'prefieres', 'quieres', 'puedes', 'tienes'.\n"
    "- Si el alumno solo está preguntando, NO le pidas el nombre ni el registro. "
    "Pedilo recién cuando confirme que quiere anotarse.\n"
    "- Respondé primero lo que preguntó, y recién después, si hace falta, "
    "preguntá una sola cosa.\n"
    "- Si preguntan qué clases o qué horarios tienen, preguntales primero su nivel "
    "de juego y qué día les queda mejor, para buscarles un grupo.\n"
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
    "alumno, proponerle un cambio de día/horario (que queda pendiente de que el "
    "alumno lo confirme), o pausar/reanudar al bot en una conversación puntual. "
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

    for tool_call in mensaje_modelo.tool_calls:
        nombre = re.sub(r"[^A-Za-z_]", "", tool_call.function.name or "")
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        if nombre == "buscar_grupo_disponible":
            resultado = _buscar_grupo_disponible(args)
        elif nombre == "consultar_precio":
            resultado = _consultar_precio(args)
        elif nombre == "consultar_cupos":
            resultado = _consultar_cupos(args)
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
        elif nombre == "registrar_alumno":
            resultado = _registrar_alumno(telefono, args)
        elif nombre == "dar_de_baja":
            resultado = _dar_de_baja(telefono, args)
        elif nombre == "reprogramar_clase":
            resultado = _reprogramar_clase(telefono, args)
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
    pendientes = (
        CambioPendiente.query.filter_by(estado="pendiente")
        .order_by(CambioPendiente.creado_en.desc(), CambioPendiente.id.desc())
        .all()
    )
    return next((c for c in pendientes if planilla._tel(c.alumno_telefono) == t), None)


# ---------------------------------------------------------------- tools
def _buscar_grupo_disponible(args: dict) -> dict:
    variantes = _variantes_nivel(args.get("nivel_juego", ""))
    dia = (args.get("dia") or "").strip().lower()

    query = Grupo.query.filter(db.func.lower(Grupo.categoria).in_(variantes))
    if dia:
        query = query.filter(db.func.lower(Grupo.dia) == dia)

    grupos = query.all()
    return {
        "grupos": [
            {"dia": g.dia, "horario": g.horario, "cupo_max": g.cupo_max}
            for g in grupos
        ]
    }


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
        "politicas": POLITICAS,
    }


# ---------------------------------------------------------------- cupos y cuota (solo lectura)
_NOMBRE_DIA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _nivel_de_clase(nivel_clase: str, canonico: str) -> bool:
    """'6TA/7MA' sirve para 6ta y para 7ma; 'PRINCIPIANTES' para principiante."""
    partes = re.split(r"[/,\s-]+", (nivel_clase or "").lower())
    return any(_nivel_canonico(p) == canonico for p in partes if p)


def _vigente(hoy):
    # inscripción vigente hoy: desde <= hoy y (sin hasta o hasta >= hoy)
    return db.and_(Inscripcion.desde <= hoy,
                   db.or_(Inscripcion.hasta.is_(None), Inscripcion.hasta >= hoy))


def _anotados_hoy(clase_ids: list[int], hoy) -> dict[int, int]:
    if not clase_ids:
        return {}
    return dict(
        db.session.query(Inscripcion.clase_id, db.func.count(Inscripcion.id))
        .filter(Inscripcion.clase_id.in_(clase_ids), _vigente(hoy))
        .group_by(Inscripcion.clase_id).all()
    )


def _consultar_cupos(args: dict) -> dict:
    dia = _DIAS.get((args.get("dia") or "").strip().lower())
    franja = (args.get("franja") or "").strip().lower()
    if dia is None or not franja:
        return {"error": "Falta el día o el turno. Preguntaselo al alumno antes de buscar."}
    if dia == 5:
        franja = "sabado"
    ambitos = [a for a, f in FRANJA_POR_AMBITO.items() if f == franja]
    nivel = _nivel_canonico(args.get("nivel") or "")

    hoy = planilla._ahora().date()
    clases = Clase.query.filter(
        Clase.activa.is_(True), Clase.tipo == "grupal",
        Clase.dia_semana == dia, Clase.ambito.in_(ambitos),
    ).order_by(Clase.hora_inicio).all()
    if nivel:
        clases = [c for c in clases if _nivel_de_clase(c.nivel, nivel)]
    if not clases:
        return {"clases_con_lugar": [], "mensaje": "No hay clases grupales ese día y turno"
                + (" para ese nivel" if nivel else "") + ". Ofrecé buscar otro día."}

    anotados = _anotados_hoy([c.id for c in clases], hoy)
    con_lugar = []
    for c in clases:
        libres = c.cupo - anotados.get(c.id, 0)
        if libres > 0:
            # sin profe ni alumnos: solo lo que el alumno necesita (el id es para anotar_en_clase)
            con_lugar.append({"clase_id": c.id, "dia": _NOMBRE_DIA[c.dia_semana],
                              "hora": c.hora_inicio.strftime("%H:%M"),
                              "nivel": c.nivel or "sin nivel", "lugares_libres": libres})
    if not con_lugar:
        return {"clases_con_lugar": [], "mensaje": f"Las {len(clases)} clases de ese día y turno están llenas. Ofrecé buscar otro día."}
    return {"clases_con_lugar": con_lugar,
            "mensaje": "Pasale las opciones. Que haya lugar no lo anota: no digas que quedó reservado."}


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
    return _anotados_hoy([clase.id], hoy).get(clase.id, 0) >= clase.cupo


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
            db.or_(Inscripcion.hasta.is_(None), Inscripcion.hasta >= hoy),
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
    if not es_jefe:
        return {"error": "No autorizado. Solo el encargado puede proponer cambios."}

    alumno = Alumno.query.filter(Alumno.nombre.ilike(f"%{args['alumno_nombre']}%")).first()
    if not alumno:
        return {"error": f"No encontré ningún alumno llamado '{args['alumno_nombre']}'"}

    cambio = CambioPendiente(
        alumno_telefono=alumno.telefono,
        tipo="reasignacion",
        propuesta=args["propuesta"],
    )
    db.session.add(cambio)
    db.session.commit()
    return {"status": "propuesta creada", "cambio_id": cambio.id, "alumno": alumno.nombre}


def _resolver_cambio_pendiente(telefono: str, args: dict) -> dict:
    cambio = _cambio_pendiente_de(telefono)
    if not cambio:
        return {"error": "No hay ningún cambio pendiente para vos"}

    cambio.estado = "aceptado" if args["decision"] == "si_acepto" else "rechazado"
    db.session.commit()

    alumno = _alumno_por_telefono(telefono)
    nombre = alumno.nombre if alumno else telefono
    _notificar(f"{nombre} {cambio.estado} el cambio propuesto: {cambio.propuesta}", tipo="cambio_resuelto")
    return {"status": cambio.estado, "propuesta": cambio.propuesta}


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


def _reprogramar_clase(telefono: str, args: dict) -> dict:
    mes_actual = datetime.utcnow().strftime("%Y-%m")

    ya_uso = Recuperacion.query.filter_by(telefono=telefono, mes=mes_actual).first()
    if ya_uso:
        return {
            "error": (
                f"Este alumno ya usó su recuperación del mes ({ya_uso.mes}), "
                f"la cambió al {ya_uso.dia_nuevo} {ya_uso.horario_nuevo}. No puede "
                "usar otra hasta el mes que viene."
            )
        }

    dia_nuevo = (args.get("dia_nuevo") or "").strip()
    horario_nuevo = (args.get("horario_nuevo") or "").strip()
    if not dia_nuevo or not horario_nuevo:
        return {"error": "Faltan día u horario nuevo, no se puede reprogramar sin eso."}

    recu = Recuperacion(telefono=telefono, mes=mes_actual, dia_nuevo=dia_nuevo, horario_nuevo=horario_nuevo)
    db.session.add(recu)
    db.session.commit()

    _notificar(f"{telefono} reprogramó su clase para {dia_nuevo} {horario_nuevo}", tipo="reprogramacion")
    return {"status": "reprogramada", "dia_nuevo": dia_nuevo, "horario_nuevo": horario_nuevo}


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