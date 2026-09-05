# Plan 017: Thread independiente para actualizar tasas cada 15 minutos

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- monitor.py sync.py rates_service.py`

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/001-fix-get-current-rate-key-mismatch.md` (para que la tasa leída sea correcta)
- **Category**: direction
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

Las tasas de cambio (BCV y Binance P2P) solo se actualizan en Supabase cuando se ejecuta `sync_incremental()` de inventario, y solo si pasó más de 1 hora desde la última actualización. Si no hay cambios en los archivos `.DAT` de HybridLite durante horas, la tasa en Supabase puede estar desactualizada.

En horario comercial, la tasa BCV puede cambiar durante el día. Las ventas que se sincronizan a última hora pueden usar una tasa de primera hora si no hubo sync de inventario entre medio.

La solución: un thread independiente en `monitor.py` que actualiza las tasas cada 15 minutos, desacoplado del ciclo de sync de inventario.

## Estado actual

```python
# sync.py:136-161 — actualización de tasas solo dentro de sync_incremental
def sync_incremental(force=False):
    ...
    # Actualizar Tasas
    try:
        last_rates_time = 0.0
        ...
        now_time = time.time()
        if force or (now_time - last_rates_time >= 3600):  # solo cada 1 hora
            print("[SYNC] Actualizando tasas de cambio...")
            service = RatesService()
            rates = service.get_all_rates()
            if service.save_to_db(rates):
                ...
    except Exception as e:
        print(f"[SYNC] Error en tasas: {e}")
```

```python
# monitor.py:197-276 — start_monitor() con el loop principal
def start_monitor():
    log_monitor(f"Iniciando monitoreo en: {WATCH_DIR}")
    ...
    while True:
        ...
        observer = Observer()
        observer.schedule(event_handler, WATCH_DIR, recursive=False)
        observer.start()
        ...
        while True:
            # Solo hace heartbeat y check de drive — no actualiza tasas
```

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Verificar sintaxis | `python -c "import ast; ast.parse(open('monitor.py').read()); print('OK')"` | OK |
| Tests | `python -m pytest tests/ -v` | Todos pasan |

## Scope

**En scope**:
- `monitor.py` — agregar función `start_rate_refresh_thread()` y llamarla desde `start_monitor()`

**Fuera de scope**:
- `sync.py` — mantener la actualización de tasas dentro de `sync_incremental` como está (no eliminar, es un fallback)
- `rates_service.py` — no modificar
- `app.py` — no modificar (podría agregar un endpoint `/api/v1/rates` en el futuro)

## Git workflow

- Branch: `advisor/017-independent-rate-refresh`
- Commit: `feat: thread independiente para refrescar tasas BCV/Binance cada 15 min`

## Pasos

### Paso 1: Agregar función `start_rate_refresh_thread()` en `monitor.py`

Después de la función `log_monitor()` y antes de `auto_heal_startup()`, agregar:

```python
RATE_REFRESH_INTERVAL = 15 * 60  # 15 minutos en segundos

def rate_refresh_worker():
    """Thread daemon que actualiza las tasas BCV y Binance en Supabase cada 15 minutos."""
    log_monitor("Rate refresh thread iniciado (intervalo: 15 min).")
    while True:
        try:
            from rates_service import RatesService
            service = RatesService()
            rates = service.get_all_rates()
            if service.save_to_db(rates):
                log_monitor(f"Tasas actualizadas: BCV={rates.get('bcv_usd', 0):.2f}, Binance={rates.get('binance_p2p', 0):.2f}")
            else:
                log_monitor("Error al guardar tasas en Supabase.")
        except Exception as e:
            log_monitor(f"Error en rate refresh: {e}")
        
        time.sleep(RATE_REFRESH_INTERVAL)


def start_rate_refresh_thread():
    """Inicia el thread de actualización de tasas como daemon."""
    t = threading.Thread(target=rate_refresh_worker, daemon=True, name="rate-refresh")
    t.start()
    return t
```

**Verificar**: `python -c "import ast; ast.parse(open('monitor.py').read()); print('OK')"` → OK

### Paso 2: Llamar `start_rate_refresh_thread()` desde `start_monitor()`

En `start_monitor()`, después de que la unidad H: esté disponible y antes de iniciar el Observer (alrededor de la línea donde se crea `event_handler`), agregar:

```python
# Iniciar thread de actualización de tasas (solo una vez)
_rate_thread_started = False

# ... dentro del while externo, antes del Observer:
if not _rate_thread_started:
    start_rate_refresh_thread()
    _rate_thread_started = True
    log_monitor("Thread de actualización de tasas iniciado.")
```

Mejor posición: justo después de verificar que H: está online por primera vez:

```python
if _drive_was_offline:
    log_monitor("✅ Unidad H: RECONECTADA.")
    _drive_was_offline = False

event_handler = SyncTriggerHandler()

if _needs_auto_heal:
    threading.Thread(target=auto_heal_startup, args=(event_handler,), daemon=True).start()
    _needs_auto_heal = False

# Iniciar rate refresh thread (solo la primera vez que H: está disponible)
if not _rate_thread_started:
    start_rate_refresh_thread()
    _rate_thread_started = True
```

La variable `_rate_thread_started` debe definirse antes del while externo:
```python
def start_monitor():
    ...
    _rate_thread_started = False
    while True:
        ...
```

**Verificar**: `python -c "import ast; ast.parse(open('monitor.py').read()); print('OK')"` → OK
**Verificar**: `python -m pytest tests/ -v` → todos pasan

## Plan de tests

No hay tests para `monitor.py` actualmente. Para este plan, agregar una verificación de importación:

```python
# En tests/test_monitor.py (crear si no existe):
def test_rate_refresh_thread_funcion_existe():
    """start_rate_refresh_thread existe y es callable."""
    from monitor import start_rate_refresh_thread, rate_refresh_worker
    assert callable(start_rate_refresh_thread)
    assert callable(rate_refresh_worker)
```

## Criterios de done

- [ ] `monitor.py` contiene `rate_refresh_worker()` y `start_rate_refresh_thread()`
- [ ] `start_monitor()` llama a `start_rate_refresh_thread()` cuando H: está disponible
- [ ] `RATE_REFRESH_INTERVAL = 15 * 60` está definido como constante
- [ ] `python -c "import ast; ast.parse(open('monitor.py').read()); print('OK')"` → OK
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo `monitor.py` fue modificado
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- El scraping del BCV o Binance falla sistemáticamente en horario comercial → el thread solo loguea el error y duerme 15 min, no hay impacto en el resto del sistema
- 15 minutos es demasiado frecuente y genera carga en los servicios externos → cambiar `RATE_REFRESH_INTERVAL` a 30 o 60 minutos

## Notas de mantenimiento

- El thread es daemon: si el monitor.py termina, el thread de tasas también termina (comportamiento correcto)
- El primer refresh ocurre inmediatamente al iniciar el thread — si se prefiere esperar 15 min antes del primer refresh, agregar `time.sleep(RATE_REFRESH_INTERVAL)` al inicio de `rate_refresh_worker()`
- Las tasas del `sync_incremental` (sync.py) siguen corriendo cada 1 hora como backup
