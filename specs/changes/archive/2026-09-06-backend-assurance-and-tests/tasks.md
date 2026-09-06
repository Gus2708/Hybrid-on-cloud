# Tasks: backend-assurance-and-tests

## Review Workload Forecast
Estimated changed lines: 400-600
Estimated product files: 10-14
Target budget: 800 lines, 15 files
Hard limit: 1000 lines, 25 files
Budget risk: Low
Independent slices possible: No
Shared production files across slices: No
Forecast basis: proposal, specs, design and code exploration

## Delivery Plan
Strategy: single-pr
Model: whole
PR mode: draft
PR creation point: final verify only
Current delivery unit: whole

### Whole Delivery
Planned branch/base: sdd/backend-assurance-and-tests -> main
Scope: Configuración de Ruff, modelos Pydantic de validación de datos, arnés de prueba para writeback y suites de tests unitarios de sincronizadores.

## Slice: whole — Cobertura y Aseguramiento del Backend

### Phase 1: Configuración de Calidad y Entorno
- [x] 1.1 Configurar Ruff y pytest-cov en pyproject.toml y requirements-dev.txt
  - [x] 1.1.a Safety Net: ejecutar python -m pytest y verificar que los 140 tests actuales pasan
  - [x] 1.1.b RED: invocar ruff check antes de pyproject.toml verificando ausencia de configuración
  - [x] 1.1.c GREEN: crear pyproject.toml y actualizar requirements-dev.txt y pytest.ini
  - [x] 1.1.d TRIANGULATE: N/A — configuración declarativa de herramientas estáticas
  - [x] 1.1.e REFACTOR: verificar ruff check . sin errores en el codebase

### Phase 2: Esquemas Declarativos de Validación
- [x] 2.1 Implementar esquemas de writeback, ventas y ajustes en schemas/
  - [x] 2.1.a Safety Net: verificar importación de pydantic en el entorno
  - [x] 2.1.b RED: escribir tests/test_schemas.py que falle por ausencia de modelos
  - [x] 2.1.c GREEN: implementar schemas/writeback.py, schemas/ventas.py y schemas/ajustes.py
  - [x] 2.1.d TRIANGULATE: probar casos con números válidos, comas venezolanas, campos nulos y campos extra
  - [x] 2.1.e REFACTOR: unificar exportaciones en schemas/__init__.py

### Phase 3: Arnés de Aislamiento y Tests de Writeback
- [x] 3.1 Implementar tests/harness/mock_hybrid.py y suites de writeback y safety
  - [x] 3.1.a Safety Net: verificar que pytest no toca hardware real
  - [x] 3.1.b RED: escribir tests/test_listener_writeback.py y tests/test_safety_control.py fallando sin mocks
  - [x] 3.1.c GREEN: implementar mock_hybrid_env interceptando Win32, SendInput y mutexes
  - [x] 3.1.d TRIANGULATE: probar reintentos en fallos pre-commit vs error inmediato en fallos post-commit y mutua exclusión
  - [x] 3.1.e REFACTOR: limpiar fixtures reutilizables en tests/harness

### Phase 4: Batería de Pruebas para Sincronizadores y Watchdog
- [x] 4.1 Implementar tests para sync_ventas, sync_ajustes y backend_watchdog
  - [x] 4.1.a Safety Net: verificar que los tests existentes de sync siguen pasando
  - [x] 4.1.b RED: escribir tests/test_sync_ventas.py, tests/test_sync_ajustes.py y tests/test_backend_watchdog.py
  - [x] 4.1.c GREEN: implementar pruebas de hashing de ventas, tiempos DBISAM y monitoreo de PIDs
  - [x] 4.1.d TRIANGULATE: evaluar casos de ventas sin cambios, ventas nuevas y procesos vivos/muertos
  - [x] 4.1.e REFACTOR: asegurar ejecución completa en <25s
