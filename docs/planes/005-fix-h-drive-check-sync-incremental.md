# Plan 005: Corregir verificación de unidad H: en `sync_incremental()`

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- sync.py config.py`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

`sync_incremental()` en `sync.py` intenta verificar que la unidad H: está disponible antes de ejecutar la extracción. Sin embargo, chequea `os.path.exists(os.path.dirname(CSV_SOURCE_PATH))`, que es el directorio del proyecto (`C:\Proyect\backend serrucho\`), **no** la unidad H:. Esta verificación siempre pasa aunque H: esté desconectada.

La protección real recae en `run_hybrid_exporter()` que llama a `actualizar_inventario.py` y falla si H: no está accesible — pero el mensaje de error en ese caso es genérico. La guard temprana debería ser un check explícito de H: usando las rutas configuradas en `config.py`.

## Estado actual

```python
# sync.py:124-133
def sync_incremental(force=False):
    # Validar unidad H: antes de empezar
    if not os.path.exists(os.path.dirname(CSV_SOURCE_PATH)):
        #                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        # BUG: os.path.dirname("C:\Proyect\backend serrucho\MAESTRO_ACTUAL.csv")
        #      = "C:\Proyect\backend serrucho\" → siempre existe
        print("[SYNC] ! ERROR: Unidad de red H: no accesible. Abortando.")
        return

    result = run_hybrid_exporter(force=force)
    if result is False:
        print("[SYNC] Extracción fallida (unidad de red probablemente caída). Abortando sync.")
        return
```

```python
# config.py:57-59 — rutas configuradas correctas
RUTA_INVENTARIO = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TInventario.dat'
RUTA_PRECIOS    = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat'
RUTA_EXISTENCIA = r'H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat'
```

La convención del proyecto para chequear la unidad H: ya existe en `monitor.py` y `network_util.py`:

```python
# monitor.py:110 y 220 — ejemplo del patrón correcto
from network_util import check_drive
if not check_drive(WATCH_DIR):
    log_monitor(f"ERROR: Unidad H: no accesible para sync {sync_type}")
    return
```

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Tests | `python -m pytest tests/ -v` | Todos pasan |
| Verificar importación | `python -c "from sync import sync_incremental; print('OK')"` | OK |

## Scope

**En scope**:
- `sync.py` — solo el check en `sync_incremental()` (líneas 125-128)

**Fuera de scope**:
- `sync_ventas.py` — tiene su propio check (líneas 169-172) que ya es correcto: `if not os.path.exists(base_h):`
- `network_util.py` — no modificar
- `config.py` — no modificar

## Git workflow

- Branch: `advisor/005-fix-h-drive-check`
- Commit: `fix: corregir verificación de unidad H: en sync_incremental`

## Pasos

### Paso 1: Reemplazar el check incorrecto con `check_drive`

En `sync.py`, la sección de imports ya tiene acceso a `config`. Agregar el import de `network_util`:

Al inicio de `sync_incremental()`, reemplazar:

```python
def sync_incremental(force=False):
    # Validar unidad H: antes de empezar
    if not os.path.exists(os.path.dirname(CSV_SOURCE_PATH)):
        print("[SYNC] ! ERROR: Unidad de red H: no accesible. Abortando.")
        return
```

Por:

```python
def sync_incremental(force=False):
    # Validar unidad H: antes de empezar
    try:
        from config import RUTA_INVENTARIO
        from network_util import check_drive
        if not check_drive(os.path.dirname(RUTA_INVENTARIO)):
            print("[SYNC] ! ERROR: Unidad de red H: no accesible. Abortando.")
            return
    except Exception as e:
        print(f"[SYNC] ! No se pudo verificar unidad H:: {e}")
        # Continuar de todas formas — run_hybrid_exporter fallará si H: está caída
```

El import dentro de la función evita dependencia circular con `config` (ya importado en el módulo) y sigue el patrón de imports locales que usa el resto del archivo.

**Verificar**: `python -c "import ast; ast.parse(open('sync.py').read()); print('OK')"` → `OK`

### Paso 2: Verificar que los tests no rompen

```powershell
python -m pytest tests/test_sync.py -v
```

Los tests de `sync_incremental` ya mockean `os.path.exists`. Puede que sea necesario actualizar los mocks para que incluyan `network_util.check_drive`.

Si `test_sync_incremental_no_changes` o `test_sync_incremental_with_changes` fallan por el nuevo import, agregar mock al inicio de cada test:

```python
mocker.patch("network_util.check_drive", return_value=True)
```

**Verificar**: `python -m pytest tests/ -v` → todos pasan

## Plan de tests

Agregar a `tests/test_sync.py`:

```python
def test_sync_incremental_aborta_si_h_no_disponible(mocker):
    """sync_incremental no continúa si la unidad H: no está accesible."""
    mocker.patch("network_util.check_drive", return_value=False)
    mock_exporter = mocker.patch("sync.run_hybrid_exporter")
    
    sync.sync_incremental()
    
    # No debe llamar al exportador si H: no está disponible
    assert mock_exporter.call_count == 0

def test_sync_incremental_continua_si_h_disponible(mocker):
    """sync_incremental llama al exportador cuando H: está accesible."""
    mocker.patch("network_util.check_drive", return_value=True)
    mocker.patch("sync.run_hybrid_exporter", return_value=True)
    mocker.patch("sync._load_csv", return_value=[])
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("builtins.open", mocker.mock_open())
    mocker.patch("json.dump")
    mocker.patch("sync.verify_sync")
    
    sync.sync_incremental()
    
    assert sync.run_hybrid_exporter.call_count == 1
```

**Verificar**: `python -m pytest tests/test_sync.py -v` → incluye los 2 nuevos tests pasando

## Criterios de done

- [ ] `sync.py:sync_incremental()` no usa `os.path.dirname(CSV_SOURCE_PATH)` para verificar H:
- [ ] El check usa `check_drive` de `network_util` o `os.path.exists` sobre un path real en H:
- [ ] `python -m pytest tests/ -v` → todos pasan, incluyendo los nuevos tests
- [ ] Solo `sync.py` fue modificado
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- `network_util.check_drive()` no está disponible o la función tiene una firma diferente → verificar `network_util.py` antes de proceder, y adaptar el check

## Notas de mantenimiento

- Si `CSV_SOURCE_PATH` o `RUTA_INVENTARIO` se mueven a una unidad diferente, este check debe actualizarse
- El patrón `check_drive` de `network_util` es el correcto para este proyecto; mantenerlo consistente con `monitor.py`
