"""Lo que en simulacion se anota en vez de salir: los WhatsApp que se hubieran mandado
y las herramientas que uso el agente. En produccion no se anota nada (las funciones no hacen nada)."""
import threading
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from itertools import count

from app import entorno

# WhatsApp que el sistema "mando" (agente, panel, avisos). Solo en memoria: se borra al reiniciar
_bandeja = deque(maxlen=300)
_lock = threading.Lock()
_ids = count(1)

# herramientas del pedido en curso; None = nadie la esta mirando
_traza: ContextVar = ContextVar("traza_agente", default=None)


def a_la_bandeja(telefono, tipo, contenido):
    """Anota un envio en vez de mandarlo a Meta. Devuelve algo con la forma de la respuesta de Meta."""
    with _lock:
        n = next(_ids)
        _bandeja.append({
            "id": n, "telefono": telefono, "tipo": tipo, "contenido": contenido,
            "hora": datetime.now(timezone.utc).isoformat(),
        })
    print(f"[simulacion] WhatsApp a {telefono} NO enviado (queda en la bandeja #{n})", flush=True)
    return {"messaging_product": "whatsapp", "messages": [{"id": f"sim-{n}"}], "simulado": True}


def bandeja(desde_id=0, telefono=None):
    with _lock:
        return [m for m in _bandeja if m["id"] > desde_id and (not telefono or m["telefono"] == telefono)]


def ultimo_id():
    with _lock:
        return _bandeja[-1]["id"] if _bandeja else 0


def empezar_traza():
    if entorno.es_simulacion():
        _traza.set([])


def anotar(paso, **datos):
    """El agente avisa que uso una herramienta (o que respondio sin el modelo)."""
    lista = _traza.get()
    if lista is not None:
        lista.append({"paso": paso, **datos})


def terminar_traza():
    lista = _traza.get()
    _traza.set(None)
    return lista or []
