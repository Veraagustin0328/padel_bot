import json
from app.llm.client import client, MODEL
from app.llm.tools import TOOLS
from app.models import Grupo


def procesar_mensaje(texto: str) -> str:
    mensajes = [
        {"role": "system", "content": (
            "Sos el asistente de WhatsApp de una academia de pádel. Respondé corto y amable, "
            "con algún emoji con moderación. Cuando muestres horarios disponibles, NO menciones "
            "el nombre del profesor salvo que el alumno lo haya pedido específicamente — "
            "el profesor se asigna puertas adentro de la academia."
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

    # Ejecutamos la primera tool que pidió (por ahora solo tenemos una)
    tool_call = mensaje_modelo.tool_calls[0]
    args = json.loads(tool_call.function.arguments)
    resultado = _buscar_grupo_disponible(args)

    # Le devolvemos el resultado al modelo para que arme la respuesta final en texto
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
    query = Grupo.query.filter_by(categoria=args.get("categoria"))
    if args.get("dia"):
        query = query.filter_by(dia=args["dia"])

    grupos = query.all()
    return {
        "grupos": [
            {"profesor": g.profesor, "dia": g.dia, "horario": g.horario, "cupo_max": g.cupo_max}
            for g in grupos
        ]
    }