# Plan 002: Eliminar credenciales Supabase hardcodeadas del código fuente

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check (ejecutar primero)**:
> `git diff --stat cc62d24..HEAD -- config.py .env.example`
> Si config.py cambió, comparar los excerpts con el código real antes de continuar.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

`config.py` contiene la URL del proyecto Supabase, la key publicable, y el JWT anon completo como valores por defecto hardcodeados. Estos valores están en el historial de git y cualquier persona con acceso al repositorio puede usarlos para leer y escribir en la base de datos de producción (la política RLS de `productos` permite escritura con anon, según CLAUDE.md).

**Adicionalmente**, los scripts en `scratch/` contienen copias independientes del JWT. El token tiene fecha de expiración en 2093, por lo que la exposición es persistente sin rotación.

La fix tiene dos partes: (A) eliminar los valores hardcodeados del código (reemplazar con `""` y hacer que la app falle explícitamente si no hay .env), y (B) rotar las credenciales en Supabase Dashboard (obligatorio — un secreto en git está quemado aunque se borre del código).

## Estado actual

```python
# config.py:34-46
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://YOUR-PROJECT-REF.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_91qCibM40mWzij-bW5bQyA_xkGA3fsj")

SUPABASE_REST_URL = os.environ.get("SUPABASE_REST_URL", "https://YOUR-PROJECT-REF.supabase.co")
SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "REDACTED-JWT-PAYLOAD."
    "REDACTED-JWT-SIGNATURE"
)
```

Scripts con credenciales duplicadas (solo la ubicación — no reproducir valores):
- `scratch/debug_401.py:5-6` — URL y JWT hardcodeados
- `scratch/analyze_sync_discrepancy.py:11-12` — idem
- `scratch/test_widget_calls.py:5-6` — idem

Archivo `.env` (si existe): contiene las credenciales reales y ya no es rastreado por git (verificar `.gitignore`).

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Ejecutar tests | `python -m pytest tests/ -v` | Todos pasan |
| Verificar que .env existe | `Test-Path ".env"` (PowerShell) | True |
| Verificar que config carga | `python -c "from config import SUPABASE_REST_URL; print(bool(SUPABASE_REST_URL))"` | True |
| Verificar no hay JWT en config.py | `Select-String -Path config.py -Pattern "eyJ"` | Sin matches |

## Scope

**En scope**:
- `config.py` — eliminar valores hardcodeados, usar `""` como default con validación
- `scratch/debug_401.py`, `scratch/analyze_sync_discrepancy.py`, `scratch/test_widget_calls.py` — reemplazar hardcoded con import de config
- `.env.example` — verificar/crear con las variables necesarias (sin valores reales)
- `.gitignore` — verificar que `.env` está listado

**Fuera de scope**:
- El resto del código que ya usa `from config import ...` (ya leen de las variables correctamente)
- `widget.pyw` — tiene su propio hardcode que se cubre en plan 012
- Rotación de credenciales en Supabase Dashboard (debe hacer el operador humano — ver Paso 0)

## Git workflow

- Branch: `advisor/002-remove-hardcoded-credentials`
- Commit: `security: eliminar credenciales Supabase hardcodeadas de config.py y scratch/`

## Pasos

### Paso 0 (MANUAL — hacer ANTES de cualquier cambio de código): Rotar las credenciales en Supabase

1. Ir a Supabase Dashboard → Proyecto → Settings → API
2. Rotar la `anon public key` (genera una nueva)
3. Copiar el nuevo valor al `.env` local
4. Verificar que la app sigue funcionando con el nuevo token: `python test_conexion.py`

**STOP si este paso falla** — no continuar con el código hasta tener credenciales nuevas funcionando.

### Paso 1: Asegurar que `.env` existe y está en `.gitignore`

```powershell
# Verificar .gitignore
Select-String -Path .gitignore -Pattern "^\.env$"
```

Si `.env` no está en `.gitignore`, agregarlo:
```
.env
```

Verificar que el `.env` actual contiene todas las variables necesarias:
```
SUPABASE_URL=https://...supabase.co
SUPABASE_KEY=sb_publishable_...
SUPABASE_REST_URL=https://...supabase.co
SUPABASE_ANON_KEY=eyJ...
```

**Verificar**: `python -c "from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY; assert SUPABASE_REST_URL and SUPABASE_ANON_KEY; print('OK')"` → imprime `OK`

