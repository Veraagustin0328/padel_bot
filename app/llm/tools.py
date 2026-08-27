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
    }
]