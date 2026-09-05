TOOLS_ALUMNO = [
    {
        "type": "function",
        "function": {
            "name": "buscar_grupo_disponible",
            "description": "Busca un grupo de pádel disponible por categoría y, opcionalmente, día",
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {"type": "string"},
                    "dia": {"type": "string"},
                },
                "required": ["categoria"],
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
                "(nunca placeholders ni texto entre corchetes) y la categoría de "
                "juego que mencionó antes en la charla."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string", "description": "Nombre real del alumno, tal como te lo dijo"},
                    "categoria": {"type": "string", "description": "Categoría de juego ya mencionada en la charla"},
                },
                "required": ["nombre", "categoria"],
            },
        },
    },
    
        {
        "type": "function",
        "function": {
            "name": "reprogramar_clase",
            "description": (
                "Reprograma o recupera una clase para el alumno, en un día y horario "
                "nuevo. Cada alumno tiene derecho a UNA sola recuperación por mes. "
                "Llamala solo cuando ya tengas el día y horario nuevo confirmados."
            ),
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
]


TOOLS_JEFE = TOOLS_ALUMNO + [
    {
        "type": "function",
        "function": {
            "name": "actualizar_categoria",
            "description": "Cambia la categoría de un alumno. Solo lo puede pedir el encargado.",
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
            "description": "Propone un cambio a un alumno (por ejemplo, moverlo de día u horario), que queda esperando su confirmación",
            "parameters": {
                "type": "object",
                "properties": {
                    "alumno_nombre": {"type": "string"},
                    "propuesta": {"type": "string", "description": "Descripción clara de qué se le está proponiendo al alumno"},
                },
                "required": ["alumno_nombre", "propuesta"],
            },
        },
    },
]


def tools_para_rol(es_jefe: bool) -> list[dict]:
    return TOOLS_JEFE if es_jefe else TOOLS_ALUMNO