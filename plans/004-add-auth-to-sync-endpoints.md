# Plan 004: Agregar autenticación por API key a los endpoints de sync

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- app.py config.py`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/002-remove-hardcoded-credentials.md` (para usar .env correctamente)
- **Category**: security
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

Los endpoints `/api/v1/sync/inventory`, `/api/v1/sync/sales`, `/api/v1/sync/run` y `/api/v1/sync/force` no tienen ningún mecanismo de autenticación. Cualquier proceso o dispositivo en la misma red local puede disparar una sincronización completa, una re-extracción forzada (que incluye lectura intensiva del disco H:), o el módulo de ventas.

El endpoint de búsqueda `/api/v1/productos` debe permanecer sin autenticación (lo usa el widget y posibles apps de catálogo). Solo los endpoints que modifican estado o disparan procesos pesados deben protegerse.

La solución más simple y adecuada para este deployment es un header `X-API-Key` con un secreto estático configurado en `.env`.

## Estado actual

```python
# app.py:96-157 — fragmento del patrón actual (sin auth en ninguno)
@app.route("/api/v1/sync/inventory", methods=["POST", "GET"])
def sync_inventory():
    try:
        from lock_util import acquire_lock
        with acquire_lock(timeout=10):
            import sync
            import importlib
            importlib.reload(sync)
            sync.sync_incremental()
        return jsonify({"status": "success", "message": "Inventario sincronizado"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/v1/sync/sales", methods=["POST", "GET"])
def sync_sales():
    # ... mismo patrón, sin auth
```

Los endpoints de lectura no tocan sync:
```python
@app.route("/api/v1/productos", methods=["GET"])   # → NO necesita auth
@app.route("/api/v1/sync/status", methods=["GET"]) # → NO necesita auth (diagnóstico)
@app.route("/health", methods=["GET"])             # → NO necesita auth (diagnóstico)
```

Convención de `config.py` para añadir variables: ya usa `os.environ.get(KEY, default)`.

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Tests | `python -m pytest tests/ -v` | Todos pasan |
| Probar sin auth | `python -m pytest tests/test_app.py -v -k "sync"` | Tests de sync pasan con mock de auth |
| Verificar import config | `python -c "from config import SYNC_API_KEY; print(bool(SYNC_API_KEY))"` | True si .env tiene el valor |

## Scope

**En scope**:
- `config.py` — agregar `SYNC_API_KEY`
- `app.py` — agregar decorator/helper de verificación, aplicarlo a los 4 endpoints de sync
- `.env` / `.env.example` — agregar `SYNC_API_KEY`

**Fuera de scope** (NO tocar):
- `remote_listener.py` — llama a sync directamente como subprocess, no usa la API HTTP
- `monitor.py` — idem
- Los endpoints de lectura (`/api/v1/productos`, `/health`, `/api/v1/sync/status`)

## Git workflow

- Branch: `advisor/004-add-sync-endpoint-auth`
- Commit: `security: agregar autenticación X-API-Key a endpoints de sync`

## Pasos

### Paso 1: Generar un API key seguro y agregarlo a `.env`

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copiar el output y agregarlo al `.env`:
```
SYNC_API_KEY=el_valor_generado_aqui
```

Y al `.env.example` (sin valor real):
```
SYNC_API_KEY=cambiar_esto_por_un_valor_generado_con_secrets.token_urlsafe
```

**Verificar**: `python -c "import os; from dotenv import load_dotenv; load_dotenv('.env'); print(bool(os.environ.get('SYNC_API_KEY')))"` → `True`

### Paso 2: Agregar `SYNC_API_KEY` a `config.py`

Agregar después de `TASA_BS_DEFAULT` en `config.py`:

```python
# ─── Autenticación de endpoints de sync ──────────────────────────────────────
# Usado por el header X-API-Key en las rutas /api/v1/sync/*
# Si está vacío, los endpoints de sync son públicos (solo para desarrollo)
SYNC_API_KEY = os.environ.get("SYNC_API_KEY", "")
```

**Verificar**: `python -c "from config import SYNC_API_KEY; print(type(SYNC_API_KEY))"` → `<class 'str'>`

### Paso 3: Agregar helper de verificación en `app.py`

Después de `app = Flask(__name__)` y `CORS(app)`, agregar:

