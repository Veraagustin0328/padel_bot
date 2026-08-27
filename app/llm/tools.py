TOOLS = [
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
]