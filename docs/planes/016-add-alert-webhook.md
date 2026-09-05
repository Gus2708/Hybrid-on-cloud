# Plan 016: Agregar alertas opcionales por webhook ante discrepancias de sync

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- sync.py sync_ventas.py monitor.py config.py`

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

Cuando `verify_sync()` detecta una discrepancia entre el CSV local y Supabase, o cuando `auto_heal_startup` necesita intervenir, el único registro es una línea en `monitor.log`. El operador de la tienda no recibe ninguna notificación activa.

Un webhook HTTP opcional (Discord, Slack, o cualquier destino compatible) permite recibir alertas automáticas sin tener que revisar logs manualmente. La feature es completamente opt-in: si `ALERT_WEBHOOK_URL` no está en `.env`, el comportamiento actual no cambia.

## Estado actual

```python
# sync.py:252-289 — verify_sync detecta discrepancias pero solo loguea
def verify_sync(csv_count: int, force: bool = False):
    cloud_count = get_row_count_rest()
    if cloud_count != -1 and cloud_count != csv_count:
        diff = abs(cloud_count - csv_count)
        ...
        print(f"[SYNC] Discrepancia detectada ({diff} filas). Corrigiendo huérfanos...")
        # No hay alerta externa
```

```python
# monitor.py:173-191 — auto_heal detecta discrepancias pero solo loguea
if not prod_ok:
    log_monitor("  -> Discrepancia en Inventario. Solicitando sync automático...")
    sync_handler.run_sync("Auto-Healing Startup", "inventario")
    # No hay alerta externa
```

Convención de configuración del proyecto (de `config.py`): variables opcionales con default vacío.

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Verificar sintaxis | `python -c "import ast; ast.parse(open('alert_util.py').read()); print('OK')"` | OK |
| Tests | `python -m pytest tests/ -v` | Todos pasan |
| Test manual (con webhook) | `python -c "from alert_util import send_alert; send_alert('test', 'Prueba de alerta')"` | Sin errores, alerta enviada |

## Scope

**En scope**:
- `alert_util.py` — crear módulo de alertas
- `config.py` — agregar `ALERT_WEBHOOK_URL`
- `sync.py` — llamar alerta en `verify_sync()` cuando hay discrepancia
- `monitor.py` — llamar alerta en `auto_heal_startup()` cuando interviene
- `.env.example` — documentar `ALERT_WEBHOOK_URL`

**Fuera de scope**:
- `sync_ventas.py` — puede incluirse en una iteración posterior
- Email, SMS u otros canales — solo webhook HTTP en este plan

## Git workflow

- Branch: `advisor/016-add-alert-webhook`
- Commit: `feat: agregar alertas opcionales por webhook ante discrepancias de sync`

## Pasos

### Paso 1: Agregar `ALERT_WEBHOOK_URL` a `config.py`

```python
# ─── Alertas (opcional) ───────────────────────────────────────────────────────
# URL de webhook para recibir alertas (Discord, Slack, Zapier, etc.)
# Dejar vacío para deshabilitar alertas.
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")
```

### Paso 2: Crear `alert_util.py`

```python
"""
alert_util.py — Envío opcional de alertas por webhook HTTP.
Compatible con Discord, Slack incoming webhooks, y cualquier endpoint POST.
"""
import json
import urllib.request
import urllib.error


