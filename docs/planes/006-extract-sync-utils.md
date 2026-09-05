# Plan 006: Extraer utilidades duplicadas a `sync_utils.py`

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- sync.py sync_ventas.py`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

`sync.py` y `sync_ventas.py` tienen copias idénticas de tres funciones utilitarias:

- `safe_decimal()` — convierte strings venezolanos ("1.500,50") a float
- `set_priority_low()` — reduce la prioridad del proceso en Windows
- `_kill_proc()` — mata un subproceso forzadamente

Estas funciones ya empezaron a divergir: `sync_ventas.py` tiene `_exponential_backoff()` que `sync.py` no tiene directamente (lo tiene en `supabase_rest.py`). Cualquier bugfix aplicado en uno no se propaga al otro automáticamente.

Extraer a un módulo compartido `sync_utils.py` elimina la duplicación y hace que un fix se aplique en ambos lados.

## Estado actual

```python
# sync.py:22-44 (y equivalentes en sync_ventas.py:18-46)

def set_priority_low():
    """Establece prioridad baja para no impactar el rendimiento de Windows."""
    if sys.platform == "win32":
        try:
            import win32api, win32process, win32con
            pid = win32api.GetCurrentProcessId()
            handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, True, pid)
            win32process.SetPriorityClass(handle, win32process.BELOW_NORMAL_PRIORITY_CLASS)
        except: pass

def _kill_proc(proc):
    """Mata un proceso forzadamente en Windows."""
    try:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=5)
            proc.wait(timeout=5)
    except: pass

def safe_decimal(val):
    if val is None: return 0.0
    s = str(val).strip()
    if not s: return 0.0
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    try: return float(s)
    except: return 0.0
```

```python
# sync_ventas.py:86-87 — solo en sync_ventas, no en sync.py
def _exponential_backoff(attempt: int) -> float:
    return min(1.5 ** attempt, 15.0)
```

Convención del proyecto: módulos utilitarios ya existen (`lock_util.py`, `network_util.py`, `supabase_rest.py`). El nuevo módulo debe seguir el mismo estilo.

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Tests antes | `python -m pytest tests/ -v` | Todos pasan (baseline) |
| Verificar imports | `python -c "from sync_utils import safe_decimal, set_priority_low, _kill_proc; print('OK')"` | OK |
| Tests después | `python -m pytest tests/ -v` | Todos pasan |

## Scope

**En scope** (únicos archivos a modificar):
- `sync_utils.py` — crear nuevo archivo con las funciones compartidas
- `sync.py` — reemplazar definiciones por imports de `sync_utils`
- `sync_ventas.py` — ídem

**Fuera de scope**:
- `supabase_rest.py` — tiene su propia lógica de backoff, no mezclar
- `actualizar_inventario.py`, `extraer_ventas.py` — verificar si usan alguna de estas funciones (probablemente no)
- Ningún test existente debe ser modificado por esta refactorización

## Git workflow

- Branch: `advisor/006-extract-sync-utils`
- Commit: `refactor: extraer safe_decimal, set_priority_low, _kill_proc a sync_utils.py`

## Pasos

### Paso 1: Crear `sync_utils.py`

Crear `C:\Proyect\backend serrucho\sync_utils.py` con el siguiente contenido:

```python
"""
sync_utils.py — Utilidades compartidas entre sync.py y sync_ventas.py.
"""
import sys
import subprocess


def set_priority_low():
    """Establece prioridad baja para no impactar el rendimiento de Windows."""
    if sys.platform == "win32":
        try:
            import win32api, win32process, win32con
            pid = win32api.GetCurrentProcessId()
            handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, True, pid)
            win32process.SetPriorityClass(handle, win32process.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass


def _kill_proc(proc):
    """Mata un proceso forzadamente en Windows."""
    try:
        if proc.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
            )
            proc.wait(timeout=5)
    except Exception:
        pass


def safe_decimal(val) -> float:
    """Convierte un valor (incluyendo formato venezolano '1.500,50') a float."""
    if val is None:
        return 0.0
    s = str(val).strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def exponential_backoff(attempt: int) -> float:
    """Calcula delay de backoff exponencial con techo de 15 segundos."""
    return min(1.5 ** attempt, 15.0)
