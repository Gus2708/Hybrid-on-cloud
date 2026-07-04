# Plan 014: Declarar pydbisam en requirements.txt y documentar sync_ajustes

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- sync_ajustes.py requirements.txt sync.py`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

`sync_ajustes.py` (408 líneas) implementa la sincronización de ajustes de inventario y compras locales leyendo directamente los archivos DBISAM (`.DAT`) de HybridLite con `pydbisam`. Esta funcionalidad:

1. **No está declarada en `requirements.txt`** — `pydbisam` es una dependencia no listada. Una instalación limpia no la instalaría y el módulo fallaría silenciosamente (capturado por el `except Exception as e` en `sync.py:244`).
2. **No está documentada** en README ni ARCHITECTURE.md — el equipo (y herramientas de IA) no saben que existe esta capacidad.
3. **Se invoca como fallback silencioso** en `sync.py:243-247` sin log claro de éxito/fallo.

Este plan hace que la integración sea explícita y visible.

## Estado actual

```python
# sync.py:243-247 — invocación silenciosa de sync_ajustes
try:
    from sync_ajustes import sync_movimientos_locales
    sync_movimientos_locales(force=force)
except Exception as e:
    print(f"[SYNC] Error importando/ejecutando sincronización de ajustes: {e}")
```

```
# requirements.txt — pydbisam NO está listado
Flask>=2.3.0
requests
python-dotenv
...
```

```python
# sync_ajustes.py:1-14 (inicio del archivo)
import os
import re
import json
import struct
import urllib.request
# ... no importa pydbisam al nivel de módulo; lo importa dentro de funciones
```

Convención de la documentación del proyecto: `CLAUDE.md` menciona que `pydbisam 1.2.1` es una dependencia clave pero no está en `requirements.txt`.

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Verificar instalación de pydbisam | `python -c "import pydbisam; print(pydbisam.__version__)"` | `1.2.1` o similar |
| Tests | `python -m pytest tests/ -v` | Todos pasan |
| Verificar sync_ajustes importa | `python -c "from sync_ajustes import sync_movimientos_locales; print('OK')"` | OK |

## Scope

**En scope**:
- `requirements.txt` — agregar `pydbisam==1.2.1` (o la versión instalada)
- `sync.py` — mejorar el log en el bloque try/except de sync_ajustes para distinguir "no instalado" de "falló"

**Fuera de scope**:
- `sync_ajustes.py` — no modificar la lógica interna (alcance del plan 006 o futuros planes)
- README — una línea sería suficiente pero no es el foco de este plan

## Git workflow

- Branch: `advisor/014-surface-sync-ajustes`
- Commit: `chore: declarar pydbisam en requirements.txt y mejorar logging de sync_ajustes`

## Pasos

### Paso 1: Verificar la versión instalada de pydbisam

```powershell
python -c "import pydbisam; print(getattr(pydbisam, '__version__', 'desconocida'))"
```

Si no está instalado → condición de STOP.

### Paso 2: Agregar pydbisam a `requirements.txt`

Agregar la línea:
```
pydbisam==1.2.1
```
(o la versión que devolvió el Paso 1)

**Verificar**: `python -m pip install -r requirements.txt --dry-run` → sin errores

### Paso 3: Mejorar el log en `sync.py:243-247`

Reemplazar:

```python
try:
    from sync_ajustes import sync_movimientos_locales
    sync_movimientos_locales(force=force)
except Exception as e:
    print(f"[SYNC] Error importando/ejecutando sincronización de ajustes: {e}")
```

Por:

```python
try:
    from sync_ajustes import sync_movimientos_locales
    sync_movimientos_locales(force=force)
    print("[SYNC] Sincronización de ajustes/compras completada.")
except ImportError as e:
    print(f"[SYNC] sync_ajustes no disponible (pydbisam instalado?): {e}")
except Exception as e:
    print(f"[SYNC] Error en sincronización de ajustes: {e}")
```

**Verificar**: `python -c "import ast; ast.parse(open('sync.py').read()); print('OK')"` → OK
**Verificar**: `python -m pytest tests/ -v` → todos pasan

## Criterios de done

- [ ] `requirements.txt` contiene `pydbisam==X.X.X`
- [ ] `python -m pip install -r requirements.txt --dry-run` → sin errores
- [ ] `sync.py` distingue `ImportError` de otras excepciones en el bloque de sync_ajustes
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo los archivos de Scope fueron modificados
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- `pydbisam` no está instalado → instalar con `pip install pydbisam==1.2.1`, verificar que `sync_ajustes.py` funciona, luego continuar con el plan

## Notas de mantenimiento

- `pydbisam` es un lector de archivos DBISAM propietario. Si la versión de HybridLite cambia el formato de los `.DAT`, puede requerirse actualizar `pydbisam`
- La integración de sync_ajustes es best-effort: si falla, el sync de inventario principal ya se completó; los ajustes locales se sincronizan en el siguiente ciclo
