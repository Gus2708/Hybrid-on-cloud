# Plan 018: Extraer el núcleo común de los listeners a `listener_base.py`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — your reviewer
> maintains the index.
>
> **Drift check (run first)**:
> `git diff --stat 2ad838c..HEAD -- hybrid_writeback/listener_writeback.py hybrid_writeback/listener_compras.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `2ad838c`, 2026-07-12

## Why this matters

`listener_writeback.py` (749 líneas) y `listener_compras.py` (473 líneas) son
procesos hermanos que nacieron por copy-paste: comparten ~350 líneas idénticas
o casi idénticas (carga de config, logging, guard de unidad H:, ventana
horaria, cliente REST, bucle principal). El copy-paste ya produjo una
divergencia real: el toggle on/off del widget (`writeback_settings.json`,
leído por `check_hybrid_write_enabled()`) **solo lo respeta
listener_writeback** — listener_compras lee la env var cruda, así que apagar
el write-back desde el widget NO apaga las compras. Extraer la base común
elimina la duplicación y corrige esa divergencia.

**Contexto crítico de dominio**: estos listeners orquestan automatización de
input REAL (mouse/teclado) sobre el POS HybridLite. El código de coreografía
vive en `flujo_stock_real.py` / `flujo_precio_real.py` /
`flujo_compra_real.py` y está **fuera de alcance**. Este plan solo toca la
capa de orquestación (polling de Supabase, política de reintentos, bucle).

## Current state

Archivos (todos en `hybrid_writeback/`, repo `C:\Proyect\backend serrucho`,
branch `serrucho`):

- `listener_writeback.py` — sondea `ordenes_cambio_items` en Supabase y aplica
  ajustes de stock/precio/costo en HybridLite. Corre 24/7 bajo
  `backend_watchdog.py` como `pythonw listener_writeback.py`.
- `listener_compras.py` — hermano: sondea `compras_app` y registra compras.
  También corre bajo el watchdog.

### Funciones IDÉNTICAS entre ambos (verificado con diff el 2026-07-12)

- `_h_disponible()` — guard de disponibilidad de la unidad H:.
- `_parse_ventana(valor)` — parsea `"HH:MM-HH:MM"`.
- `_dentro_de_ventana(ventana, ahora=None)` — chequeo de ventana horaria.
- `_rest(method, path, body=None, extra_headers=None)` — cliente REST urllib
  contra Supabase (usa los globals `SUPABASE_REST_URL` y `HEADERS` del módulo).

### Bloques casi idénticos

- **Carga de config** (writeback líneas 104–113, compras 73–82): `sys.path.insert`
  al dir padre + `import config` + extracción de `SUPABASE_REST_URL`,
  `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`; `sys.exit(1)` si falla.
- **API_KEY/HEADERS + warning** (writeback 169–181, compras 131–142): idéntico
  salvo el nombre de la tabla en el texto del warning.
- **Logging** (writeback 143–157, compras 93–110): `logging.basicConfig(...,
  force=True, handlers=[StreamHandler, FileHandler(<archivo>)])`. Difieren solo
  en el archivo (`writeback.log` vs `compras.log`) y el nombre del logger
  (`"writeback"` vs `"compras"`). El comentario explica por qué `force=True`
  es obligatorio (los flujos importados ya llamaron basicConfig); ese
  requisito DEBE preservarse: el basicConfig con force debe ejecutarse
  DESPUÉS de importar los módulos de flujo.
- **Parse de `HYBRID_WRITE_WINDOW`** (writeback 226–238, compras 190–202):
  mismo bloque que setea `_HYBRID_WRITE_WINDOW_RAW`, `HYBRID_WRITE_WINDOW`,
  `HYBRID_WRITE_WINDOW_ERROR`.
- **`loop(once=False)`** (writeback 669–745, compras 406–470): estructuralmente
  idéntico. Difiere en: (a) cómo refresca `HYBRID_WRITE_ENABLED`
  (writeback llama `check_hybrid_write_enabled()`, compras lee la env var);
  (b) qué callable de pendientes/proceso invoca; (c) la palabra "items" vs
  "compras" en 3 mensajes de log. El log de arranque
  `"codigo listener del <mtime>"` usa `os.path.getmtime(__file__)` — en la
  versión extraída debe seguir reportando el mtime del ARCHIVO DEL LISTENER,
  no del módulo base (recibirlo como parámetro).

### Divergencia a corregir (cambio de comportamiento DELIBERADO y único)

`check_hybrid_write_enabled()` (writeback líneas 126–141): lee
`writeback_settings.json` en la raíz del backend (toggle del widget de
escritorio) con fallback a la env var `HYBRID_WRITE_ENABLED`. **Tras este plan,
AMBOS listeners deben usar esta función** — es decir, listener_compras pasa a
respetar el toggle del widget. Este es el ÚNICO cambio de comportamiento
permitido (más la unificación cosmética de textos de log con la palabra
"pendientes"). Todo lo demás debe quedar byte-a-byte equivalente en efecto.

### Lo que queda POR LISTENER (no compartir)

- `TABLE` / `TABLE_CAB` / `TABLE_ITEMS`, `ETAPAS_REINTENTABLES` (¡difieren y
  su contenido es política de seguridad — copiar textual!).
- `get_pendientes()` / `get_compras_pendientes()`, `get_items()`,
  `update_item()` / `update_compra()`, `recuperar_huerfanos()` (tablas y
  campos distintos), `_politica_resultado()` (textos y etapas distintos),
  `_tiene_*`, `_fase_*`, `procesar_pendientes()`, `_procesar_pendientes_impl()`,
  `_texto_item()`, `procesar_compra()`, `_LOCK_FALLIDO`,
  `_AVISO_SIN_SAFETY_CONTROL`, `_AVISO_SIN_COSTO_DB`, el `try: from
  safety_control import control_seguro`, y el bloque `__main__`.

### Convenciones del repo

- Español en docstrings/comentarios/logs; funciones module-level con guiones
  de sección `# ─── Título ───`. Sin type hints (no introducirlos).
