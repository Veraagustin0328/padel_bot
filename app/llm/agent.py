import json
import re
from datetime import datetime, timedelta
from app.extensions import db
from app.llm.client import client, MODEL
from app.llm.tools import tools_para_rol
from app.models import (
    Grupo, ClaseSuelta, Conversacion, Pago, Alumno,
    CambioPendiente, Recuperacion, Notificacion, EstadoChat,
)

MAX_HISTORIAL = 10
SESION_HORAS = 24

DATOS_DE_PAGO = (
    "Alias: academiaarenapadel. Se paga por transferencia a ese alias. "
    "Después hay que avisarle al encargado y mostrarle el comprobante "
    "para que confirme el pago."
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
# Precios mensuales. Actualizar acá cuando cambien los flyers.
INSCRIPCION = 25000

# tipo -> {(personas, veces_por_semana): precio}. "por_persona" indica si es c/u.
PRECIOS = {
    "modo_academia": {
        "descripcion": "Modo Academia, mañana (7 a 12 hs). Los profes arman los grupos según el nivel.",
        "por_persona": True,
        "tabla": {(None, 1): 55000, (None, 2): 92000, (None, 3): 140000, (None, 4): 180000},
    },
    "particular_manana": {
        "descripcion": "Clases particulares de mañana (7 a 12 hs). El alumno decide cómo formar el grupo.",
        "por_persona": True,
        "tabla": {
            (1, 1): 110000, (1, 2): 220000,
            (2, 1): 72000, (2, 2): 145000,
            (3, 1): 50000, (3, 2): 100000,
        },
    },
    "particular_manana_2x1": {
        "descripcion": "Promo 2x1 de mañana, lunes, miércoles y viernes a las 9, 10 y 11 hs.",
        "por_persona": True,
        "tabla": {(None, 1): 55000, (None, 2): 110000},
    },
    "particular_tarde": {
        "descripcion": "Clases particulares de tarde (14:30, 15:30, 16:30 y 17:30 hs).",
        "por_persona": True,
        "tabla": {
            (1, 1): 160000, (1, 2): 320000,
            (2, 1): 107000, (2, 2): 186000,
            (3, 1): 80000, (3, 2): 140000,
        },
    },
    "particular_head_coach": {
        "descripcion": "Clases particulares con el head coach (7 a 12 hs).",
        "por_persona": True,
        "tabla": {
            (1, 1): 140000, (1, 2): 280000,
            (2, 1): 100000, (2, 2): 200000,
            (3, 1): 80000, (3, 2): 160000,
        },
    },
    "sabado_modo_academia": {
        "descripcion": "Modo Academia del sábado a la mañana (8, 9, 10 y 11 hs).",
        "por_persona": True,
        "tabla": {(None, None): 75000},
    },
    "sabado_particular": {
        "descripcion": "Particular del sábado a la mañana (8, 9, 10 y 11 hs).",
        "por_persona": True,
        "tabla": {(2, None): 80000, (3, None): 65000},
    },
}

POLITICAS = (
    "Las clases se pagan por mes adelantado. Hay que avisar con al menos 24 hs "
    "de anticipación si no se puede ir, si no se pierde la clase. Se puede "
    "recuperar 1 clase por mes."
)

# ---------------------------------------------------------------- prompts
PROMPT_ALUMNO_PARTE_1 = (
    "Sos el asistente de WhatsApp de Academia Arena Pádel. Hablás como un profe "
    "argentino de confianza, cálido y cercano.\n\n"
    "Estilo:\n"
    "- Usá SIEMPRE voseo ('querés', 'podés', 'decime', 'contame'). Nunca mezcles "
    "con tuteo ('quieres', 'puedes').\n"
    "- Mensajes cortos y naturales. No uses emojis numerados ni listas con "
    "emojis. Podés usar algún emoji suelto, con moderación.\n"
    "- Mantené el tono cálido SIEMPRE, incluso cuando tengas que decir que no "
    "podés ayudar con algo.\n\n"
    "Niveles de juego: 1era (también se escribe 1ra, es lo mismo), 2da, 3ra, 4ta, "
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
    "no te dieron.\n\n"
    "Precios:\n"
    "- Para CUALQUIER precio usá la tool consultar_precio. Nunca digas un precio "
    "de memoria ni lo calcules vos.\n"
    "- Si el alumno pregunta el precio en general ('cuánto sale', 'qué precio "
    "tienen las clases'), NO llames la tool todavía y NO des ningún número. "
    "Primero preguntale, en un solo mensaje corto: si quiere grupo armado por los "
    "profes (modo academia) o clase particular con su propio grupo, si prefiere "
    "mañana, tarde o sábado, y cuántas veces por semana.\n"
    "- Solo llamá consultar_precio cuando el alumno YA te dijo todos los datos. "
    "Nunca asumas ni inventes un dato que no dijo (ni las veces por semana, ni "
    "la cantidad de personas, ni el turno).\n"
    "- Los precios son mensuales y cada alumno paga el suyo (por persona).\n"
    "- La inscripción es de $25.000, pago único. Mencionala solo si preguntan o si "
    "se están anotando.\n\n"
    "Confirmaciones:\n"
    "- Nunca digas que una clase quedó agendada, cancelada o que alguien quedó "
    "registrado si no llamaste a la tool correspondiente y devolvió ok.\n"
    "- Si un alumno confirma que quiere anotarse a un grupo y NO está registrado "
    "(más abajo te aviso si lo está), NO le repitas día ni hora: preguntale SOLO "
    "el nombre y apenas te lo diga llamá registrar_alumno con ese nombre y el "
    "nivel que ya mencionó.\n"
    "- Si quiere cancelar una clase particular que ya tenía, usá "
    "cancelar_clase_suelta (con el día si tiene más de una).\n"
)

BLOQUE_PAGOS_CON_DATOS = (
    "Pagos: si preguntan cómo o dónde pagar, respondé con estos datos y nada más: "
    + DATOS_DE_PAGO + "\n"
    "- Escribilo en voseo ('Podés transferir', no 'Podes').\n"
    "- NO pidas que mande el comprobante por este chat: vos no podés leerlo "
    "ni registrarlo. Decile que se lo muestre o se lo mande al encargado.\n"
    "- NUNCA digas que un pago se cobra, se acredita o se confirma solo, ni "
    "'al instante'. Quien confirma el pago es el encargado.\n"
)
BLOQUE_PAGOS_SIN_DATOS = (
    "Pagos: si preguntan cómo o dónde pagar, decí que el encargado les pasa los "
    "datos de pago. NO inventes alias, CBU, apps, lugares ni medios de pago.\n"
)
BLOQUE_PAGOS = BLOQUE_PAGOS_CON_DATOS if DATOS_DE_PAGO else BLOQUE_PAGOS_SIN_DATOS

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
)

