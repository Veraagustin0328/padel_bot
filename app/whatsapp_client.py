import os
import requests


def _normalizar_telefono(telefono: str) -> str:
    # WhatsApp manda los móviles argentinos como 549 + área + número,
    # pero la lista de destinatarios de prueba de Meta los guarda como
    # 54 + área + 15 + número. Esto es solo para el sandbox.
    if not telefono.startswith("549"):
        return telefono

    resto = telefono[3:]  # área + número (10 dígitos)
    # 11 = Buenos Aires (2 dígitos), 261 = Gran Mendoza (3 dígitos),
    # el resto de Mendoza (2622, 2634, etc.) tiene 4 dígitos
    if resto.startswith("11"):
        largo_area = 2
    elif resto.startswith("261"):
        largo_area = 3
    elif resto.startswith("26"):
        largo_area = 4
    else:
        largo_area = 3
    area = resto[:largo_area]
    numero = resto[largo_area:]
    return f"54{area}15{numero}"


def enviar_mensaje_whatsapp(telefono: str, texto: str) -> dict:
    # strip() por si la variable en Render quedó con enters o espacios al final
    token = os.environ.get("WHATSAPP_TOKEN", "").strip()
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()

    destino = _normalizar_telefono(telefono)

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "text",
        "text": {"body": texto},
    }

    respuesta = requests.post(url, headers=headers, json=payload)

    # dejamos en los logs a quién le mandamos y si Meta lo rechazó
    print(f"Enviando WhatsApp a {destino} (original: {telefono}) -> {respuesta.status_code}", flush=True)
    if not respuesta.ok:
        print(f"Error al enviar WhatsApp ({respuesta.status_code}): {respuesta.text}", flush=True)

    return respuesta.json()


def reenviar_archivo_whatsapp(telefono: str, tipo: str, media_id: str,
                              caption: str = "", filename: str | None = None) -> dict:
    """Reenvía una imagen o documento que ya recibimos (por su media id) a otro número."""
    token = os.environ.get("WHATSAPP_TOKEN", "").strip()
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    destino = _normalizar_telefono(telefono)

    cuerpo = {"id": media_id, "caption": caption}
    if tipo == "document" and filename:
        cuerpo["filename"] = filename
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": tipo,
        tipo: cuerpo,
    }

    respuesta = requests.post(
        f"https://graph.facebook.com/v21.0/{phone_id}/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
    )
    print(f"Reenviando {tipo} a {destino} -> {respuesta.status_code}", flush=True)
    if not respuesta.ok:
        print(f"Error al reenviar {tipo} ({respuesta.status_code}): {respuesta.text}", flush=True)
    return respuesta.json()
