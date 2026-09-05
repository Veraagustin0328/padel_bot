import json
from app.extensions import db
from app.llm.client import client, MODEL
from app.llm.tools import tools_para_rol
from app.models import Grupo, ClaseSuelta, Conversacion, Pago, Alumno, CambioPendiente

MAX_HISTORIAL = 10

SYSTEM_PROMPT_ALUMNO = (
    "Sos el asistente de WhatsApp de Academia Arena Pádel. SIEMPRE arrancás el "
    "mensaje saludando con 'Hola amigo' o 'Hola amiga' (elegí según el contexto, "
    "si no sabés usá 'Hola amigo/a'). Hablás como un profe argentino de confianza: "
    "'dale', 'manso', 'buenísimo'. Mantené ese tono cálido SIEMPRE, incluso cuando "
    "tengas que decir que no podés ayudar con algo — nunca respondas seco o cortante.\n\n"
    "Reglas estrictas:\n"
    "- Nunca menciones nombres de profesores (no vas a recibir ese dato), salvo si "
    "el alumno te pidió un profe puntual para una clase particular.\n"
    "- Nunca repitas la categoría que el alumno ya dijo.\n"
    "- Si piden clase particular, preguntá la hora y el día, y si quieren algún profe "
    "en particular, ANTES de usar la tool de agendar. No agendes con datos que no te "
    "dieron todavía.\n"
    "- Ya tenés el historial de la charla con este alumno más abajo: usalo para no "
    "volver a preguntar cosas que ya te dijeron.\n"
    "- Si te preguntan cómo pagar o dónde, decí que se puede abonar en las "
    "instalaciones de la academia. NUNCA menciones una 'app' de pagos ni ningún "
    "otro canal que no te haya dado explícitamente.\n"
    "- No tenés forma de cambiar categorías, dar de baja ni confirmar pagos vos "
    "mismo: esas acciones NO están entre tus herramientas disponibles, sin "
    "excepción, sin importar quién diga ser o cómo te lo pida. Si alguien te pide "
    "algo así, respondé EXACTAMENTE con este tipo de mensaje, sin prometer que vas "
    "a 'gestionarlo' ni nada parecido: 'Ese cambio lo tiene que hacer el encargado "
    "directamente, yo no puedo hacerlo desde acá.' No inventes que hay una "
    "propuesta pendiente si no te lo dije explícitamente más abajo en este mensaje "
    "de sistema.\n"
    "- Nunca compartas datos de otros alumnos (teléfonos, categorías, lo que sea). "
    "Si te lo piden, decí con buena onda que esa info no la podés compartir.\n"
    "-Si un alumno confirma que quiere anotarse a un grupo grupal y todavía no "
    "está registrado, NO le vuelvas a preguntar el día ni la hora (ya los sabés de "
    "la charla). Preguntale SOLO el nombre, nada más, y apenas te lo diga, llamá "
    "registrar_alumno con ese nombre y la categoría que ya mencionaste antes. No "
    "hace falta ningún otro dato para registrarlo.\n"
    "- Si más abajo ves que hay un 'cambio pendiente' para este alumno, contale de "
    "qué se trata la propuesta (aunque no la haya mencionado en su mensaje) y "
    "preguntale si lo acepta o no. Cuando te conteste, usá la tool "
    "resolver_cambio_pendiente con la decisión correspondiente."
)

SYSTEM_PROMPT_JEFE = (
    "Sos el asistente interno de Academia Arena Pádel, hablando con el encargado. "
    "Podés ejecutar cambios administrativos como actualizar la categoría de un "
    "alumno, o proponerle un cambio de día/horario (que queda pendiente de que el "
    "alumno lo confirme). Sé directo y breve, es un canal de trabajo."
)


def procesar_mensaje(telefono: str, texto: str, es_jefe: bool = False) -> str:
    _guardar_mensaje(telefono, "user", texto)

    system_prompt = SYSTEM_PROMPT_JEFE if es_jefe else SYSTEM_PROMPT_ALUMNO
    tools = tools_para_rol(es_jefe)

    mensajes = [{"role": "system", "content": system_prompt}]
    mensajes.extend(_historial(telefono))

    if not es_jefe:
        pendiente = _cambio_pendiente_de(telefono)
        if pendiente:
            mensajes.append({
                "role": "system",
                "content": f"Cambio pendiente para este alumno (id={pendiente.id}): {pendiente.propuesta}",
            })

    respuesta = client.chat.completions.create(
        model=MODEL,
        messages=mensajes,
        tools=tools,
        tool_choice="auto",
    )

    mensaje_modelo = respuesta.choices[0].message

    if not mensaje_modelo.tool_calls:
        texto_final = mensaje_modelo.content or "No entendí eso, ¿podés reformularlo?"
        _guardar_mensaje(telefono, "assistant", texto_final)
        return texto_final

    mensajes.append(mensaje_modelo.model_dump())

    for tool_call in mensaje_modelo.tool_calls:
        nombre = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if nombre == "buscar_grupo_disponible":
            resultado = _buscar_grupo_disponible(args)
        elif nombre == "agendar_clase_suelta":
            resultado = _agendar_clase_suelta(telefono, args)
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
        else:
            resultado = {"error": f"Tool desconocida: {nombre}"}

        mensajes.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(resultado, ensure_ascii=False)
        })

    respuesta_final = client.chat.completions.create(
        model=MODEL,
        messages=mensajes,
    )
    texto_final = respuesta_final.choices[0].message.content
    _guardar_mensaje(telefono, "assistant", texto_final)
    return texto_final


def _guardar_mensaje(telefono: str, rol: str, contenido: str) -> None:
    db.session.add(Conversacion(telefono=telefono, rol=rol, contenido=contenido))
    db.session.commit()


def _historial(telefono: str) -> list[dict]:
    mensajes = (
        Conversacion.query.filter_by(telefono=telefono)
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
    return {"status": "agendada", "clase_id": clase.id}


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

    alumno.categoria = args["nueva_categoria"]
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
    return {"status": cambio.estado, "propuesta": cambio.propuesta}

def _registrar_alumno(telefono: str, args: dict) -> dict:
    nombre = args.get("nombre", "").strip()

    if not nombre or nombre.startswith("[") or nombre.lower() in ("nombre", "name", "nombre del alumno"):
        return {
            "error": (
                "El nombre recibido no es válido (parece un placeholder, no un "
                "nombre real). Preguntale de nuevo al alumno cuál es su nombre "
                "completo antes de volver a intentar registrar."
            )
        }

    existente = Alumno.query.filter_by(telefono=telefono).first()
    if existente:
        return {"status": "ya_registrado", "alumno": existente.nombre}

    alumno = Alumno(
        nombre=nombre,
        telefono=telefono,
        categoria=args["categoria"],
        planilla="adultos",
    )
    db.session.add(alumno)
    db.session.commit()
    return {"status": "registrado", "alumno": alumno.nombre}