SYSTEM_PROMPT_ALUMNO = PROMPT_ALUMNO_PARTE_1 + BLOQUE_PAGOS + PROMPT_ALUMNO_PARTE_2

SALUDO_PRIMER_MENSAJE = (
    "Es el primer mensaje de esta conversación (o pasó más de un día desde el "
    "último). Arrancá tu respuesta con un saludo breve: 'Hola amigo' o 'Hola "
    "amiga' (si no sabés, 'Hola amigo/a'), y después respondé lo que preguntó."
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
    "Sé directo y breve, es un canal de trabajo."
)


# ---------------------------------------------------------------- principal
def _inicio_sesion() -> datetime:
    return datetime.utcnow() - timedelta(hours=SESION_HORAS)


def _nota_registro(telefono: str) -> str:
    alumno = Alumno.query.filter_by(telefono=telefono).first()
    if alumno:
        return f"Este número YA está registrado como alumno: {alumno.nombre}. No hace falta registrarlo."
    return (
        "Este número NO está registrado todavía como alumno. Si quiere anotarse "
        "a un grupo, primero hay que registrarlo con registrar_alumno."
    )


def procesar_mensaje(telefono: str, texto: str, es_jefe: bool = False) -> str:
    _guardar_mensaje(telefono, "user", texto)

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
            "content": SALUDO_YA_SALUDASTE if ya_hablo_bot else SALUDO_PRIMER_MENSAJE,
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

    respuesta = client.chat.completions.create(
        model=MODEL,
        messages=mensajes,
        tools=tools,
        tool_choice="auto",
        temperature=0.2,
    )
    mensaje_modelo = respuesta.choices[0].message

    if not mensaje_modelo.tool_calls:
        texto_final = mensaje_modelo.content or "No entendí eso, ¿podés reformularlo?"
        _guardar_mensaje(telefono, "assistant", texto_final)
        return texto_final

    mensajes.append(mensaje_modelo.model_dump())

    for tool_call in mensaje_modelo.tool_calls:
        nombre = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        if nombre == "buscar_grupo_disponible":
            resultado = _buscar_grupo_disponible(args)
        elif nombre == "consultar_precio":
            resultado = _consultar_precio(args)
        elif nombre == "agendar_clase_suelta":
            resultado = _agendar_clase_suelta(telefono, args)
        elif nombre == "cancelar_clase_suelta":
            resultado = _cancelar_clase_suelta(telefono, args)
        elif nombre == "consultar_estado_pago":
            resultado = _consultar_estado_pago(telefono)
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
            resultado = {"error": f"Tool desconocida: {nombre}"}

        mensajes.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(resultado, ensure_ascii=False),
        })

    respuesta_final = client.chat.completions.create(
        model=MODEL,
        messages=mensajes,
        temperature=0.2,
    )
    texto_final = respuesta_final.choices[0].message.content or "Listo, ya está."
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
    return (
        CambioPendiente.query.filter_by(alumno_telefono=telefono, estado="pendiente")
        .order_by(CambioPendiente.creado_en.desc())
        .first()
    )


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