```python
def _require_sync_key():
    """Verifica X-API-Key header para endpoints de sync. Retorna None si OK, Response si rechazado."""
    from config import SYNC_API_KEY
    if not SYNC_API_KEY:
        return None  # Sin key configurada → modo desarrollo, sin restricción
    key = request.headers.get("X-API-Key", "")
    if key != SYNC_API_KEY:
        return jsonify({"status": "error", "message": "API key inválida o ausente"}), 401
    return None
```

**Verificar**: `python -c "import ast; ast.parse(open('app.py').read()); print('OK')"` → `OK`

### Paso 4: Aplicar la verificación a los 4 endpoints de sync

En cada uno de los 4 endpoints (`sync_inventory`, `sync_sales`, `trigger_sync_all`, `trigger_sync_force`), agregar al inicio del cuerpo de la función:

```python
auth_err = _require_sync_key()
if auth_err:
    return auth_err
```

Ejemplo completo del endpoint modificado:

```python
@app.route("/api/v1/sync/inventory", methods=["POST", "GET"])
def sync_inventory():
    auth_err = _require_sync_key()
    if auth_err:
        return auth_err
    try:
        from lock_util import acquire_lock
        with acquire_lock(timeout=10):
            import sync
            import importlib
            importlib.reload(sync)
            sync.sync_incremental()
        return jsonify({"status": "success", "message": "Inventario sincronizado"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
```

Repetir el mismo patrón para `sync_sales`, `trigger_sync_all`, `trigger_sync_force`.

**Verificar**: `python -m pytest tests/test_app.py -v` → pasan los tests existentes

## Plan de tests

Agregar a `tests/test_app.py`:

```python
def test_sync_inventory_sin_api_key_rechazado(client, monkeypatch):
    """Sync endpoint retorna 401 si SYNC_API_KEY está configurada y falta el header."""
    import config
    monkeypatch.setattr(config, "SYNC_API_KEY", "test-secret-key")
    response = client.post("/api/v1/sync/inventory")
    assert response.status_code == 401

def test_sync_inventory_con_api_key_correcta(client, mocker, monkeypatch):
    """Sync endpoint acepta request con X-API-Key correcto."""
    import config
    monkeypatch.setattr(config, "SYNC_API_KEY", "test-secret-key")
    mocker.patch("app.acquire_lock", return_value=__import__("contextlib").nullcontext())
    mocker.patch("sync.sync_incremental")
    response = client.post("/api/v1/sync/inventory", headers={"X-API-Key": "test-secret-key"})
    assert response.status_code == 200

def test_sync_sin_key_configurada_es_publico(client, monkeypatch):
    """Si SYNC_API_KEY está vacío, el endpoint es accesible sin auth (modo dev)."""
    import config
    monkeypatch.setattr(config, "SYNC_API_KEY", "")
    # No debe retornar 401
    # (mockear el sync para que no ejecute realmente)
```

**Verificar**: `python -m pytest tests/test_app.py -v` → incluye los 3 nuevos tests pasando

## Criterios de done

- [ ] `.env` contiene `SYNC_API_KEY` con un valor no vacío generado con `secrets.token_urlsafe`
- [ ] `.env.example` contiene `SYNC_API_KEY` sin valor real
- [ ] `config.py` exporta `SYNC_API_KEY`
- [ ] Los 4 endpoints de sync retornan 401 sin el header correcto cuando `SYNC_API_KEY` está configurado
- [ ] `/api/v1/productos`, `/health`, `/api/v1/sync/status` son accesibles sin auth (comportamiento sin cambios)
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo los archivos en Scope fueron modificados
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- El widget o `remote_listener.py` llaman directamente a los endpoints de sync (verificar con grep) → si sí, necesitan ser actualizados para incluir el header, lo cual requiere que el plan sea expandido
- Los tests de sync existentes empiezan a fallar por 401 → los tests deben mockear config.SYNC_API_KEY = "" (o monkeypatching)

## Notas de mantenimiento

- Si en el futuro el widget o una app externa necesita llamar a los endpoints de sync, deben incluir el header `X-API-Key: <valor de SYNC_API_KEY>`
- El modo "sin restricción" cuando `SYNC_API_KEY=""` es intencional para facilitar desarrollo local sin configurar el .env
