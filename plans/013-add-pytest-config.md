# Plan 013: Agregar configuración de pytest y baseline de cobertura

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- pytest.ini setup.cfg pyproject.toml tests/`

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (puede ejecutarse en cualquier orden, pero mejor después de los planes de tests)
- **Category**: dx
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

No hay `pytest.ini` ni configuración de cobertura. El comando documentado en README es solo `pytest` sin flags de cobertura ni markers. Sin configuración:
- No se sabe qué porcentaje del código está cubierto
- No hay markers para separar tests lentos de tests rápidos
- No hay un umbral de cobertura mínimo que CI pueda verificar

Este plan agrega `pytest.ini` con configuración básica y `pytest-cov` para reportes de cobertura.

## Estado actual

```
# requirements.txt (actual) — no tiene pytest-cov
pytest
pytest-flask
pytest-mock
responses
```

```
# No existe pytest.ini, setup.cfg, ni pyproject.toml
```

Los tests existentes:
- `tests/test_app.py` — 86 líneas, prueba Flask endpoints
- `tests/test_sync.py` — 70 líneas, prueba sync_incremental y helpers
- `tests/test_supabase_rest.py` — prueba REST client
- `tests/test_config.py` — prueba carga de config
- `tests/test_widget.py` — prueba widget

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Tests con cobertura | `python -m pytest tests/ -v --cov=. --cov-report=term-missing` | Todos pasan + reporte |
| Solo tests rápidos | `python -m pytest tests/ -v -m "not slow"` | Pasan (excluye lentos) |

## Scope

**En scope**:
- `pytest.ini` (crear)
- `requirements-dev.txt` (crear o actualizar si plan 011 ya lo creó)

**Fuera de scope**:
- Los tests existentes (no modificar)
- `setup.py` / `pyproject.toml` — no crear si no existen

## Git workflow

- Branch: `advisor/013-add-pytest-config`
- Commit: `dx: agregar pytest.ini con configuración de cobertura y markers`

## Pasos

### Paso 1: Instalar pytest-cov

```powershell
python -m pip install pytest-cov
```

Verificar la versión instalada:
```powershell
python -m pip show pytest-cov | Select-String "Version"
```

Agregar al `requirements-dev.txt` (o crearlo si no existe del plan 011):
```
pytest-cov==X.X.X
```

### Paso 2: Crear `pytest.ini`

Crear `C:\Proyect\backend serrucho\pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*

# Markers para clasificar tests
markers =
    slow: tests que tardan más de 2 segundos (lock timeouts, network)
    integration: tests que requieren Supabase real o H: drive

# Opciones por defecto
addopts =
    -v
    --tb=short
    --cov=.
    --cov-report=term-missing
    --cov-config=.coveragerc
    --ignore=scratch
    --ignore=hybrid_writeback

# Suprimir warnings esperados
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
```

### Paso 3: Crear `.coveragerc`

Crear `C:\Proyect\backend serrucho\.coveragerc`:

```ini
[run]
source = .
omit =
    tests/*
    scratch/*
    hybrid_writeback/*
    widget*.py
    widget_backup*.py
    *__pycache__*
    setup.py
    conftest.py

[report]
exclude_lines =
    pragma: no cover
    if sys.executable.lower().endswith("pythonw.exe")
    except: pass
    raise NotImplementedError
    if __name__ == "__main__":
```

### Paso 4: Ejecutar y verificar baseline

```powershell
python -m pytest tests/ -v
```

Esperado: todos los tests pasan y se imprime un reporte de cobertura.

Anotar el porcentaje de cobertura actual para tener un baseline. No imponer un umbral mínimo aún — primero establecer la línea base con los tests existentes.

**Verificar**: el comando termina con `Xpassed` y muestra el reporte de cobertura.

### Paso 5: Agregar marker `slow` al test más lento

En `tests/test_lock_util.py` (del plan 010), el test `test_segundo_adquirir_espera_hasta_timeout` usa un timeout real de 3 segundos. Marcarlo:

```python
@pytest.mark.slow
def test_segundo_adquirir_espera_hasta_timeout(self, tmp_path, monkeypatch):
    ...
```

**Verificar**: `python -m pytest tests/ -m "not slow" -v` → excluye ese test específico

## Criterios de done

- [ ] `pytest.ini` existe con `testpaths`, `markers`, y `addopts` configurados
- [ ] `.coveragerc` existe con los omits correctos
- [ ] `pytest-cov` está en `requirements-dev.txt`
- [ ] `python -m pytest tests/ -v` → todos los tests pasan con reporte de cobertura
- [ ] `python -m pytest tests/ -m "not slow" -v` → funciona sin error de marker desconocido
- [ ] Solo archivos de configuración fueron creados/modificados
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- `pytest-cov` no se puede instalar (Python 3.14 tiene incompatibilidades) → usar `coverage` directamente sin pytest-cov, o reportar la incompatibilidad

## Notas de mantenimiento

- A medida que se agregan tests (planes 009, 010), la cobertura aumentará. Revisar el reporte después de cada plan de tests para saber qué módulos siguen sin cobertura.
- Para agregar un threshold mínimo en el futuro: agregar `--cov-fail-under=60` a `addopts`