def _consultar_precio(args: dict) -> dict:
    tipo = (args.get("tipo") or "").strip()
    info = PRECIOS.get(tipo)
    if not info:
        return {"error": f"Tipo de clase desconocido. Opciones: {', '.join(PRECIOS)}"}

    personas = args.get("personas")
    veces = args.get("veces_por_semana")
    if isinstance(personas, int) and personas >= 3:
        personas = 3  # 3 y 4 personas pagan igual

    tabla = info["tabla"]
    clave_personas = personas if any(k[0] is not None for k in tabla) else None
    clave_veces = veces if any(k[1] is not None for k in tabla) else None

    faltan = []
    if any(k[0] is not None for k in tabla) and clave_personas is None:
        faltan.append("personas")
    if any(k[1] is not None for k in tabla) and clave_veces is None:
        faltan.append("veces_por_semana")
    if faltan:
        return {"error": "Faltan datos para dar el precio. Preguntale al alumno: " + ", ".join(faltan)}

    precio = tabla.get((clave_personas, clave_veces))
    if precio is None:
        opciones = sorted(f"{p or '-'} personas, {v or '-'} veces por semana" for p, v in tabla)
        return {"error": "Esa combinación no existe.", "combinaciones_validas": opciones}

    return {
        "descripcion": info["descripcion"],
        "precio_mensual": precio,
        "por_persona": info["por_persona"],
        "inscripcion_pago_unico": INSCRIPCION,
        "politicas": POLITICAS,
    }



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


def _consultar_estado_pago(telefono: str) -> dict:
    pago = Pago.query.filter_by(telefono=telefono).order_by(Pago.id.desc()).first()
    if not pago:
        return {"estado": "sin_registro", "detalle": "No hay pagos registrados para este número"}
    return {"estado": pago.estado, "mes": pago.mes, "monto": float(pago.monto)}


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

    alumno = Alumno.query.filter_by(telefono=telefono).first()
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

    existente = Alumno.query.filter_by(telefono=telefono).first()
    if existente:
        return {"status": "ya_registrado", "alumno": existente.nombre}

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
    alumno = Alumno.query.filter_by(telefono=telefono).first()
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