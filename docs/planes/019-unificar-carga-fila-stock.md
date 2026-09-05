# Plan 019: Unificar `cargar_y_fijar` con `cargar_y_fijar_fila` en flujo_stock_real

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — your reviewer
> maintains the index.
>
> **Drift check (run first)**:
> `git diff --stat 2ad838c..HEAD -- hybrid_writeback/flujo_stock_real.py`
> If the file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `2ad838c`, 2026-07-12

## Why this matters

`flujo_stock_real.py` tiene dos funciones casi idénticas de ~55 líneas cada
una: `cargar_y_fijar` (línea 237, flujo de UN producto) y
`cargar_y_fijar_fila` (línea 295, fila N de un lote). El propio docstring de
la versión de lote dice que "fila=0 es idéntico al flujo single". Mantener dos
copias ya costó: la optimización de 2026-07-12 ("clicar solo la primera
fila", commit 2ad838c) tuvo que razonarse dos veces. Unificar deja UNA
coreografía de carga de fila, que es exactamente lo que valida el dueño.

**Contexto crítico**: esto es automatización de input real (mouse/teclado)
sobre HybridLite. Timings (`time.sleep`), coordenadas (`gr.left+196,
gr.top+40`), y el orden de verificación SON comportamiento validado en vivo.
La unificación debe ser una delegación pura, no una reescritura.

## Current state

Archivo: `hybrid_writeback/flujo_stock_real.py` (repo
`C:\Proyect\backend serrucho`, branch `serrucho`).

- `cargar_y_fijar(aj, grid, codigo, target)` — línea 237. Estructura:
  1. `_leer(aj, grid)` y si `d["codigo"]` no coincide con `codigo` →
     `_borrar_items(aj)` + `time.sleep(0.4)` (limpieza de residuo).
  2. clic en celda Código de la fila 0: `ri.click(gr.left + 196, gr.top + 40)`
     precedido de `_focus(...)`.
  3. teclear código LENTO → ENTER → verificación en bucle (6 intentos) de que
     la grilla cargó el código correcto → teclear cantidad → verificación
     pre-posteo (código y conteo) → ENTER, ENTER (postea).
  4. devuelve el dict `datos` de `_leer` con `existencia` preservada.
- `cargar_y_fijar_fila(aj, grid, codigo, target, fila)` — línea 295. La MISMA
  coreografía con tres diferencias:
  1. NO hace la limpieza de residuo (el lote limpia la grilla una única vez).
  2. Solo la fila 0 hace clic/enfoque (cambio de 2ad838c): las filas
     siguientes tipean directo sobre el cursor auto-posicionado.
  3. Lee con `_leer(aj, grid, fila)` y sus mensajes de log/error llevan el
     prefijo de fila: `"Fila %s: %s cargado..."`,
     `"La grilla NO cargó {codigo} en la fila {fila}..."`.
- `_leer(aj, grid, fila=0)` — línea 205: `fila` defaultea a 0, así que
  `_leer(aj, grid)` ≡ `_leer(aj, grid, 0)`.
- Llamadores: `ajustar_stock` (línea ~525) llama `cargar_y_fijar`;
  `_lote_un_documento` (línea ~592) llama `cargar_y_fijar_fila`. Ambos son
  rutas de producción activas: el listener usa `ajustar_stock` para órdenes
  de 1 ítem y el lote para 2+.

Convenciones del repo: español en docstrings/logs, sin type hints, comentarios
que explican el porqué se conservan.

## Commands you will need

| Purpose | Command (desde el worktree) | Expected on success |
|---------|------------------------------|---------------------|
| Compilar | `C:/Python314/python.exe -m py_compile hybrid_writeback/flujo_stock_real.py` | exit 0 |
| Import smoke | `cd hybrid_writeback && C:/Python314/python.exe -c "import flujo_stock_real; print('OK')"` | `OK` |
| Suite | `C:/Python314/python.exe -m pytest -q` (raíz) | 47 passed |

## Scope

**In scope**:
- `hybrid_writeback/flujo_stock_real.py`

**Out of scope** (NO tocar):
- Todo lo demás. En particular `listener_writeback.py` (llama estas
  funciones; sus firmas NO cambian) y `flujo_compra_real.py` (importa
  `_cerrar_ficha_si_abierta` de este módulo).
- Las funciones `ajustar_stock`, `ajustar_stock_lote`, `_lote_un_documento`:
  sus contratos de retorno difieren a propósito y NO se unifican (decisión
  registrada en plans/README.md).

## Git workflow

- Branch: `improve/019-unificar-carga-fila-stock`
- Un commit: `refactor(stock): cargar_y_fijar delega en cargar_y_fijar_fila (fila 0)`
- NO push.

## Steps

### Step 1: Reescribir `cargar_y_fijar` como delegación

Reemplazar el cuerpo de `cargar_y_fijar(aj, grid, codigo, target)` por:

1. El bloque de limpieza de residuo EXACTO que tiene hoy (leer con
   `_leer(aj, grid)`, comparar código normalizado, `_borrar_items(aj)` +
   `time.sleep(0.4)` si hay residuo).
2. `return cargar_y_fijar_fila(aj, grid, codigo, target, fila=0)`.

Actualizar su docstring: sigue describiendo el flujo single y anota que la
coreografía vive en `cargar_y_fijar_fila` (fila 0 = clic inicial; la
grabación original del dueño 2026-07-08 sigue siendo la referencia).

NO tocar el cuerpo de `cargar_y_fijar_fila`.

**Cambio cosmético aceptado y documentado**: los mensajes de log y de error
del flujo single pasan a ser los de la versión de fila (p.ej. "Fila 0: X
cargado…", "La grilla NO cargó X en la fila 0…"). Esos textos llegan a
`backend_resultado` en la app en caso de error; siguen siendo correctos.
Mencionarlo en el mensaje de commit.

**Verify**: `C:/Python314/python.exe -m py_compile hybrid_writeback/flujo_stock_real.py` → exit 0

### Step 2: Verificación integral

**Verify**:
1. `cd hybrid_writeback && C:/Python314/python.exe -c "import flujo_stock_real as f; import inspect; src = inspect.getsource(f.cargar_y_fijar); assert 'cargar_y_fijar_fila' in src and 'ri.click' not in src, src; print('DELEGA OK')"` → `DELEGA OK`
2. `C:/Python314/python.exe -m pytest -q` → 47 passed
3. `git -C . status --porcelain` → solo `flujo_stock_real.py`

## Test plan

No hay tests unitarios de este módulo (pytest ignora `hybrid_writeback/`).
La validación de comportamiento real (preview de un ajuste single, que abre
HybridLite y toma el mouse ~40 s) la hace el REVIEWER después, no el
executor. No ejecutar ningún `flujo_stock_real.py` desde CLI.

## Done criteria

- [ ] py_compile exit 0
- [ ] El assert de delegación imprime `DELEGA OK`
- [ ] `pytest -q` → 47 passed
- [ ] Diff toca únicamente `cargar_y_fijar` (su cuerpo/docstring): `git diff` no muestra hunks en otras funciones
- [ ] Un solo archivo modificado

## STOP conditions

- El drift check muestra cambios post-`2ad838c` en el archivo.
- El cuerpo actual de `cargar_y_fijar` o `cargar_y_fijar_fila` difiere de lo
  descrito en "Current state" en algo más que espacios (p.ej. la fila version
  volvió a clicar todas las filas): reportar, no adaptar.
- Cualquier necesidad de cambiar `cargar_y_fijar_fila`, firmas, o el shape de
  retorno.

## Maintenance notes

- A partir de ahora, cualquier ajuste a la coreografía de carga de fila se
  hace UNA vez en `cargar_y_fijar_fila`.
- Reviewer: correr una validación en vivo en preview (sin commit) de
  `ajustar_stock` single ANTES de aprobar el merge — es la ruta caliente del
  listener para órdenes de 1 ítem.
- Tras mergear: reiniciar el backend (regla de despliegue del repo).
