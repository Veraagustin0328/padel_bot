from app.planilla import TOOLS_PLANILLA_ALUMNO, TOOLS_PLANILLA_JEFE

NIVELES = ["1era", "1ra", "2da", "3ra", "4ta", "5ta", "6ta", "7ma", "8va", "principiante"]

_TOOLS_BASE = [
    {
        "type": "function",
        "function": {
            "name": "buscar_grupo_disponible",
            "description": (
                "Busca un grupo GRUPAL de pádel disponible por nivel de juego y, "
                "opcionalmente, día. Con el nivel de juego alcanza para buscar — "
                "no hace falta ningún otro dato adicional."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nivel_juego": {
                        "type": "string",
                        "enum": NIVELES,
                        "description": "Nivel de juego del alumno (1era o 1ra son lo mismo), NO el tipo de clase.",
                    },
                    "dia": {"type": "string", "description": "Opcional. Solo si el alumno mencionó un día."},
                },
                "required": ["nivel_juego"],
            },
        },
    },
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
            "name": "reprogramar_clase",
            "description": "Reprograma (recupera) una clase del alumno a otro día y horario. Solo 1 recuperación por mes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dia_nuevo": {"type": "string"},
                    "horario_nuevo": {"type": "string"},
                },
                "required": ["dia_nuevo", "horario_nuevo"],
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
                "Solo lectura. Devuelve las clases GRUPALES de un día y turno que todavía "
                "tienen lugar (cupo menos alumnos anotados hoy). Usala cuando pregunten si "
                "hay lugar, cupo o vacante en un día. No anota a nadie."
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
                        "description": "Turno: manana, tarde o kids. Si el día es sábado, poné manana.",
                    },
                    "nivel": {
                        "type": "string",
                        "enum": NIVELES,
                        "description": "Opcional. Nivel de juego, SOLO si el alumno lo dijo.",
                    },
                },
                "required": ["dia", "franja"],
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
            "description": "Inicia una propuesta que depende de la confirmación de un alumno (ej: reasignar de día u horario).",
            "parameters": {
                "type": "object",
                "properties": {
                    "alumno_nombre": {"type": "string"},
                    "propuesta": {"type": "string", "description": "Detalle en texto de qué se propone"},
                },
                "required": ["alumno_nombre", "propuesta"],
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