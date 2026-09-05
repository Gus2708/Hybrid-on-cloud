# Plan 007: Reemplazar `importlib.reload()` en endpoints Flask con llamadas limpias

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- app.py`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (puede hacerse independientemente de plan 004)
- **Category**: tech-debt
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

Los endpoints de sync en `app.py` usan `import sync; importlib.reload(sync); sync.sync_incremental()`. Este patrón:

1. **No es thread-safe**: si dos requests llegan simultáneamente, ambas recargan el módulo sobre el mismo estado global, potencialmente corrompiendo variables como `_retry_count` en `supabase_rest.py`.
2. **Rompe referencias**: código que ya tiene una referencia a `sync.sync_incremental` antes del reload ve la versión vieja.
3. **Es innecesario**: los módulos de sync están diseñados para llamarse como funciones puras (leen archivos y llaman a Supabase), no necesitan recargarse.

La solución es importar los módulos de sync al inicio de `app.py` (como variables de módulo) y llamar sus funciones directamente. Para `sync/inventory` y similares que necesitan ejecutarse en background, lanzar un subproceso (como ya hace `run_hybrid_exporter` en `sync.py`).

## Estado actual

```python
# app.py:96-156 — los 4 endpoints con el patrón reload
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

@app.route("/api/v1/sync/run", methods=["POST", "GET"])
def trigger_sync_all():
    def run_all():
        try:
            from lock_util import acquire_lock
            with acquire_lock(timeout=10):
                import sync
                import sync_ventas
                import importlib
                importlib.reload(sync)
                importlib.reload(sync_ventas)
                sync.sync_incremental()
                sync_ventas.sync_incremental()
        except: pass
    
    threading.Thread(target=run_all, daemon=True).start()
    return jsonify({"status": "success", "message": "Sincronización completa iniciada"})
```

Patrón ejemplar del proyecto para llamadas a sync (ya correcto en `monitor.py:107-128`):

```python
# monitor.py:107-128 — patrón a seguir
def sync_worker():
    try:
        from lock_util import acquire_lock
        ...
        with acquire_lock(timeout=60):
            if sync_type == "ventas":
                import sync_ventas
                import importlib
                importlib.reload(sync_ventas)
                sync_ventas.sync_incremental()
```

> Nota: `monitor.py` también usa reload. El objetivo de este plan es limpiar al menos `app.py`. `monitor.py` puede limpiarse en una iteración posterior.

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Tests antes | `python -m pytest tests/test_app.py -v` | Todos pasan (baseline) |
| Verificar no hay reload | `Select-String -Path app.py -Pattern "importlib.reload"` | Sin matches |
| Tests después | `python -m pytest tests/ -v` | Todos pasan |

## Scope

**En scope**:
- `app.py` — eliminar `importlib.reload` de los 4 endpoints de sync

**Fuera de scope**:
- `monitor.py` — también usa reload, pero cambiarlo aquí es un cambio de mayor alcance que puede hacerse independientemente
- `remote_listener.py` — ídem

## Git workflow

- Branch: `advisor/007-remove-importlib-reload-app`
- Commit: `refactor: eliminar importlib.reload() en endpoints Flask, usar imports estáticos`

## Pasos

### Paso 1: Agregar imports de sync al inicio de `app.py`

Después de `from flask_cors import CORS`, agregar:

```python
import sync as _sync_module
import sync_ventas as _sync_ventas_module
```

Si estos imports fallan al inicio (porque los módulos tienen side-effects al importarse), usar imports lazy dentro de las funciones pero sin reload:

```python
# Alternativa si los imports al inicio causan problemas:
# Los imports lazy dentro de la función son aceptables, solo eliminar el reload
```

**Verificar**: `python -c "import app; print('OK')"` → OK (sin errores)

### Paso 2: Reemplazar el patrón reload en los 4 endpoints

**`sync_inventory`** — reemplazar:
```python
# ANTES:
import sync
import importlib
importlib.reload(sync)
sync.sync_incremental()

# DESPUÉS:
import sync
sync.sync_incremental()
```

**`sync_sales`** — mismo patrón:
```python
import sync_ventas
sync_ventas.sync_incremental()
```

**`trigger_sync_all`** — en la función interna `run_all`:
```python
import sync
import sync_ventas
sync.sync_incremental()
sync_ventas.sync_incremental()
```

**`trigger_sync_force`** — en la función interna `run_force`:
```python
import sync
import sync_ventas
sync.sync_incremental(force=True)
sync_ventas.sync_incremental()
```

También eliminar el `import importlib` que quedará sin usar.

**Verificar**: `Select-String -Path app.py -Pattern "importlib"` → sin matches
**Verificar**: `python -c "import ast; ast.parse(open('app.py').read()); print('OK')"` → OK

### Paso 3: Verificar tests

```powershell
python -m pytest tests/test_app.py -v
```

Los tests de sync mockean `sync.sync_incremental` — deberían seguir funcionando. Si alguno falla porque esperaba que se hiciera reload antes de llamar a la función, actualizar el mock:

```python
# El mock correcto después de la fix:
mocker.patch("sync.sync_incremental")  # mismo que antes, sin cambios
```

**Verificar**: `python -m pytest tests/ -v` → todos pasan

## Plan de tests

Los tests existentes de `test_app.py` ya mockean los módulos de sync. Agregar una verificación explícita:

```python
def test_sync_inventory_no_usa_reload(client, mocker):
    """El endpoint de sync no debe usar importlib.reload."""
    import inspect, app
    source = inspect.getsource(app.sync_inventory)
    assert "importlib" not in source
    assert "reload" not in source
```

**Verificar**: `python -m pytest tests/test_app.py::test_sync_inventory_no_usa_reload -v` → pasa

## Criterios de done

- [ ] `Select-String -Path app.py -Pattern "importlib.reload"` → sin matches
- [ ] `Select-String -Path app.py -Pattern "^import importlib"` → sin matches (a menos que se use en otro lugar)
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo `app.py` fue modificado
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- Al remover el reload, los módulos `sync` o `sync_ventas` fallan en llamadas repetidas porque tienen estado global que se necesita reiniciar → investigar qué estado es ese y limpiar manualmente o con un patrón `reset()` en los módulos

## Notas de mantenimiento

- `monitor.py` y `remote_listener.py` también usan `importlib.reload`. Limpiarlos en una siguiente iteración usando el mismo patrón.
- El patrón recomendado para sync es importar el módulo una vez y llamar su función. Si se necesita "estado fresco", la función misma debe encargarse de leer los archivos/config al inicio (como ya hace `sync_incremental` leyendo el CSV en cada llamada).
