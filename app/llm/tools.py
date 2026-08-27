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
]


def tools_para_rol(es_jefe: bool) -> list[dict]:
    return TOOLS_JEFE if es_jefe else TOOLS_ALUMNO