```

**Verificar**: `python -c "from sync_utils import safe_decimal, set_priority_low, _kill_proc, exponential_backoff; print('OK')"` → `OK`

### Paso 2: Actualizar `sync.py`

Reemplazar las definiciones de `set_priority_low`, `_kill_proc`, `safe_decimal` en `sync.py` por imports:

Agregar después de los imports existentes (antes de `BASE_DIR = ...`):

```python
from sync_utils import safe_decimal, set_priority_low, _kill_proc
```

Eliminar las definiciones locales de esas tres funciones (líneas 22-44 aproximadamente).

**Verificar**: `python -c "import ast; ast.parse(open('sync.py').read()); print('OK')"` → `OK`
**Verificar**: `python -m pytest tests/test_sync.py -v` → todos pasan

### Paso 3: Actualizar `sync_ventas.py`

Agregar después de los imports existentes:

```python
from sync_utils import safe_decimal, set_priority_low, _kill_proc, exponential_backoff
```

Eliminar las definiciones locales de `safe_decimal`, `set_priority_low`, `_kill_proc`, y `_exponential_backoff`.

Donde `sync_ventas.py` usa `_exponential_backoff(attempt)`, cambiar por `exponential_backoff(attempt)` (sin underscore — es parte de la API pública del módulo).

**Verificar**: `python -c "import ast; ast.parse(open('sync_ventas.py').read()); print('OK')"` → `OK`
**Verificar**: `python -m pytest tests/ -v` → todos pasan

### Paso 4: Verificar que no hay otras definiciones duplicadas

```powershell
Select-String -Path *.py -Pattern "^def safe_decimal" | Where-Object { $_.Filename -ne "sync_utils.py" }
Select-String -Path *.py -Pattern "^def set_priority_low" | Where-Object { $_.Filename -ne "sync_utils.py" }
```

Esperado: sin matches fuera de `sync_utils.py`.

## Plan de tests

Crear `tests/test_sync_utils.py`:

```python
from sync_utils import safe_decimal, exponential_backoff

def test_safe_decimal_formato_venezolano():
    assert safe_decimal("1.500,50") == 1500.50

def test_safe_decimal_formato_punto():
    assert safe_decimal("1500.50") == 1500.50

def test_safe_decimal_coma_simple():
    assert safe_decimal("1500,50") == 1500.50

def test_safe_decimal_none():
    assert safe_decimal(None) == 0.0

def test_safe_decimal_string_vacio():
    assert safe_decimal("") == 0.0

def test_safe_decimal_valor_invalido():
    assert safe_decimal("abc") == 0.0

def test_exponential_backoff_techo():
    assert exponential_backoff(100) == 15.0

def test_exponential_backoff_primer_intento():
    assert exponential_backoff(1) == 1.5
```

**Verificar**: `python -m pytest tests/test_sync_utils.py -v` → 8 tests pasan

## Criterios de done

- [ ] `sync_utils.py` existe con las 4 funciones
- [ ] `sync.py` importa desde `sync_utils` y no define `safe_decimal`, `set_priority_low`, `_kill_proc`
- [ ] `sync_ventas.py` importa desde `sync_utils` y no define esas funciones localmente
- [ ] `Select-String -Path *.py -Pattern "^def safe_decimal" | Where-Object { $_.Filename -ne "sync_utils.py" }` → sin matches
- [ ] `python -m pytest tests/ -v` → todos pasan, incluyendo 8 nuevos en `test_sync_utils.py`
- [ ] Solo los archivos de Scope fueron modificados
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- `actualizar_inventario.py` o `extraer_ventas.py` definen sus propias copias de `safe_decimal` → extender el scope del plan para incluirlos
- Los tests de `sync.py` rompen porque mockean `sync.safe_decimal` directamente → actualizar mocks para usar `sync_utils.safe_decimal`

## Notas de mantenimiento

- Futuros extractores o módulos de sync deben importar desde `sync_utils`, nunca copiar las funciones
- `sync_ventas.py` también tiene `to_float()` (alias de safe_decimal) y `to_int()` — si se quiere limpiar más, esas también pueden moverse en una segunda iteración