def send_alert(severity: str, message: str) -> bool:
    """
    Envía una alerta al webhook configurado.
    severity: "info", "warning", "error"
    Retorna True si fue enviado, False si no hay webhook configurado o falla.
    """
    try:
        from config import ALERT_WEBHOOK_URL
    except ImportError:
        return False

    if not ALERT_WEBHOOK_URL:
        return False  # Alertas deshabilitadas

    # Formato compatible con Discord y Slack
    icons = {"info": "ℹ️", "warning": "⚠️", "error": "🚨"}
    icon = icons.get(severity, "📢")

    payload = {
        "content": f"{icon} **[El Serrucho Backend]** {message}",
        "text": f"{icon} [El Serrucho Backend] {message}",  # Slack
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
```

**Verificar**: `python -c "from alert_util import send_alert; print('OK')"` → OK

### Paso 3: Integrar en `sync.py:verify_sync()`

En la función `verify_sync()`, después de detectar una discrepancia grande (línea ~260), agregar:

```python
# Alerta: discrepancia grande detectada
try:
    from alert_util import send_alert
    send_alert("warning", f"Discrepancia detectada: {diff} filas entre CSV local ({csv_count}) y Supabase ({cloud_count}). Posible unidad H: caída.")
except Exception:
    pass
```

Y después del auto-heal exitoso:

```python
try:
    from alert_util import send_alert
    send_alert("info", f"Auto-reconciliación completada: {len(orphans)} registros huérfanos eliminados.")
except Exception:
    pass
```

### Paso 4: Integrar en `monitor.py:auto_heal_startup()`

Cuando el auto-heal interviene (líneas 179-188), agregar después de cada `sync_handler.run_sync(...)`:

```python
try:
    from alert_util import send_alert
    send_alert("warning", "Auto-Healing: Discrepancia detectada al iniciar. Sync automático iniciado.")
except Exception:
    pass
```

### Paso 5: Documentar en `.env.example`

```
# Webhook para alertas de discrepancias de sync (opcional)
# Discord: configurar un webhook en el servidor → Editar canal → Integraciones → Webhooks
# Slack: crear un Incoming Webhook en api.slack.com/apps
# Dejar vacío para deshabilitar
ALERT_WEBHOOK_URL=
```

**Verificar**: `python -m pytest tests/ -v` → todos pasan

## Plan de tests

Crear `tests/test_alert_util.py`:

```python
def test_send_alert_sin_webhook_url_retorna_false(monkeypatch):
    """send_alert retorna False silenciosamente si no hay webhook configurado."""
    import config
    monkeypatch.setattr(config, "ALERT_WEBHOOK_URL", "")
    from alert_util import send_alert
    assert send_alert("warning", "test") is False

def test_send_alert_con_webhook_valido(mocker, monkeypatch):
    """send_alert hace POST al webhook cuando está configurado."""
    import config
    monkeypatch.setattr(config, "ALERT_WEBHOOK_URL", "https://hooks.example.com/test")
    
    mock_resp = mocker.MagicMock()
    mock_resp.getcode.return_value = 200
    mocker.patch("urllib.request.urlopen", return_value=__import__("contextlib").nullcontext(mock_resp))
    
    from alert_util import send_alert
    # Debe intentar enviar sin error
    send_alert("error", "test message")
```

## Criterios de done

- [ ] `alert_util.py` existe con `send_alert(severity, message)`
- [ ] `config.py` exporta `ALERT_WEBHOOK_URL` (default `""`)
- [ ] Si `ALERT_WEBHOOK_URL` está vacío, `send_alert()` retorna False sin hacer requests
- [ ] `sync.py:verify_sync()` llama a `send_alert` en caso de discrepancia
- [ ] `monitor.py:auto_heal_startup()` llama a `send_alert` cuando interviene
- [ ] `.env.example` documenta `ALERT_WEBHOOK_URL`
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- Las llamadas a `send_alert` dentro de `verify_sync` o `auto_heal_startup` son demasiado frecuentes (el monitor corre cada 30s) → ajustar para solo alertar cuando el estado cambia (de ok → discrepancia), no en cada ciclo

## Notas de mantenimiento

- Para Discord: crear webhook en Servidor → Editar canal → Integraciones → Webhooks → Nuevo Webhook → Copiar URL
- Para Slack: crear app en api.slack.com/apps con "Incoming Webhooks" activado
- Las alertas son fire-and-forget; si el webhook falla, el sync continúa normalmente
