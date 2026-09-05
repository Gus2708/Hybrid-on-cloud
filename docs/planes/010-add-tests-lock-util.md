# Plan 010: Agregar tests para `lock_util.py` — locks, PIDs y timeouts

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- lock_util.py tests/`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

`lock_util.py` protege contra sincronizaciones simultáneas que corromperían los CSV y el cache de hashes. Tiene lógica de:
- Detección de locks huérfanos (PID muerto)
- Timeout configurable
- Limpieza de `.tmp` colgados
- PID-based alive check con ctypes en Windows

Si esta lógica falla (por ejemplo, reutilización de PID en Windows, o condición de carrera al limpiar un lock huérfano), dos procesos pueden sincronizar simultáneamente corrompiendo `MAESTRO_ACTUAL.csv`. Actualmente hay **cero tests** para este módulo crítico.

## Estado actual

```python
# lock_util.py:67-106 — acquire_lock (context manager)
@contextmanager
def acquire_lock(timeout=120):
    start_time = time.time()
    acquired = False
    
    while time.time() - start_time < timeout:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w') as f:
                f.write(str(os.getpid()))
            acquired = True
            break
        except FileExistsError:
            # Verificar si el lock es "huérfano"
            try:
                if os.path.exists(LOCK_FILE):
                    with open(LOCK_FILE, "r") as f:
                        content = f.read().strip()
                        if content:
                            old_pid = int(content)
                            if not pid_exists(old_pid):
                                try: os.remove(LOCK_FILE)
                                except: pass
                                continue
            except: pass
            time.sleep(2)
            continue
            
    if not acquired:
        raise TimeoutError(f"No se pudo adquirir el bloqueo...")
```

```python
# lock_util.py:35-64 — pid_exists() con ctypes
def pid_exists(pid):
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                res = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                return bool(res and exit_code.value == 259)  # 259 = STILL_ACTIVE
            else:
                err = kernel32.GetLastError()
                if err == 5:  # ERROR_ACCESS_DENIED → proceso vivo
                    return True
                return False
        except:
            return False
```

Patrón de tests del proyecto: usar `tmp_path` fixture de pytest y `mocker` de pytest-mock.

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Tests antes | `python -m pytest tests/ -v` | Todos pasan |
| Nuevo archivo | `python -m pytest tests/test_lock_util.py -v` | Todos los nuevos pasan |
| Tests completos | `python -m pytest tests/ -v` | Todos pasan |

## Scope

**En scope**:
- `tests/test_lock_util.py` — crear nuevo archivo

**Fuera de scope**:
- `lock_util.py` — no modificar (solo testear)

## Git workflow

- Branch: `advisor/010-add-lock-util-tests`
- Commit: `test: agregar cobertura para lock_util (acquire_lock, pid_exists, stale locks)`

## Pasos

### Paso 1: Crear `tests/test_lock_util.py`

```python
"""
tests/test_lock_util.py — Tests para lock_util.acquire_lock y helpers.
"""
import os
import pytest
import threading
import time


# ─── Tests de pid_exists() ───────────────────────────────────────────────────

class TestPidExists:
    def test_proceso_actual_existe(self):
        """El PID del proceso actual siempre existe."""
        from lock_util import pid_exists
        assert pid_exists(os.getpid()) is True

    def test_pid_cero_no_existe(self):
        """PID 0 o negativo retorna False."""
        from lock_util import pid_exists
        assert pid_exists(0) is False
        assert pid_exists(-1) is False
        assert pid_exists(None) is False

    def test_pid_inexistente_retorna_false(self):
        """Un PID muy alto que no existe retorna False."""
        from lock_util import pid_exists
        # PID 9999999 es improbable que exista
        result = pid_exists(9999999)
        assert result is False


# ─── Tests de acquire_lock() ─────────────────────────────────────────────────

