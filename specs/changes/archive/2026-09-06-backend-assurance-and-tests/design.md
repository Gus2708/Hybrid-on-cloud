# Design: backend-assurance-and-tests

## Technical Approach
Implementar un sistema de aseguramiento de código, contratos de datos y suites de pruebas deterministas organizados en cuatro capas:
1. **Calidad Estática**: Configuración de `pyproject.toml` definiendo **Ruff** (reglas `E`, `F`, `W`, `B`, `I`) y opciones de cobertura con `pytest-cov`, permitiendo diagnósticos completos en <100ms sin tocar producción.
2. **Esquemas Declarativos (`schemas/`)**: Modelos **Pydantic v2** (`WritebackItemSchema`, `VentaCabeceraSchema`, `VentaDetalleSchema`, `AjusteInventarioSchema`) con tolerancia a campos adicionales (`extra="ignore"`) y coerción de formatos venezolanos de decimales.
3. **Arnés de Simulación (`tests/harness/mock_hybrid.py`)**: Aislamiento total de APIs Win32 (`realinput.SendInput`, `ctypes.windll.user32`, handles de ventanas) para permitir ejecutar tests de `listener_writeback.py` y `safety_control.py` de forma determinista y headless.
4. **Suites de Pruebas**: Tests unitarios con datos sintéticos y mocking para `sync_ventas.py`, `sync_ajustes.py` y `backend_watchdog.py`.

## Architecture Decisions
| Decision | Choice | Alternatives | Rationale |
|----------|--------|--------------|-----------|
| Linter & Formatter | Ruff configurado en `pyproject.toml` | Flake8, Black, Pylint | Ruff corre nativamente en Rust (<100ms), es 10-100x más rápido, unifica formato y linting, y es compatible con Python 3.14. |
| Validación de Esquemas | Pydantic v2 | Marshmallow, validación manual con `dict.get()`, dataclasses | Pydantic v2 ofrece validación ultrarrápida compilada en C/Rust, mensajes de error explícitos, coerciones numéricas y soporte nativo de JSON. |
| Aislamiento de Writeback | Fixture `mock_hybrid` interceptor de Win32/realinput | Depender de ventanas reales de HybridLite, omitir tests de writeback | Permite probar la máquina de estados, reintentos y mutexes en CI o entornos sin interfaz gráfica sin riesgo de mover el mouse físico. |
| Inclusión de tests en pytest.ini | Desbloquear `hybrid_writeback` de `pytest.ini` y usar suite centralizada en `tests/` | Dejar `hybrid_writeback` ignorado permanentemente | Permite que `python -m pytest` valide todo el backend, incluyendo la lógica de automatización. |

## Architecture Design

### Project Placement
```text
schemas/
├── writeback.py
│   └── WritebackItemSchema
        [new] Validacion de items de ordenes de cambio.
├── ventas.py
│   ├── VentaCabeceraSchema
        [new] Validacion de cabecera de ventas.
│   └── VentaDetalleSchema
        [new] Validacion de detalle de ventas.
└── ajustes.py
    └── AjusteInventarioSchema
        [new] Validacion de transacciones de inventario.
tests/
├── harness/
│   └── mock_hybrid.py
│       └── mock_hybrid_env
            [new] Fixture de aislamiento para pruebas de writeback.
├── test_schemas.py
│   └── test_writeback_validation()
        [new] Pruebas de validacion de esquemas.
├── test_listener_writeback.py
│   └── test_retry_policy()
        [new] Pruebas de maquina de estados y reintentos.
├── test_safety_control.py
│   └── test_mutex_concurrency()
        [new] Pruebas de exclusion mutua y aborto.
├── test_sync_ventas.py
│   └── test_ventas_batch()
        [new] Pruebas de extraccion y payload de ventas.
├── test_sync_ajustes.py
│   └── test_decode_time()
        [new] Pruebas de decodificacion de tiempos DBISAM.
└── test_backend_watchdog.py
    └── test_watchdog_alive()
        [new] Pruebas de deteccion de procesos vivos.
```

### Data Flow
1. **Supabase REST / CSV -> `schemas/`**: Los datos crudos recibidos desde PostgREST o CSV pasan por `model_validate()`. Si contienen errores (ej. `delta` ausente o costo corrupto), se rechazan inmediatamente en la frontera con un log claro.
2. **`schemas/` -> `listener_writeback`**: Los items limpios y tipados alimentan la máquina de estados de ejecución robótica.
3. **Ejecución Robótica -> `mock_hybrid`**: En pruebas, cualquier invocación a `realinput.click` o `ctypes.windll` es capturada por el interceptor del arnés, registrando las llamadas para validación sin tocar el hardware.

### Interfaces / Contracts
- `WritebackItemSchema`:
  - Campos: `id: int`, `orden_id: int`, `codigo_producto: str`, `delta: float`, `costo: Optional[float] = None`, `precio_actual: Optional[float] = None`, `nuevo_precio: Optional[float] = None`, `descripcion: Optional[str] = None`.
  - Configuración: `ConfigDict(extra="ignore")`.
- `mock_hybrid_env(monkeypatch)`:
  - Intercepta `realinput.SendInput`, `listener_writeback.control_seguro`, y llamadas `ctypes`.

## Testing Strategy
| Layer | What | Approach |
|-------|------|----------|
| Estática (Linter) | Sintaxis, variables no declaradas, imports | `python -m ruff check .` sobre todo el repositorio. |
| Unitaria (Schemas) | Modelos Pydantic v2 | Tests de casos válidos, valores nulos, coerción de comas decimales venezolanas y campos extra. |
| Unitaria (Writeback) | Máquina de estados y seguridad de writeback | Tests aislados con `mock_hybrid_env` evaluando reintentos en pre-commit vs error en post-commit. |
| Unitaria (Sync) | Conciliación de ventas y ajustes | Pruebas con fixtures sintéticos sin conexión de red a Supabase. |
| Unitaria (Watchdog) | Supervisión y cooldowns | Pruebas mockeando PIDs del sistema operativo. |

## Migration / Rollout
1. Instalar dependencias en el entorno virtual / Python 3.14.
2. Añadir `pyproject.toml` y verificar que `ruff check .` pase limpiamente.
3. Crear `schemas/` e integrarlo progresivamente sin alterar las funciones existentes.
4. Añadir las nuevas suites en `tests/` y validar que corran junto con los 140 tests existentes.

## Technical Risks
| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Falsos positivos de Ruff en scripts dinámicos | Baja | Exclusiones precisas de reglas cosméticas en `pyproject.toml`. |
| Interferencia de llamadas Win32 reales | Baja | Fixture `mock_hybrid_env` monkeypatchea los módulos antes de importar flujos. |
| Incremento del tiempo de tests | Baja | Todo corre en memoria sin pausas ni dependencias de red; tiempo total estimado <25s. |

## Open Questions
- Ninguna pregunta bloqueante.