- Los comentarios largos que explican decisiones (p.ej. por qué `force=True`,
  la lección F11 del proceso stale) NO se descartan: se mueven junto al código
  al que pertenecen.

## Commands you will need

| Purpose | Command (desde el worktree) | Expected on success |
|---------|------------------------------|---------------------|
| Compilar | `C:/Python314/python.exe -m py_compile hybrid_writeback/listener_base.py hybrid_writeback/listener_writeback.py hybrid_writeback/listener_compras.py` | exit 0, sin output |
| Import smoke | `cd hybrid_writeback && C:/Python314/python.exe -c "import listener_writeback, listener_compras, listener_base; print('OK')"` | imprime `OK` (puede emitir el warning de pywinauto 32/64-bit — es cosmético) |
| Suite | `C:/Python314/python.exe -m pytest -q` (desde la raíz del repo) | 47 passed |

## Scope

**In scope** (los únicos archivos a modificar/crear):
- `hybrid_writeback/listener_base.py` (crear)
- `hybrid_writeback/listener_writeback.py`
- `hybrid_writeback/listener_compras.py`

**Out of scope** (NO tocar aunque parezcan relacionados):
- `hybrid_writeback/flujo_*.py`, `abrir_hybrid.py`, `safety_control.py`,
  `realinput.py`, `hybrid_price_writer.py`, `read_db_*.py` — coreografía de
  input real validada en vivo; cualquier cambio ahí es comportamiento.
- `backend_watchdog.py` — lanza los listeners por nombre de archivo; los
  nombres NO cambian.
- `config.py`, `.env` — nunca reproducir valores de credenciales en ningún
  archivo nuevo ni en el reporte.

## Git workflow

- Branch: `improve/018-listener-base` (creado en el worktree; ver instrucciones del dispatcher).
- Un commit al final: `refactor(listeners): extraer nucleo comun a listener_base.py`
  (estilo del repo: conventional commits en español, cuerpo explicando el qué y el porqué).
- NO push.

## Steps

### Step 1: Crear `hybrid_writeback/listener_base.py`

Módulo nuevo con (en este orden):

1. Docstring de módulo en español explicando: "Base común de
   listener_writeback y listener_compras: config, logging, guards (H:,
   ventana horaria, toggle del widget), cliente REST y bucle principal. La
   lógica de dominio (qué se sondea y cómo se aplica) vive en cada listener."
2. El bloque de carga de config (copiar de `listener_writeback.py:104-113`,
   incluye el `sys.path.insert` al dir padre) que expone
   `SUPABASE_REST_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` como
   globals del módulo base.
