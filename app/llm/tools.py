TOOLS_ALUMNO = [
    {
        "type": "function",
        "function": {
            "name": "buscar_grupo_disponible",
            "description": (
                "Busca un grupo GRUPAL de pádel disponible por nivel de juego y, "
                "opcionalmente, día. Con el nivel de juego y el día alcanza para "
                "buscar — no hace falta ningún otro dato adicional."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nivel_juego": {
                        "type": "string",
                        "enum": ["1ra", "2da", "3ra", "4ta", "5ta", "6ta", "7ma", "8va", "principiante"],
                        "description": "Nivel de juego del alumno, NO el tipo de clase.",
                    },
                    "dia": {"type": "string"},
                },
                "required": ["nivel_juego"],
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
            "name": "consultar_estado_pago",
            "description": "Consulta si el alumno está al día con el pago del mes actual o si debe",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolver_cambio_pendiente",
            "description": (
                "Se llama cuando el alumno responde sobre una propuesta de cambio pendiente. "
                "Si el alumno dice que sí, dale, acepto, está bien, o cualquier confirmación "
                "positiva, usá decision='si_acepto'. Si dice que no, prefiere que no, o "
                "cualquier negativa, usá decision='no_rechazo'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "string",
                        "enum": ["si_acepto", "no_rechazo"],
                        "description": "si_acepto = el alumno confirmó que sí quiere el cambio. no_rechazo = el alumno no quiere el cambio.",
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
                    "categoria": {"type": "string", "description": "Nivel de juego ya mencionado en la charla"},
                },
                "required": ["nombre", "categoria"],
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
                "properties": {
                    "motivo": {"type": "string", "enum": ["horario", "lesion", "otro"]},
                },
                "required": ["motivo"],
            },
        },
    },
]

TOOLS_JEFE = TOOLS_ALUMNO + [
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
                "Inicia una propuesta que depende de la confirmación de un alumno "
                "(ej: reasignar de día u horario)."
            ),
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
                "properties": {
                    "alumno_nombre": {"type": "string"},
                },
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
                "properties": {
                    "alumno_nombre": {"type": "string"},
                },
                "required": ["alumno_nombre"],
            },
        },
    },
]


def tools_para_rol(es_jefe: bool) -> list[dict]:
    return TOOLS_JEFE if es_jefe else TOOLS_ALUMNO