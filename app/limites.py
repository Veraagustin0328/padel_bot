"""Limites de intentos con ventana corrida, en memoria.

Lo usan el registro, el login y el cambio de clave (app/routes/auth.py).
En memoria alcanza con un solo proceso (Render free, 1 worker): si el proceso se reinicia
los contadores vuelven a cero, y con mas de un worker cada uno tendria su propia cuenta.
"""
import math
import os
import threading
import time
from collections import deque


def numero_de_entorno(nombre, defecto):
    """Entero positivo de una variable de entorno; si falta o esta mal, el default."""
    try:
        valor = int(os.environ.get(nombre, ""))
    except ValueError:
        return defecto
    return valor if valor > 0 else defecto


class Ventana:
    """Hasta `maximo` marcas por clave en los ultimos `segundos`. Pasada la ventana se levanta sola."""

    def __init__(self, maximo, segundos, reloj=time.monotonic):
        self.maximo = maximo
        self.segundos = segundos
        self._reloj = reloj  # se cambia en los tests para no esperar 15 minutos
        self._marcas = {}
        self._candado = threading.Lock()

    def _limpiar(self, clave, ahora):
        cola = self._marcas.get(clave)
        while cola and ahora - cola[0] >= self.segundos:
            cola.popleft()
        if cola is not None and not cola:
            del self._marcas[clave]  # que el dict no crezca para siempre
            return None
        return cola

    def espera(self, clave):
        """0 si puede seguir; si no, cuantos segundos faltan para que se libere un lugar."""
        ahora = self._reloj()
        with self._candado:
            cola = self._limpiar(clave, ahora)
            if not cola or len(cola) < self.maximo:
                return 0
            # tiene que vencer la marca que deja la cola justo debajo del maximo
            vence = cola[len(cola) - self.maximo] + self.segundos
            return max(1, math.ceil(vence - ahora))

    def anotar(self, clave):
        with self._candado:
            self._marcas.setdefault(clave, deque()).append(self._reloj())

    def borrar(self, clave):
        with self._candado:
            self._marcas.pop(clave, None)

    def bloqueado(self, clave):
        return self.espera(clave) > 0

    def vaciar(self):
        with self._candado:
            self._marcas.clear()
