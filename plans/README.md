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
