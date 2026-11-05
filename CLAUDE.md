# padel_bot: Academia Arena Pádel

Agente de WhatsApp + panel de gestión. Se llama "agente", no "bot".

## Stack
- Backend: Flask + SQLAlchemy, Neon Postgres. Deploy en Render (plan free).
- Panel: React 18 + Vite en /frontend. Llamadas con `api(path, { metodo, cuerpo })` desde `../api.js`.
- Agente: app/llm/agent.py + tools.py (LLM gpt-oss-20b, modelo chico e inestable).
- Auth: `@requiere_login("encargado")` de app.routes.auth. El admin siempre pasa.
- Comprobantes viven en la pestaña "comprobantes" de la planilla de Google, no en Neon. Su id es el número de fila.

## Reglas de negocio
- Promo 2x1 solo lunes, miércoles y viernes de 9 a 12.
- Inscripción $25.000, pago único por alumno.
- Recuperaciones en el mismo mes, con aviso de 24 hs.
- Reemplazo por viaje solo por el lapso del viaje.
- Cada profe ve solo sus clases.
- Nunca inventar precios: si no hay tarifa exacta, derivar al encargado.
- Nada hardcodeado de "Arena": nombre, colores y reglas tienen que ser configurables (se va a vender a otros clubes).

## Estilo del agente
- Voseo rioplatense (tenés, podés, avisame), nunca tuteo de España ni usted.
- Tono de amigo, con buena onda, algunos emojis, saludo según la hora.
- Emojis en el código Python se escriben como escapes \UXXXXXXXX, no pegados.

## Cómo trabajar
- Una tarea por sesión. Alcance cerrado: tocá solo los archivos que hagan falta, no explores el repo entero.
- Devolvé los archivos completos, no diffs.
- Comentarios en español argentino informal, cortos.
- Antes de commitear: py_compile de los .py tocados, npm run build si tocaste frontend, y mostrame un resumen corto.
- Esperá mi OK para commitear. Sin push salvo que lo pida.
- Mensajes de commit en español, sin tildes.
- No commitees scripts locales: migrar_*.py, probar_*.py, importar_*.py, corregir_*.py, crear_admin.py, borrar_historial.py ni los .csv.
- Las migraciones se dejan como script local suelto en la raíz, que se pueda correr más de una vez.
- Al final de la tarea: resumen corto + git log --oneline -5. No pegues los archivos.

## Entorno del usuario
- Windows + PowerShell. venv: `.\venv\Scripts\Activate.ps1`. Servidor local: `python run.py`.