# Exploration: backend-assurance-and-tests

## Request Understanding
El usuario solicitó establecer un sistema de pruebas y aseguradores para el backend (`backend serrucho`) que abarque esquemas de datos, linters y cobertura exhaustiva (incluyendo el sistema de `hybrid_writeback`), de modo que diagnosticar, reparar y evolucionar el backend sea económico, rápido y seguro.

Restricciones y alcance:
- Entorno de ejecución: Windows con Python 3.14.2.
- Integraciones críticas: HybridLite (ERP Win32 legado mediante DBISAM y automatización de hardware con SendInput/realinput), Supabase PostgREST, API Flask y procesos demonio/watchdog.
- No romper flujos existentes en producción ni alterar los esquemas de bases de datos externas de forma incompatible.
- Asegurar ejecución autónoma de pruebas sin requerir una sesión de escritorio interactiva con HybridLite abierto.

## Current State
- **Pruebas**: 140 pruebas existentes en `tests/` pasan en ~18s (`python -m pytest`). Sin embargo, `pytest.ini` contiene `--ignore=hybrid_writeback`, dejando el componente más delicado fuera del ciclo de verificación estándar.
- **Linters y Formato**: Inexistentes. `profile.md` reportaba `lint_command: null` y `typecheck_command: null`. No hay `pyproject.toml` ni reglas estáticas.
- **Validación de Datos**: Las comunicaciones con Supabase, archivos CSV locales y requests se manipulan con diccionarios genéricos (`dict`) y conversiones manuales ad-hoc (`safe_decimal`, `.get()`). Errores de tipo o claves nulas/ausentes fallan tardíamente durante la ejecución.
- **Puntos Ciegos**: `hybrid_writeback/listener_writeback.py`, `hybrid_writeback/safety_control.py`, `sync_ventas.py`, `sync_ajustes.py` y `backend_watchdog.py` no cuentan con cobertura de pruebas unitarias directas ni arnés de aislamiento.

## Affected Areas
| Area | Evidence | Why It Matters |
|------|----------|----------------|
| Calidad Estática y Configuración | Inexistencia de `pyproject.toml`, linters ausentes en `requirements-dev.txt` | Permite detectar errores de sintaxis, variables no declaradas e imports rotos en milisegundos sin arrancar el runtime. |
| Esquemas de Datos (Schemas) | Manipulación de `dict` crudos en `listener_writeback.py` (L145-155), `sync_ventas.py` (L78-85) y `sync_ajustes.py` | La falta de validación de esquemas (Fail-Fast) permite que datos corruptos lleguen a HybridLite o Supabase. |
| Arnés de Pruebas Writeback | `pytest.ini` L11 (`--ignore=hybrid_writeback`), dependencias Win32 en `safety_control.py` y `listener_writeback.py` | `hybrid_writeback` controla mouse/teclado y bases DBISAM; necesita un harness con mocks para testear lógica y máquina de estados sin GUI real. |
| Sincronización de Ventas y Ajustes | `sync_ventas.py` (592 líneas) y `sync_ajustes.py` (457 líneas) sin archivos `test_sync_ventas.py` ni `test_sync_ajustes.py` en `tests/` | Son los motores de conciliación entre la tienda local y la nube; cualquier regresión corrompe inventario y estadísticas de venta. |
| Watchdog y Estabilidad | `backend_watchdog.py` (407 líneas) sin pruebas | Es el proceso supervisor responsable de revivir listeners caídos; requiere pruebas de detección de PIDs y cooldowns. |

## Existing Tests
| Test/File | Relevance | Missing Coverage |
|-----------|-----------|------------------|
| `tests/test_lock_util.py` | Cubre locks de archivo, PID y helpers numéricos (`safe_decimal`) | Cobertura adecuada de primitivas base. |
| `tests/test_price_tolerance_and_confirmation.py` | Verifica tolerancias de precios en GUI | No prueba la cola de writeback ni reintentos en Supabase. |
| `tests/test_hybrid_health.py` | Limpieza de procesos y huérfanos de HybridLite | No prueba `safety_control.py` (Mutex inter-proceso, F12 abort). |
| `tests/test_flujo_pedido_real.py` | Lógica de pedidos en Hybrid | No cubre `listener_writeback.py` ni `listener_base.py`. |
| `tests/test_sync.py` | Sincronización básica de hashes | No cubre ventas cabecera/detalle ni ajustes de inventario. |

## Options
| Option | Pros | Cons | Risk | Effort |
|--------|------|------|------|--------|
| **Opción A**: Suite Integral con Ruff + Pydantic v2 + Test Harness de Writeback y Syncs | Cobertura total de estática a runtime; validación Fail-Fast de datos; pruebas deterministas sin GUI; verificación en <1s de linters y tests seguros. | Requiere introducir `pyproject.toml`, dependencia `pydantic` y refactorizar puntos de entrada para usar schemas. | Bajo (aditivo y sin tocar tablas de producción). | Medio |
| **Opción B**: Solo Linters (Ruff) y Tests Mínimos en `tests/` | Implementación muy rápida; no introduce Pydantic ni cambios en estructuras de datos. | Mantiene la fragilidad de diccionarios planos sin tipar; datos malformados siguen pasando a HybridLite. | Medio (los bugs de datos en producción persisten). | Bajo |
| **Opción C**: Tipado estricto con MyPy sobre todo el codebase | Máxima seguridad estática de tipos. | El codebase actual usa mucho código dinámico Win32/COM y DBISAM; MyPy generará cientos de falsos positivos y requerirá refactor masivo de tipos. | Alto (fricción y tiempo excesivo). | Alto |

## Recommendation
Implementar la **Opción A**:
1. Configurar **Ruff** en `pyproject.toml` como linter y formateador ultrarrápido y añadir `pytest-cov`.
2. Crear modelos **Pydantic v2** en `schemas/` para validar transacciones de writeback, ventas y ajustes antes de procesarlas.
3. Crear un **Harness de Simulación** en `tests/harness/mock_hybrid.py` que permita testear `listener_writeback.py` y `safety_control.py` en entornos headless.
4. Desarrollar suites de pruebas unitarias dedicadas para `sync_ventas.py`, `sync_ajustes.py` y `backend_watchdog.py`.

## Risks
- **Riesgo 1**: Falsos fallos de linters por código Win32 dinámico (`ctypes`, `win32com`).
  - *Mitigación*: Ajustar exclusiones y reglas permisivas para módulos COM en `pyproject.toml`.
- **Riesgo 2**: Validación de esquemas demasiado rígida que rechace payloads válidos con campos opcionales no documentados de Supabase.
  - *Mitigación*: Diseñar modelos Pydantic con campos opcionales (`Optional[...] = None`) y `model_config = ConfigDict(extra="ignore")` para tolerar columnas adicionales.
- **Riesgo 3**: Tests de writeback que interactúen con el hardware real por error.
  - *Mitigación*: Asegurar que el harness mockee explícitamente `realinput` y `ctypes.windll.user32` impidiendo cualquier llamada Win32 real durante pytest.

## Open Questions
- Ninguna pregunta bloqueante. La estrategia es estrictamente aditiva y no altera contratos de red ni esquemas de bases de datos.

## Ready For Planning
Yes. El estado actual, los puntos ciegos y la estrategia de aseguramiento están completamente determinados con evidencia de código.