3. `API_KEY = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY` y `HEADERS` (copiar
   de writeback:169/175-181). El warning de service-key faltante NO se emite
   en import del base (todavía no hay logging): guardar el texto en una
   constante `AVISO_SIN_SERVICE_KEY = (...)` genérica ("...NO puede ver las
   tablas de otros usuarios...") o `None` si la key está; cada listener lo
   loguea tras configurar logging.
4. `def setup_logging(nombre_logger, archivo_log):` — hace el
   `logging.basicConfig(..., force=True, handlers=[StreamHandler,
   FileHandler(<dir de hybrid_writeback>/archivo_log, encoding="utf-8")])`
   exactamente como writeback:148-157, y devuelve
   `logging.getLogger(nombre_logger)`. Conservar el comentario que explica
   `force=True`. Documentar en el docstring: "llamar DESPUÉS de importar los
   módulos de flujo".
5. `check_hybrid_write_enabled()` — mover textual de writeback:124-141
   (incluye el global `_last_known_enabled` y la ruta a
   `writeback_settings.json` en el dir padre).
6. `_h_disponible()`, `_parse_ventana()`, `_dentro_de_ventana()` — mover
   textuales (son idénticas en ambos listeners).
7. El bloque de parse de `HYBRID_WRITE_WINDOW` (writeback:226-238) →
   ejecutado en import del base; expone `HYBRID_WRITE_WINDOW`,
   `HYBRID_WRITE_WINDOW_ERROR`, `HYBRID_WRITE_WINDOW_RAW` (renombrar el
   `_HYBRID_WRITE_WINDOW_RAW` privado a público para que los listeners lo
   usen en mensajes).
8. `def rest(method, path, body=None, extra_headers=None):` — el `_rest`
   textual de writeback:240-250, usando los globals del base.
9. `def correr_loop(log, listener_file, nombre, get_pendientes,
   procesar_pendientes, recuperar_huerfanos, once=False, sujeto="pendientes"):`
   — el `loop()` de writeback:669-745 generalizado:
   - `HYBRID_WRITE_ENABLED` se refresca SIEMPRE con
     `check_hybrid_write_enabled()` (el cambio deliberado) y se DEVUELVE al
     llamador por pasada… no: los listeners lo consumen dentro de sus
     callbacks. Resolver así: `correr_loop` pasa el valor actual de enabled a
     `procesar_pendientes(items, enabled)` — cada listener adapta su firma
     interna (hoy leen el global propio `HYBRID_WRITE_ENABLED`; pasar a usar
     el parámetro `enabled` en TODOS los puntos donde hoy leen ese global:
     writeback lo usa en `_fase_stock_orden`, `_fase_precio_costo_item`,
     `_procesar_pendientes_impl`; compras en `procesar_compra`). Alternativa
     más simple y aceptable: los listeners llaman
     `listener_base.check_hybrid_write_enabled()` directamente donde hoy leen
     el global. Elegir UNA y aplicarla consistentemente.
   - El log de arranque usa `os.path.getmtime(listener_file)` (parámetro),
     conservando el comentario F11.
   - Los textos con "items"/"compras" usan el parámetro `sujeto`.
   - Estructura, orden de guards (H: → ventana inválida → fuera de ventana),
     anti-spam de `ultimo_motivo_skip`, `POLL_INTERVAL=8` y el manejo de
     `once` se copian EXACTOS de writeback:700-745.

**Verify**: `C:/Python314/python.exe -m py_compile hybrid_writeback/listener_base.py` → exit 0

### Step 2: Reescribir `listener_writeback.py` sobre la base

- Eliminar de listener_writeback todo lo movido al base; importar
  `import listener_base as lb` y reemplazar los usos:
  `_rest(...)` → `lb.rest(...)`, `_h_disponible` → (ya no se llama aquí; vive
  en el loop del base), `check_hybrid_write_enabled` → `lb.check_...`, el
  logging → `log = lb.setup_logging("writeback", "writeback.log")` (después
  de los imports de flujo), el warning →
  `if lb.AVISO_SIN_SERVICE_KEY: log.warning(lb.AVISO_SIN_SERVICE_KEY)`.
- Conservar en el archivo: TABLE, POLL_INTERVAL si algún código local lo usa
  (el del bucle vive en el base), MAX_INTENTOS, ETAPAS_REINTENTABLES (con su
  comentario completo), get_pendientes, update_item, recuperar_huerfanos,
  _tiene_*, _politica_resultado, _aplicar_resultado_final, _LOCK_FALLIDO,
  _fase_stock_orden, _fase_precio_costo_item, procesar_pendientes,
  _texto_item, _procesar_pendientes_impl, y el `__main__` que ahora llama
  `lb.correr_loop(log, __file__, "listener_writeback", get_pendientes,
  procesar_pendientes, recuperar_huerfanos, once=..., sujeto="items")`.
- El módulo NO debe redefinir `HYBRID_WRITE_ENABLED` como global de módulo:
  donde se leía, usar la opción elegida en Step 1.9.

**Verify**: `cd hybrid_writeback && C:/Python314/python.exe -c "import listener_writeback; print('OK')"` → `OK`

### Step 3: Reescribir `listener_compras.py` sobre la base

Igual que Step 2 con lo propio de compras (TABLE_CAB, TABLE_ITEMS,
ETAPAS_REINTENTABLES con su comentario completo, get_compras_pendientes,
get_items, update_compra, recuperar_huerfanos, _politica_resultado,
procesar_compra, procesar_pendientes, `sujeto="compras"`). El
`HYBRID_WRITE_ENABLED` de compras pasa a venir de
`lb.check_hybrid_write_enabled()` — el cambio deliberado de este plan.

**Verify**: `cd hybrid_writeback && C:/Python314/python.exe -c "import listener_compras; print('OK')"` → `OK`

### Step 4: Verificación integral

**Verify**:
1. `C:/Python314/python.exe -m py_compile hybrid_writeback/listener_base.py hybrid_writeback/listener_writeback.py hybrid_writeback/listener_compras.py` → exit 0
2. `C:/Python314/python.exe -m pytest -q` (raíz del repo) → 47 passed
3. Conteo de líneas: `wc -l hybrid_writeback/listener_writeback.py hybrid_writeback/listener_compras.py hybrid_writeback/listener_base.py` → la suma debe ser claramente menor que 1222 (las ~350 líneas duplicadas aparecen una sola vez).
4. `grep -n "def _rest\|def _h_disponible\|def _parse_ventana\|def _dentro_de_ventana\|def check_hybrid_write_enabled" hybrid_writeback/listener_writeback.py hybrid_writeback/listener_compras.py` → sin matches (todo vive en el base).

## Test plan

No hay tests existentes para los listeners (pytest ignora `hybrid_writeback/`
por configuración; no crear tests ahí). La verificación es la de arriba:
compilación, import smoke, suite intacta, y greps de dedup. NO ejecutar
`listener_*.py --once` (si hubiera pendientes reales en Supabase tomaría el
mouse de la máquina); el reviewer hace esa validación en vivo.

## Done criteria

- [ ] py_compile de los 3 archivos exit 0
- [ ] `import listener_writeback` e `import listener_compras` imprimen OK
- [ ] `pytest -q` → 47 passed
- [ ] grep del Done 4 sin matches
- [ ] `git -C <worktree> status --porcelain` solo muestra los 3 archivos in scope
- [ ] `git log -1` en el worktree muestra el commit con el mensaje acordado

## STOP conditions

Stop and report back (do not improvise) if:

- El drift check muestra cambios en los listeners posteriores a `2ad838c`.
- Los excerpts de "Current state" no coinciden con el código vivo.
- Descubrís que algún callable "idéntico" difiere entre ambos listeners más
  allá de lo documentado aquí (sería una divergencia de comportamiento no
  mapeada: reportarla, no unificarla por tu cuenta).
- Necesitás tocar un archivo fuera de scope.
- La verificación de un step falla dos veces.

## Maintenance notes

- Cualquier listener futuro (tercer pipeline) debe montarse sobre
  `listener_base.correr_loop` en vez de copiar.
- Revisor: verificar especialmente que (1) el orden import-flujos →
  setup_logging(force=True) se preservó en ambos listeners; (2) el mtime del
  log de arranque es el del listener, no el del base; (3) compras ahora
  respeta `writeback_settings.json` (cambio deliberado, avisar al operador);
  (4) ETAPAS_REINTENTABLES quedaron byte-idénticas a las originales.
- Tras mergear: REINICIAR el backend (`start_backend.vbs`) — regla de
  despliegue del repo (los procesos viejos quedan con código stale).
