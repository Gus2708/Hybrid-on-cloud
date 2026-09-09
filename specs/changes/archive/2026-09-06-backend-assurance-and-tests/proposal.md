# Proposal: backend-assurance-and-tests

## Intent
El backend de sincronización y automatización robótica (HybridLite, Supabase, DBISAM y API local) carece de aseguradores automáticos modernos (linters estáticos, esquemas de validación de datos y harness de tests para el subsistema de writeback). Cualquier fallo en payloads o regresión en el código requiere depuración manual costosa en producción. Implementar un arnés de aseguramiento integral reduce drásticamente el costo de mantenimiento y el riesgo de incidentes operativos.

## Scope
### In Scope
- Configuración de **Ruff** y `pytest-cov` en `pyproject.toml` y `requirements-dev.txt` para verificación estática ultrarrápida (<100ms) compatible con Python 3.14.
- Creación del paquete de esquemas declarativos `schemas/` con **Pydantic v2** para validar contratos de datos en fronteras de Supabase PostgREST, archivos CSV y colas de writeback (`ordenes_cambio_items`, `ventas_cabecera`, `ventas_detalle`, `ajustes`).
- Creación de un arnés de simulación headless (`tests/harness/mock_hybrid.py`) para aislar llamadas Win32 y `realinput`.
- Implementación de suites de pruebas unitarias para `hybrid_writeback/listener_writeback.py` (máquina de estados, reintentos, ventana horaria) y `hybrid_writeback/safety_control.py` (Mutex inter-proceso y aborto F12).
- Implementación de suites de pruebas unitarias para los motores de sincronización `sync_ventas.py`, `sync_ajustes.py` y el supervisor `backend_watchdog.py`.
- Actualización de `pytest.ini` para incluir el harness sin ignorar el subsistema de writeback.

### Out of Scope
- Modificación de esquemas de bases de datos remotas en Supabase o tablas locales de HybridLite.
- Refactorización total de la arquitectura legacy de HybridLite o reemplazo del motor DBISAM.
- Tipado estricto con MyPy en código COM/Win32 dinámico.

## Capabilities
### New Capabilities
- `code-quality`: Linters, reglas estáticas de código y medición de cobertura ejecutables con un solo comando.
- `schema-validation`: Validación declarativa de datos Fail-Fast con modelos Pydantic v2 en fronteras de integración.
- `writeback-assurance`: Entorno de prueba aislado y batería de pruebas automáticas para la lógica y seguridad del writeback robótico.
- `sync-assurance`: Batería de pruebas unitarias con fixtures para conciliación de ventas, ajustes de inventario y supervisión de watchdog.

### Modified Capabilities
- Ninguna (no existen especificaciones vivas previas en `specs/specs`).

## Approach
1. **Infraestructura de Calidad**: Instalar `ruff`, `pytest-cov` y `pydantic` en el entorno; crear `pyproject.toml` definiendo reglas de linter y perfiles de cobertura sin interferir con scripts de producción.
2. **Esquemas Declarativos**: Implementar clases Pydantic (`WritebackItem`, `VentaCabecera`, `VentaDetalle`, `AjusteInventario`) con validación de tipos, coerción segura de decimales y compatibilidad tolerante a campos extras (`extra="ignore"`).
3. **Arnés de Simulación**: Diseñar fixtures reutilizables en `tests/harness/` que intercepten `realinput.SendInput`, handles de ventana Win32 y accesos a disco `H:`, permitiendo ejecutar pruebas deterministas de writeback en cualquier máquina.
4. **Pruebas de Sincronización y Supervisión**: Construir pruebas unitarias parametrizadas con datos sintéticos para `sync_ventas.py` (conciliación por hash, manejo de duplicados), `sync_ajustes.py` (tiempos DBISAM, detección de espejos locales) y `backend_watchdog.py` (monitoreo de PIDs y cooldowns).

## Affected Areas
| Area | Impact | Description |
|------|--------|-------------|
| `pyproject.toml` | Nuevo | Configuración de Ruff, exclusiones y perfil de pytest-cov. |
| `requirements-dev.txt` | Modificado | Declaración de `ruff`, `pytest-cov` y `pydantic`. |
| `pytest.ini` | Modificado | Ajuste de flags para ejecutar pruebas de writeback bajo el arnés simulado. |
| `schemas/` | Nuevo paquete | Modelos Pydantic v2 de validación de datos. |
| `tests/harness/` | Nuevo | Mocks y fixtures para simulación de HybridLite y Win32. |
| `tests/test_listener_writeback.py` | Nuevo | Pruebas de máquina de estados, idempotencia y reintentos. |
| `tests/test_safety_control.py` | Nuevo | Pruebas de exclusión mutua por Mutex y bandera de aborto. |
| `tests/test_sync_ventas.py` | Nuevo | Pruebas de extracción, hashing y paginación de ventas. |
| `tests/test_sync_ajustes.py` | Nuevo | Pruebas de decodificación y mapeo de ajustes. |
| `tests/test_backend_watchdog.py` | Nuevo | Pruebas de verificación de vida y cooldowns del watchdog. |

## Risks
| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Falsos positivos de Ruff en scripts existentes con patrones dinámicos | Media | Configurar reglas balanceadas (`E`, `F`, `W`, `B`, `I`) e ignorar reglas cosméticas conflictivas. |
| Sobrecarga o incompatibilidad de Pydantic v2 con Python 3.14 | Baja | Se verificó compatibilidad de instalación en Python 3.14.2 mediante dry-run con `pydantic-core==2.46.5`. |
| Interferencia accidental de tests de writeback con el hardware real del usuario | Baja | Los tests de writeback utilizarán el arnés `mock_hybrid` que bloquea y sustituye cualquier invocación a `realinput` y `ctypes.windll`. |

## Rollback Plan
Todas las adiciones son modulares (archivos nuevos en `schemas/`, `tests/` y configuración en `pyproject.toml`). En caso de reversión, basta con descartar los archivos nuevos y restaurar `pytest.ini` y `requirements-dev.txt` mediante `git checkout`.

## Success Criteria
- [ ] `python -m ruff check .` se ejecuta sin errores en la raíz del proyecto.
- [ ] `schemas/` valida payloads válidos e invalida datos corruptos con errores descriptivos.
- [ ] La suite de pruebas de `hybrid_writeback` se ejecuta y pasa al 100% en modo headless sin requerir HybridLite abierto.
- [ ] Las pruebas de `sync_ventas`, `sync_ajustes` y `backend_watchdog` cubren los casos críticos de datos.
- [ ] Toda la suite completa (`python -m pytest`) pasa exitosamente en menos de 30 segundos.

## Open Questions
- Ninguna. Alcance y diseño determinados.
