# Plan 021: README de arquitectura del paquete `hybrid_writeback/`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — your reviewer
> maintains the index.
>
> **Drift check (run first)**: este plan depende de 018, 019 y 020 ya
> mergeados. Verificá: `ls hybrid_writeback/listener_base.py` existe y
> `ls hybrid_writeback/diagnostico/` existe. Si no, STOP.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/018, plans/019, plans/020
- **Category**: docs
- **Planned at**: commit `2ad838c`, 2026-07-12

## Why this matters

El paquete ya tiene un `README.md` orientado al write-back histórico, pero
tras los planes 018–020 la estructura cambió (base de listeners, paquete
limpio, diagnóstico separado). Quien toque esto en 6 meses (humano o agente)
necesita el mapa: qué módulo hace qué, qué invariantes de seguridad NUNCA se
rompen, y dónde está el registro de coreografías validadas.

## Current state

- `hybrid_writeback/README.md` existe (documenta la fase de descubrimiento
  del write-back). NO se borra: se le agrega/actualiza una sección de
  arquitectura al inicio, preservando el contenido histórico debajo.
- Módulos de producción tras 018–020 (rol de cada uno):
  - `realinput.py` — motor de input real (SendInput): clic/tecla de hardware.
  - `flujo_precio.py` — base compartida de ventanas: `_find_hwnd`, filtro de
    PID objetivo (`set_target_pid`), constantes de clase de ventana.
  - `hybrid_price_writer.py` — lectura DBISAM (`_db_precio_usd`,
    `_db_costo_usd`) y localización de campos/diálogos.
  - `read_db_precio.py` / `read_db_existencia.py` — lectura DBISAM de
    precio/existencia para verificación.
  - `flujo_precio_real.py` — coreografía de precio/costo en la Ficha.
  - `flujo_stock_real.py` — coreografía de ajustes de stock (single y lote).
  - `flujo_compra_real.py` — coreografía de compras + alta de producto nuevo.
  - `abrir_hybrid.py` — instancia AISLADA de HybridLite: launch, login,
    `cerrar_aislada()` (solo mata el PID propio).
  - `safety_control.py` — banner topmost, F12 aborto, mutex del mouse
    (`Local\SerruchoBotMouseLock`) que serializa los dos listeners.
  - `listener_base.py` — núcleo común de listeners (config, logging, guards,
    REST, bucle).
  - `listener_writeback.py` / `listener_compras.py` — pipelines 24/7
    (ordenes_cambio_items / compras_app), lanzados por `backend_watchdog.py`.
  - `grabar_flujo.py` — grabadora de coreografías (sesiones con el dueño).
  - `diagnostico/` — scripts desechables (ver su README).

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Nada que compilar | — | solo se edita un .md |

## Scope

**In scope**: `hybrid_writeback/README.md` (editar: sección nueva al inicio).
**Out of scope**: todo archivo `.py`; el README de `diagnostico/`.

## Git workflow

- Branch: `improve/021-readme-arquitectura`
- Un commit: `docs(writeback): mapa de arquitectura e invariantes del paquete`
- NO push.

## Steps

### Step 1: Agregar la sección "Arquitectura del paquete" al inicio del README

Después del título principal existente, insertar una sección con:

1. **Mapa de módulos** — la tabla de "Current state" de este plan (módulo → rol).
2. **Flujo de datos** — 4 líneas: app (Supabase `ordenes_cambio_items` /
   `compras_app` con `backend_status`) → listener (poll cada 8 s, SERVICE_KEY)
   → coreografía de input real sobre una instancia AISLADA de HybridLite →
   verificación contra la DBISAM → estado final en Supabase → chip en la app.
3. **Invariantes de seguridad (NUNCA romper)** — lista literal:
   - Nunca cerrar la ventana de HybridLite del empleado; solo la instancia
     aislada propia (`abrir_hybrid.cerrar_aislada()`, por PID verificado).
   - Nunca UPDATE crudo a la DBISAM ni parchear los `.DAT` (solo lectura).
   - Todo-o-nada pre-Totalizar: cualquier fallo cancela el documento entero.
   - Los timings, coordenadas y el orden de manejo de alertas de las
     coreografías son COMPORTAMIENTO validado en vivo: no se "limpian".
   - La alerta "producto llegó al mínimo" (TFConfirmacion) se responde `&Ok`
     y se continúa; es tardía/asíncrona en compras.
   - Etapas ambiguas (post-commit) NO son reintentables: riesgo de
     aplicación doble (ver ETAPAS_REINTENTABLES en cada listener).
   - Tras cambiar código: reiniciar los procesos (`start_backend.vbs`) — un
     proceso stale aplicando código viejo ya causó 2 incidentes.
4. **Cómo probar sin escribir** — `--once` sin `HYBRID_WRITE_ENABLED` es
   preview; los flujos aceptan `commit=False`; advertir que un preview
   igualmente toma el mouse si hay pendientes.

Tono/idioma: español, seco y técnico, consistente con el README existente.
No inventar detalles: todo lo listado arriba está verificado en el código.

**Verify**: `grep -c "Invariantes" hybrid_writeback/README.md` → ≥1

## Test plan

N/A (documentación). Gate: el grep del Step 1.

## Done criteria

- [ ] La sección nueva existe al inicio del README con las 4 subsecciones
- [ ] El contenido histórico del README sigue presente (no se borró nada)
- [ ] `git status --porcelain` → solo `hybrid_writeback/README.md`

## STOP conditions

- `listener_base.py` o `diagnostico/` no existen (dependencias sin mergear).
- El README actual contradice algo de este plan (p.ej. ya tiene un mapa de
  arquitectura): reportar en vez de duplicar.

## Maintenance notes

- Este mapa se actualiza cuando se agregue un módulo de producción o un
  invariante nuevo (p.ej. un tercer listener).