### Paso 2: Reemplazar valores hardcodeados en `config.py`

Reemplazar las líneas 34-46 de `config.py`:

```python
# ─── Supabase (cliente Python supabase-py) ───────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ─── Supabase REST API (fallback sin supabase-py) ────────────────────────────
SUPABASE_REST_URL = os.environ.get("SUPABASE_REST_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# Validar que las credenciales críticas están disponibles
if not SUPABASE_REST_URL or not SUPABASE_ANON_KEY:
    import sys
    print("[CONFIG] ERROR: SUPABASE_REST_URL y SUPABASE_ANON_KEY son requeridos.")
    print("[CONFIG] Crear/verificar el archivo .env con las credenciales del proyecto.")
    # No sys.exit() aquí — permitir que módulos individuales fallen con su propio mensaje
```

**Verificar**: `python -c "from config import SUPABASE_REST_URL; print(bool(SUPABASE_REST_URL))"` → `True` (asumiendo que .env está correctamente configurado)

### Paso 3: Limpiar scripts en `scratch/`

Para cada script en `scratch/` que tenga credenciales hardcodeadas, reemplazar las líneas con:

```python
# Importar desde config (que lee de .env)
from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY
```

Borrar las líneas que tenían `SUPABASE_URL = "https://..."` y `SUPABASE_ANON_KEY = "eyJ..."`.

**Verificar**: `Select-String -Path scratch/ -Pattern "eyJ" -Recurse` → sin matches

### Paso 4: Crear/actualizar `.env.example`

Asegurar que existe `C:\Proyect\backend serrucho\.env.example` con este contenido (sin valores reales):

```
# Copiar este archivo a .env y completar con los valores reales del Dashboard de Supabase
SUPABASE_URL=https://TU-PROYECTO.supabase.co
SUPABASE_KEY=sb_publishable_TU_KEY_AQUI
SUPABASE_REST_URL=https://TU-PROYECTO.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.TU_ANON_JWT_AQUI
TASA_BS=100.0
PORT=5000
```

**Verificar**: `Test-Path ".env.example"` → True; `Select-String -Path .env.example -Pattern "eyJ.*\."` → sin matches con JWT reales

## Plan de tests

Actualizar `tests/test_config.py` para que no dependa de valores hardcodeados:

```python
def test_config_loads_from_env(monkeypatch):
    """Config carga valores desde variables de entorno."""
    monkeypatch.setenv("SUPABASE_REST_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-key-123")
    import importlib, config
    importlib.reload(config)
    assert config.SUPABASE_REST_URL == "https://test.supabase.co"
    assert config.SUPABASE_ANON_KEY == "test-key-123"

def test_config_empty_when_no_env(monkeypatch):
    """Config devuelve string vacío si no hay env var ni .env."""
    monkeypatch.delenv("SUPABASE_REST_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    # Renombrar temporalmente .env si existe para simular ausencia
    # (usar tmp_path fixture del plan 013 cuando esté disponible)
```

**Verificar**: `python -m pytest tests/test_config.py -v` → pasan

## Criterios de done

- [ ] `Select-String -Path config.py -Pattern "eyJ"` → sin matches
- [ ] `Select-String -Path config.py -Pattern "sb_publishable"` → sin matches
- [ ] `Select-String -Path scratch/ -Pattern "eyJ" -Recurse` → sin matches
- [ ] `.env` existe y contiene las nuevas credenciales rotadas
- [ ] `.env` está en `.gitignore`
- [ ] `.env.example` existe sin valores reales
- [ ] `python -c "from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY; assert SUPABASE_REST_URL"` → sin error
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo los archivos listados en Scope fueron modificados (`git diff --name-only`)
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- El Paso 0 (rotación) falla — no continuar sin credenciales nuevas funcionando
- `python test_conexion.py` falla después de actualizar `.env` con nuevas credenciales
- No se puede encontrar el archivo `.env` existente — verificar con el operador antes de crear uno nuevo

## Notas de mantenimiento

- Las credenciales de Supabase deben estar **únicamente** en `.env` (nunca en código fuente)
- Si se genera un nuevo ambiente (dev/staging), crear un proyecto Supabase separado con sus propias keys
- El warning en `config.py` (sin `sys.exit()`) es intencional: permite que módulos individuales fallen con mensajes específicos en vez de un crash general al importar
