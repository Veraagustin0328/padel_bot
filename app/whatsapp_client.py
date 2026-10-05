import os
import requests


def _normalizar_telefono(telefono: str) -> str:
    # WhatsApp manda los móviles argentinos como 549 + área + número,
    # pero la lista de destinatarios de prueba de Meta los guarda como
    # 54 + área + 15 + número. Esto es solo para el sandbox.
    if not telefono.startswith("549"):
        return telefono

    resto = telefono[3:]  # área + número (10 dígitos)
    largo_area = 2 if resto.startswith("11") else 3  # 11 = Buenos Aires, el resto 3 (261 = Mendoza)
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