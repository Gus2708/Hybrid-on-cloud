"""
alert_util.py — Envío opcional de alertas por webhook HTTP.
Compatible con Discord, Slack Incoming Webhooks, y cualquier endpoint POST.
Configurar ALERT_WEBHOOK_URL en .env para activar.
"""
import json
import urllib.request
import urllib.error


def send_alert(severity: str, message: str) -> bool:
    """
    Envía una alerta al webhook configurado.
    severity: "info" | "warning" | "error"
    Retorna True si fue enviado exitosamente, False si no hay webhook o falla.
    """
    try:
        from config import ALERT_WEBHOOK_URL
    except ImportError:
        return False

    if not ALERT_WEBHOOK_URL:
        return False  # Alertas deshabilitadas

    icons = {"info": "ℹ️", "warning": "⚠️", "error": "🚨"}
    icon = icons.get(severity, "📢")

    payload = {
        "content": f"{icon} **[El Serrucho Backend]** {message}",
        "text": f"{icon} [El Serrucho Backend] {message}",  # compatibilidad Slack
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ALERT_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.getcode() in (200, 201, 204)
    except urllib.error.HTTPError as e:
        print(f"[ALERT] Error HTTP {e.code} enviando alerta")
        return False
    except Exception as e:
        print(f"[ALERT] Error enviando alerta: {e}")
        return False
