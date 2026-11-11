from app.planilla import TOOLS_PLANILLA_ALUMNO, TOOLS_PLANILLA_JEFE

DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado"]
NIVELES = ["1era", "1ra", "2da", "3ra", "4ta", "5ta", "6ta", "7ma", "8va", "principiante"]

# buscar_grupo_disponible ya no está: leía la tabla vieja Grupo. Si el modelo la manda igual,
# el agente la pasa a consultar_cupos.
_TOOLS_BASE = [
    {
        "type": "function",
        "function": {
            "name": "consultar_precio",
            "description": (
                "Devuelve el precio mensual de las clases. Mandá solo lo que el alumno "
                "dijo: si falta algo, la tool te dice qué preguntar. NUNCA inventes datos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "modalidad": {
                        "type": "string",
                        "enum": ["academia", "particular"],
                        "description": (
                            "academia = grupo armado por los profes según el nivel. "
                            "particular = el alumno arma su propio grupo. SOLO si lo dijo."
                        ),
                    },
                    "turno": {
                        "type": "string",
                        "enum": ["mañana", "tarde", "sabado"],
                        "description": "Turno que pidió el alumno. SOLO si lo dijo.",
                    },
                    "personas": {"type": "integer", "description": "Cuántas personas van a la clase (1 a 4), SOLO si el alumno lo dijo. Solo para particular."},
                    "veces": {"type": "integer", "description": "Veces por semana (1 a 4), SOLO si el alumno lo dijo. No aplica al sábado."},
                    "promo_2x1": {"type": "boolean", "description": "true SOLO si el alumno pidió la promo 2x1."},
                    "head_coach": {"type": "boolean", "description": "true SOLO si el alumno pidió clase con el head coach."},
                    "dia": {"type": "string", "description": "Opcional. Día que pidió el alumno (ej. 'martes'), SOLO si lo dijo. Sirve para chequear la promo 2x1."},
                    "hora": {"type": "string", "description": "Opcional. Hora que pidió el alumno (ej. '10' o '18:30'), SOLO si la dijo. Sirve para chequear la promo 2x1."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agendar_clase_suelta",
            "description": "Agenda una clase particular puntual, cuando ya se sabe el día, horario y opcionalmente el profe pedido",
            "parameters": {
                "type": "object",
                "properties": {
                    "dia": {"type": "string"},
                    "horario": {"type": "string"},
                    "profesor": {"type": "string", "description": "Opcional, solo si el alumno pidió uno en particular"},
                },
                "required": ["dia", "horario"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancelar_clase_suelta",
            "description": (
                "Cancela una clase particular que el alumno ya tenía agendada. "
                "Si tiene más de una, indicá el día."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dia": {"type": "string", "description": "Opcional. Día de la clase a cancelar."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolver_cambio_pendiente",
            "description": (
                "Se llama cuando el alumno responde sobre una propuesta de cambio pendiente. "
                "Si dice que sí, dale, acepto, está bien, o cualquier confirmación positiva, "
                "usá decision='si_acepto'. Si dice que no o prefiere que no, usá decision='no_rechazo'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "string",
                        "enum": ["si_acepto", "no_rechazo"],
                        "description": "si_acepto = confirmó que sí quiere el cambio. no_rechazo = no lo quiere.",
                    },
                },
                "required": ["decision"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_alumno",
            "description": (
                "Registra a un alumno nuevo que todavía no está en el sistema. "
                "Llamala SOLO cuando ya tengas el nombre real que te dijo el alumno "
                "(nunca placeholders ni texto entre corchetes) y su nivel de juego "
                "ya mencionado en la charla."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "description": "Nombre real del alumno, tal como te lo dijo"},
                    "categoria": {"type": "string", "description": "Nivel de juego ya mencionado en la charla (ej: 5ta, 1era)"},
                },
                "required": ["nombre", "categoria"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "avisar_ausencia",
            "description": (
                "Anota que el alumno que escribe NO va a ir a su clase un día (ej. 'el jueves no voy'). "
                "El alumno sale del número de WhatsApp. La primera vez te devuelve la fecha completa: "
                "preguntale si es esa y, cuando diga que sí, volvé a llamarla con confirmado=true. "
                "Contale solo lo que dice 'decile'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha": {"type": "string", "description": "El día tal cual lo dijo el alumno (ej. 'jueves', 'mañana', '12/11')."},
                    "horario": {"type": "string", "description": "Opcional. Hora de la clase, SOLO si la tool te la pidió."},
                    "motivo": {"type": "string", "description": "Opcional. Por qué no va, si lo dijo."},
                    "alumno": {"type": "string", "description": "Nombre del alumno, SOLO si la tool te pidió elegir entre varios."},
                    "confirmado": {"type": "boolean", "description": "true SOLO si el alumno ya confirmó la fecha completa que te dio la tool."},
                },
                "required": ["fecha"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pedir_recuperacion",
            "description": (
                "Pide recuperar (o reprogramar) una clase en otro día y horario. Si cumple las reglas "
                "queda confirmada; si no, queda pendiente y la decide el encargado. La primera vez te "
                "devuelve la fecha completa para confirmar: cuando el alumno diga que sí, volvé a "
                "llamarla con confirmado=true. Solo decí 'confirmada' si la tool devolvió status 'confirmada'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dia": {"type": "string", "description": "Día en que quiere recuperar, tal cual lo dijo (ej. 'miércoles' o '18/11')."},
                    "horario": {"type": "string", "description": "Hora de la clase donde quiere recuperar (ej. '18' o '18:30')."},
                    "clase_id": {"type": "integer", "description": "Opcional. Solo si la tool te dio opciones con clase_id."},
                    "alumno": {"type": "string", "description": "Nombre del alumno, SOLO si la tool te pidió elegir entre varios."},
                    "confirmado": {"type": "boolean", "description": "true SOLO si el alumno ya confirmó la fecha completa que te dio la tool."},
                },
                "required": ["dia", "horario"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "avisar_viaje",
            "description": (
                "Anota que el alumno se va de viaje y no viene entre dos fechas. Queda pendiente hasta "
                "que el encargado lo confirme. La primera vez te devuelve las fechas completas para "
                "confirmar: cuando el alumno diga que sí, volvé a llamarla con confirmado=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "desde": {"type": "string", "description": "Primer día que no viene, tal cual lo dijo (ej. '20/11' o 'lunes')."},
                    "hasta": {"type": "string", "description": "Último día que no viene, tal cual lo dijo."},
                    "motivo": {"type": "string", "description": "Opcional, si lo dijo."},
                    "alumno": {"type": "string", "description": "Nombre del alumno, SOLO si la tool te pidió elegir entre varios."},
                    "confirmado": {"type": "boolean", "description": "true SOLO si el alumno ya confirmó las fechas completas que te dio la tool."},
                },
                "required": ["desde", "hasta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dar_de_baja",
            "description": "Da de baja al alumno de la academia, cuando confirma que quiere dejar. Preguntale el motivo antes de llamarla.",
            "parameters": {
                "type": "object",
                "properties": {"motivo": {"type": "string", "enum": ["horario", "lesion", "otro"]}},
                "required": ["motivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_cupos",
            "description": (
                "Solo lectura. Devuelve las clases GRUPALES REALES de un día que todavía tienen "
                "lugar, con día, hora y nivel. Si no hay lugar, trae alternativas cercanas del "
                "mismo nivel. Llamala apenas el alumno diga un día, cuando quiera anotarse o "
                "pregunte por lugar, cupo u horarios. Con el día alcanza: NO preguntes turno ni "
                "nivel antes. No anota a nadie."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dia": {
                        "type": "string",
                        "enum": ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado"],
                        "description": "Día que pidió el alumno.",
                    },
                    "franja": {
                        "type": "string",
                        "enum": ["manana", "tarde", "kids"],
                        "description": "Opcional. Turno, SOLO si el alumno lo dijo. Sin turno trae todo el día. "
                                       "El sábado no lo mandes: es siempre a la mañana.",
                    },
                    "nivel": {
                        "type": "string",
                        "enum": NIVELES,
                        "description": "Opcional. Nivel de juego, SOLO si el alumno lo dijo.",
                    },
                    "desde": {
                        "type": "string",
                        "description": "Opcional. Si pregunta por lugar más adelante, desde cuándo, "
                                       "tal cual lo dijo (ej. 'diciembre' o '1/12'). Si no, no lo mandes.",
                    },
                },
                "required": ["dia"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "derivar_al_encargado",
            "description": (
                "Le pasa al encargado una consulta que vos no manejás: alquiler de canchas, venta "
                "o alquiler de paletas y pelotas, torneos, eventos u otro tema que no sea clases, "
                "cuotas, pagos, faltas, recuperaciones, cambios de días o viajes. Después decile "
                "solo lo que diga 'decile', sin precios ni plazos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tema": {"type": "string", "description": "Tema corto (ej. 'alquiler de canchas', 'paletas')."},
                    "consulta": {"type": "string", "description": "Qué preguntó el alumno, en una frase."},
                },
                "required": ["tema"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "anotar_en_clase",
            "description": (
                "Anota en una clase GRUPAL fija al alumno que está escribiendo (lo busca por su "
                "número de WhatsApp). Usala SOLO cuando confirmó que quiere anotarse. Pasá el "
                "clase_id que devolvió consultar_cupos, o el día y la hora. Si el número no es "
                "alumno, la tool te pide el nombre: preguntáselo y volvé a llamarla con el nombre."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "clase_id": {"type": "integer", "description": "Id de la clase que devolvió consultar_cupos."},
                    "dia": {
                        "type": "string",
                        "enum": ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado"],
                        "description": "Día de la clase, si no tenés el clase_id.",
                    },
                    "hora": {"type": "string", "description": "Hora de la clase (ej. '10' o '18:30'), si no tenés el clase_id."},
                    "nombre": {"type": "string", "description": "Nombre real del alumno, SOLO si la tool te lo pidió y él te lo dijo."},
                    "nivel": {"type": "string", "enum": NIVELES, "description": "Opcional. Nivel de juego, SOLO si el alumno lo dijo."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pedir_cambio_dias",
            "description": (
                "El alumno que escribe quiere CAMBIAR los días u horarios fijos que viene "
                "(ej. 'desde diciembre quiero ir solo los jueves'). No sirve para sumar una clase "
                "(eso es anotar_en_clase) ni para faltar un día (avisar_ausencia). Busca lugar, "
                "arma el pedido con la fecha y la cuota nueva y lo deja pendiente para que lo "
                "apruebe el encargado. No cambia nada hasta que el encargado lo aprueba."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dias_nuevos": {
                        "type": "array",
                        "items": {"type": "string", "enum": DIAS_SEMANA},
                        "description": "Los días que quiere venir de ahora en más.",
                    },
                    "hora": {"type": "string", "description": "Opcional. Hora que pidió (ej. '10' o '18:30'), SOLO si la dijo."},
                    "dias_que_deja": {
                        "type": "array",
                        "items": {"type": "string", "enum": DIAS_SEMANA},
                        "description": "Opcional. Qué días deja, SOLO si dijo que cambia algunos y no todos.",
                    },
                    "clase_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Opcional. Ids de clase que te devolvió esta tool como opción, si eligió una.",
                    },
                    "desde": {"type": "string", "description": "Opcional. Desde cuándo, tal cual lo dijo (ej. 'diciembre' o '1/12')."},
                    "alumno": {"type": "string", "description": "Nombre del alumno, SOLO si la tool te pidió elegir."},
                    "confirmado": {"type": "boolean", "description": "true SOLO cuando el alumno confirmó el detalle que le pasaste."},
                },
                "required": ["dias_nuevos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estado_cuota",
            "description": (
                "Solo lectura. Devuelve la cuota de este mes del alumno que está escribiendo "
                "(lo busca por su número de WhatsApp): cuánto es, cuánto pagó y cuánto debe. "
                "Usala cuando pregunte cuánto debe o cuánto es su cuota. No recibe datos: "
                "nunca sirve para consultar a otra persona."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOLS_ALUMNO = _TOOLS_BASE + TOOLS_PLANILLA_ALUMNO

TOOLS_JEFE = TOOLS_ALUMNO + TOOLS_PLANILLA_JEFE + [
    {
        "type": "function",
        "function": {
            "name": "actualizar_categoria",
            "description": "Cambia la categoría (nivel de juego) de un alumno. Solo lo puede pedir el encargado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "alumno_nombre": {"type": "string"},
                    "nueva_categoria": {"type": "string"},
                },
                "required": ["alumno_nombre", "nueva_categoria"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crear_cambio_pendiente",
            "description": (
                "Le propone un cambio a un alumno, que queda pendiente de que él lo confirme. "
                "Si es un cambio de días u horarios fijos, mandá dias_nuevos (y hora, dias_que_deja "
                "o desde si los dijiste): se busca lugar y la cuota nueva. Para otra cosa, mandá "
                "solo la propuesta en texto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "alumno_nombre": {"type": "string"},
                    "propuesta": {"type": "string", "description": "Detalle en texto, si no es un cambio de días."},
                    "dias_nuevos": {"type": "array", "items": {"type": "string", "enum": DIAS_SEMANA}},
                    "hora": {"type": "string"},
                    "dias_que_deja": {"type": "array", "items": {"type": "string", "enum": DIAS_SEMANA}},
                    "clase_ids": {"type": "array", "items": {"type": "integer"}},
                    "desde": {"type": "string", "description": "Desde cuándo (ej. '1/12'). Por defecto, el 1 del mes que viene."},
                },
                "required": ["alumno_nombre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pausar_bot",
            "description": "Pausa al bot en la conversación de un alumno puntual, para que el encargado responda a mano por un rato.",
            "parameters": {
                "type": "object",
                "properties": {"alumno_nombre": {"type": "string"}},
                "required": ["alumno_nombre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reanudar_bot",
            "description": "Reactiva al bot en la conversación de un alumno, para que vuelva a responder automáticamente.",
            "parameters": {
                "type": "object",
                "properties": {"alumno_nombre": {"type": "string"}},
                "required": ["alumno_nombre"],
            },
        },
    },
]


def tools_para_rol(es_jefe: bool) -> list[dict]:
    return TOOLS_JEFE if es_jefe else TOOLS_ALUMNO