class TestAcquireLock:
    def test_adquiere_y_libera_lock(self, tmp_path, monkeypatch):
        """acquire_lock crea el lock file y lo elimina al salir del context."""
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))

        assert not lock_file.exists()
        
        with lock_util.acquire_lock(timeout=5):
            assert lock_file.exists()
            content = lock_file.read_text().strip()
            assert content.isdigit()
            assert int(content) == os.getpid()
        
        assert not lock_file.exists()

    def test_segundo_adquirir_espera_hasta_timeout(self, tmp_path, monkeypatch):
        """Si el lock está tomado por un proceso vivo, TimeoutError tras timeout."""
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))

        # Crear lock con PID real (proceso actual = proceso "vivo")
        lock_file.write_text(str(os.getpid()))

        with pytest.raises(TimeoutError):
            with lock_util.acquire_lock(timeout=3):  # Timeout corto para el test
                pass

    def test_limpia_lock_huerfano(self, tmp_path, monkeypatch, mocker):
        """Si el lock tiene un PID muerto, acquire_lock lo limpia y continúa."""
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))

        # PID 99999 probablemente no existe — simular con mock
        lock_file.write_text("99999")
        mocker.patch("lock_util.pid_exists", side_effect=lambda pid: False if pid == 99999 else True)

        # Debe adquirir el lock limpiando el huérfano
        with lock_util.acquire_lock(timeout=5):
            assert lock_file.exists()
        
        assert not lock_file.exists()

    def test_lock_liberado_en_excepcion(self, tmp_path, monkeypatch):
        """El lock se libera aunque el cuerpo del context manager lance excepción."""
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))

        with pytest.raises(ValueError):
            with lock_util.acquire_lock(timeout=5):
                raise ValueError("error simulado")

        # El lock debe haberse liberado
        assert not lock_file.exists()


# ─── Tests de is_locked() ────────────────────────────────────────────────────

class TestIsLocked:
    def test_sin_lock_file_retorna_false(self, tmp_path, monkeypatch):
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))

        assert lock_util.is_locked() is False

    def test_con_lock_de_proceso_actual_retorna_true(self, tmp_path, monkeypatch):
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))
        lock_file.write_text(str(os.getpid()))

        assert lock_util.is_locked() is True

    def test_con_lock_huerfano_retorna_false(self, tmp_path, monkeypatch, mocker):
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))
        lock_file.write_text("99999")
        mocker.patch("lock_util.pid_exists", return_value=False)

        assert lock_util.is_locked() is False


# ─── Tests de safe_replace() ─────────────────────────────────────────────────

class TestSafeReplace:
    def test_reemplaza_archivo_existente(self, tmp_path):
        from lock_util import safe_replace
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("nuevo")
        dst.write_text("viejo")

        result = safe_replace(str(src), str(dst))

        assert result is True
        assert dst.read_text() == "nuevo"
        assert not src.exists()

    def test_renombra_si_dst_no_existe(self, tmp_path):
        from lock_util import safe_replace
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("contenido")

        result = safe_replace(str(src), str(dst))

        assert result is True
        assert dst.read_text() == "contenido"
```

**Verificar**: `python -m pytest tests/test_lock_util.py -v` → mínimo 10 tests pasan

### Paso 2: Verificar suite completa

```powershell
python -m pytest tests/ -v
```

## Criterios de done

- [ ] `tests/test_lock_util.py` existe con mínimo 10 tests
- [ ] `python -m pytest tests/test_lock_util.py -v` → todos pasan
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo `tests/test_lock_util.py` fue creado
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- `test_segundo_adquirir_espera_hasta_timeout` demora 3+ segundos → es normal (el timeout del test es intencional). Si el timeout se vuelve un problema de CI, reducirlo y usar `mocker.patch("time.sleep")` para acelerar.
- `monkeypatch.setattr(lock_util, "LOCK_FILE", ...)` no funciona porque `LOCK_FILE` está definido al nivel de módulo y ya fue usado por `clear_stale_locks()` → verificar si es necesario resetear el módulo entre tests.

## Notas de mantenimiento

- Si `LOCK_FILE` o `pid_exists()` cambian, actualizar los tests correspondientes
- El test `test_segundo_adquirir_espera_hasta_timeout` es lento por diseño — puede marcarse con `@pytest.mark.slow` y excluirse en CI rápido
