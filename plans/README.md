# Implementation Plans — Backend El Serrucho

Generado por la skill `improve` el 2026-06-20. SHA base: `cc62d24`.

Ejecutar en el orden de la tabla salvo que las dependencias indiquen otra cosa. Cada ejecutor debe: leer el plan completo antes de empezar, respetar las condiciones STOP, y actualizar su fila al terminar.

---

## Orden de ejecución y estado

| Plan | Título | Priority | Effort | Depende de | Status |
|------|--------|----------|--------|------------|--------|
| [001](001-fix-get-current-rate-key-mismatch.md) | Corregir claves rotas en `get_current_rate()` | P1 | S | — | DONE |
| [002](002-remove-hardcoded-credentials.md) | Eliminar credenciales Supabase hardcodeadas | P1 | S | — | DONE |
| [003](003-fix-ssl-verification-bcv.md) | Habilitar verificación SSL en scraper BCV | P1 | S | — | DONE |
| [004](004-add-auth-to-sync-endpoints.md) | Agregar auth X-API-Key a endpoints de sync | P1 | S | 002 | DONE |
| [005](005-fix-h-drive-check-sync-incremental.md) | Corregir verificación de unidad H: en sync | P2 | S | — | DONE |
| [006](006-extract-sync-utils.md) | Extraer utilidades duplicadas a `sync_utils.py` | P2 | S | — | DONE |
| [007](007-replace-importlib-reload.md) | Reemplazar `importlib.reload()` en Flask | P2 | M | — | DONE |
| [008](008-restrict-cors.md) | Restringir CORS a orígenes conocidos | P3 | S | — | DONE |
| [009](009-add-tests-rates-service.md) | Tests para `rates_service` y cascada de tasas | P1 | M | 001 | DONE |
| [010](010-add-tests-lock-util.md) | Tests para `lock_util` (locks, PIDs, timeouts) | P2 | M | — | DONE |
| [011](011-pin-dependencies.md) | Fijar versiones de dependencias y crear lockfile | P2 | S | — | DONE |
| [012](012-investigate-bug3-bug5-sales.md) | Resolver Bug #3 (total_bruto) y Bug #5 (timestamp) | P2 | M | 001 | DONE |
| [013](013-add-pytest-config.md) | Agregar pytest.ini y baseline de cobertura | P3 | S | — | DONE |
| [014](014-surface-sync-ajustes.md) | Declarar pydbisam en requirements y documentar | P2 | S | 011 | DONE |
| [015](015-add-sales-sync-safeguards.md) | Salvaguardas de calidad en sync de ventas | P2 | S | — | DONE |
| [016](016-add-alert-webhook.md) | Alertas opcionales por webhook ante discrepancias | P3 | M | — | DONE |
| [017](017-independent-rate-refresh.md) | Thread independiente para refrescar tasas c/15 min | P3 | S | 001 | DONE |
| [018](018-extraer-listener-base.md) | Extraer núcleo común de listeners a `listener_base.py` | P1 | M | — | DONE (rama `improve/018-listener-base`, commit db98f2e; revisado y validado --once en vivo 2026-07-12; pendiente de merge) |
| [019](019-unificar-carga-fila-stock.md) | Unificar `cargar_y_fijar` con `cargar_y_fijar_fila` | P2 | S | — | DONE (rama `improve/019-unificar-carga-fila-stock`, commit 6c5f0cf; preview single validado en vivo 2026-07-12; pendiente de merge) |
| [020](020-mover-scripts-diagnostico.md) | Mover scripts de diagnóstico a `diagnostico/` | P2 | S | — | DONE (rama `improve/020-mover-diagnostico`, commit 32abce0; 56 renames puros; pendiente de merge) |
| [021](021-readme-arquitectura-writeback.md) | README de arquitectura de `hybrid_writeback/` | P3 | S | 018, 019, 020 | TODO (despachar tras mergear 018-020) |

Status values: `DONE` | `IN PROGRESS` | `DONE` | `BLOCKED: <razón>` | `REJECTED: <razón>`

---

## Notas de dependencias

- **004** requiere **002** porque agrega una variable al `.env`; si el .env no tiene las credenciales rotadas, desplegar auth primero no tiene sentido.
- **009** requiere **001** porque los tests de `TestGetCurrentRate` verifican el comportamiento corregido.
- **012** requiere **001** porque los tests de cálculo de USD usan la tasa correcta.
- **014** requiere **011** para que `pydbisam` quede en el mismo `requirements.txt` pinado.
- **017** requiere **001** para que la tasa que se guarda sea la real y no 489.55.

---

## Hallazgos considerados y rechazados

- **BUG: `body` no inicializado en `remote_listener.py:76`**: Falso positivo — `body = ""` sí se asigna en el bloque `except`. Rechazado.
- **SEC: URL de Supabase en logs (`remote_listener.py:53`)**: By-design — el project ID de Supabase no es un secreto operacional. Rechazado.
- **SEC: Inyección WMI en `backend_watchdog.py`**: El array `SCRIPTS` está hardcodeado en el fuente; riesgo práctico nulo con el deployment actual. Downgradeado a informativo, no planificado.
- **PERF: Búsqueda lineal en `/api/v1/productos`**: El catálogo de una ferretería raramente supera 10k productos; la búsqueda in-memory es adecuada. Rechazado por ahora.
- **(2026-07-12, ronda write-back) Renombrar `flujo_precio.py`→`hybrid_base.py`** (el nombre no refleja su rol de base compartida): rechazado — alto riesgo (imports en 5 módulos, procesos 24/7, docs/memoria referencian los nombres) por valor puramente estético. Documentado en el README de arquitectura (plan 021) en su lugar.
- **(2026-07-12) Unificar `ajustar_stock` con `ajustar_stock_lote`**: rechazado — contratos de retorno distintos consumidos por el listener y la CLI; unificarlos cambia mensajes/shape en la ruta caliente por ganancia marginal.
- **(2026-07-12) Dedup de `_focus` (flujo_stock_real / flujo_compra_real)**: rechazado por ahora — 12 líneas duplicadas; moverlo a `flujo_precio` toca 3 módulos de coreografía viva. Valor marginal, riesgo desproporcionado.
- **(2026-07-12) Sweep de type hints/docstrings en los flujos**: rechazado — churn masivo en código validado en vivo sin beneficio funcional.

---

## Resumen por categoría

| Categoría | Planes | P1 | P2 | P3 |
|-----------|--------|----|----|-----|
| Bug | 001, 005, 012 | 1 | 2 | 0 |
| Security | 002, 003, 004, 008 | 3 | 0 | 1 |
| Tech-debt | 006, 007 | 0 | 2 | 0 |
| Tests | 009, 010, 013 | 1 | 1 | 1 |
| Deps / DX | 011, 013 | 0 | 1 | 1 |
| Direction | 014, 015, 016, 017 | 0 | 2 | 2 |
| **Total** | **17** | **5** | **8** | **4** |
