import json
from app.extensions import db
from app.llm.client import client, MODEL
from app.llm.tools import TOOLS
from app.models import Grupo


def procesar_mensaje(texto: str) -> str:
    mensajes = [
        {"role": "system", "content": (
            "Sos el asistente de WhatsApp de Academia Arena Pádel. SIEMPRE arrancás el "
            "mensaje saludando con 'Hola amigo' o 'Hola amiga' (elegí según el contexto, "
            "si no sabés usá 'Hola amigo/a'). Hablás como un profe argentino de confianza: "
            "'dale', 'manso', 'buenísimo'. Por ejemplo: 'Hola amigo, tenemos disponibilidad "
            "los lunes a las 7, 8 y 9. ¿Cuál te viene mejor?'\n\n"
            "Reglas estrictas:\n"
            "- Nunca menciones nombres de profesores (no vas a recibir ese dato).\n"
            "- Nunca repitas la categoría que el alumno ya dijo.\n"
            "- Si piden clase particular, preguntá la hora y si quieren algún profe en "
            "particular, antes de cualquier otra cosa."
        )},
        {"role": "user", "content": texto},
    ]

    respuesta = client.chat.completions.create(
        model=MODEL,
        messages=mensajes,
        tools=TOOLS,
        tool_choice="auto",
    )

    mensaje_modelo = respuesta.choices[0].message

    if not mensaje_modelo.tool_calls:
        return mensaje_modelo.content or "No entendí eso, ¿podés reformularlo?"

    tool_call = mensaje_modelo.tool_calls[0]
    args = json.loads(tool_call.function.arguments)
    resultado = _buscar_grupo_disponible(args)

    mensajes.append(mensaje_modelo.model_dump())
    mensajes.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": json.dumps(resultado, ensure_ascii=False),
    })

    respuesta_final = client.chat.completions.create(
        model=MODEL,
        messages=mensajes,
    )
    return respuesta_final.choices[0].message.content


def _buscar_grupo_disponible(args: dict) -> dict:
    categoria = args.get("categoria", "").strip().lower()
    dia = args.get("dia", "").strip().lower()

    query = Grupo.query.filter(db.func.lower(Grupo.categoria) == categoria)
    if dia:
        query = query.filter(db.func.lower(Grupo.dia) == dia)

    grupos = query.all()
    return {
        "grupos": [
            {"dia": g.dia, "horario": g.horario, "cupo_max": g.cupo_max}
            for g in grupos
        ]
    }