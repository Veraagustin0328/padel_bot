import os
import requests


def enviar_mensaje_whatsapp(telefono: str, texto: str) -> dict:
    # strip() por si la variable en Render quedó con enters o espacios al final
    token = os.environ.get("WHATSAPP_TOKEN", "").strip()
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "text",
        "text": {"body": texto},
    }

    respuesta = requests.post(url, headers=headers, json=payload)

    # si Meta rechaza el envío, lo dejamos en los logs para verlo
    if not respuesta.ok:
        print(f"Error al enviar WhatsApp ({respuesta.status_code}): {respuesta.text}")

    return respuesta.json()