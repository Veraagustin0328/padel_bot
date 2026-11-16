"""Entorno: produccion (la base y la planilla reales) o simulacion (rama de Neon y copia de la planilla).

Se decide una sola vez, al importar el paquete app, antes de que nadie lea variables:
- En Render siempre es produccion y no pregunta nada (Render pone la variable RENDER sola).
- En la PC: ENTORNO=produccion carga .env y pide escribir PRODUCCION.
  ENTORNO=simulacion carga .env y encima .env.simulacion, y frena si algo apunta a lo real.
  Sin ENTORNO: simulacion si existe .env.simulacion; si todavia no existe, produccion con confirmacion.

Lo "real" sale del .env de la PC (host de DATABASE_URL y GOOGLE_SHEET_ID), nada hardcodeado.
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values, load_dotenv

PRODUCCION = "produccion"
SIMULACION = "simulacion"
PALABRA = "PRODUCCION"  # lo que hay que escribir para usar lo real
# marca interna: el reloader de Flask relanza el proceso y no queremos preguntar dos veces
_MARCA = "_PADEL_PRODUCCION_CONFIRMADA"

RAIZ = Path(__file__).resolve().parent.parent

_actual = None


class EntornoError(RuntimeError):
    pass


def _host(url):
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _huellas_reales(raiz):
    """Host de la base y id de la planilla de produccion, leidos del .env sin cargarlo."""
    archivo = raiz / ".env"
    if not archivo.exists():
        return "", ""
    valores = dotenv_values(archivo)
    return _host(valores.get("DATABASE_URL")), (valores.get("GOOGLE_SHEET_ID") or "").strip()


def _confirmar_produccion(host, entrada=input):
    if os.environ.get(_MARCA) == "1":
        return
    if not sys.stdin or not sys.stdin.isatty():
        raise EntornoError(
            "Esto apunta a la base REAL y no hay consola para confirmar. Freno.")
    print("\n" + "=" * 60, flush=True)
    print(f"  OJO: vas a usar la base REAL ({host or 'sin host'}) y la planilla real.", flush=True)
    print(f"  Escribi {PALABRA} para seguir, cualquier otra cosa corta.", flush=True)
    print("=" * 60, flush=True)
    try:
        respuesta = entrada("> ")
    except (EOFError, KeyboardInterrupt):
        # en Windows NUL dice que es consola, asi que puede llegar aca sin nadie escribiendo
        raise EntornoError("No se confirmo. No toque nada.") from None
    if respuesta.strip() != PALABRA:
        raise EntornoError("No se confirmo. No toque nada.")
    os.environ[_MARCA] = "1"


def _verificar_simulacion(host_real, hoja_real):
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise EntornoError(".env.simulacion no tiene DATABASE_URL. Freno.")
    if host_real and _host(url) == host_real:
        raise EntornoError("Simulacion apunta a la base REAL. Revisa DATABASE_URL en .env.simulacion.")
    hoja = (os.environ.get("GOOGLE_SHEET_ID") or "").strip()
    if hoja_real and hoja == hoja_real:
        raise EntornoError("Simulacion apunta a la planilla REAL. Revisa GOOGLE_SHEET_ID en .env.simulacion.")
    # que el agente nunca le escriba a nadie de verdad
    os.environ["WHATSAPP_TOKEN"] = ""
    os.environ["SIMULACION"] = "1"


def preparar(raiz=RAIZ, entrada=input):
    """Carga las variables del entorno elegido y aplica la proteccion. Se puede llamar varias veces."""
    global _actual
    if _actual:
        return _actual

    if os.environ.get("RENDER"):
        load_dotenv(raiz / ".env")
        _actual = PRODUCCION
        return _actual

    pedido = (os.environ.get("ENTORNO") or "").strip().lower()
    hay_sim = (raiz / ".env.simulacion").exists()
    if not pedido:
        pedido = SIMULACION if hay_sim else PRODUCCION
    if pedido not in (PRODUCCION, SIMULACION):
        raise EntornoError(f"ENTORNO='{pedido}' no existe: usa produccion o simulacion.")

    host_real, hoja_real = _huellas_reales(raiz)
    if pedido == SIMULACION:
        if not hay_sim:
            raise EntornoError("Pediste simulacion pero no esta el archivo .env.simulacion.")
        # .env primero (claves del LLM, JWT, credenciales de Google) y encima lo de simulacion.
        # override porque algunos scripts ya cargaron el .env antes de importar app
        load_dotenv(raiz / ".env")
        load_dotenv(raiz / ".env.simulacion", override=True)
        _verificar_simulacion(host_real, hoja_real)
    else:
        load_dotenv(raiz / ".env")
        os.environ.pop("SIMULACION", None)
        _confirmar_produccion(_host(os.environ.get("DATABASE_URL")), entrada)

    _actual = pedido
    return _actual


def actual():
    return _actual or preparar()


def es_simulacion():
    return actual() == SIMULACION
