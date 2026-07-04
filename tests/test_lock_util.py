"""
tests/test_lock_util.py — Tests para lock_util.acquire_lock y helpers.
"""
import os
import pytest
import time


# ─── Tests de pid_exists() ────────────────────────────────────────────────────

class TestPidExists:
    def test_proceso_actual_existe(self):
        """El PID del proceso actual siempre existe."""
        from lock_util import pid_exists
        assert pid_exists(os.getpid()) is True

    def test_pid_cero_retorna_false(self):
        """PID 0 retorna False."""
        from lock_util import pid_exists
        assert pid_exists(0) is False

    def test_pid_negativo_retorna_false(self):
        """PID negativo retorna False."""
        from lock_util import pid_exists
        assert pid_exists(-1) is False

    def test_pid_none_retorna_false(self):
        """None retorna False."""
        from lock_util import pid_exists
        assert pid_exists(None) is False

    def test_pid_inexistente_retorna_false(self):
        """PID muy alto que no existe retorna False."""
        from lock_util import pid_exists
        assert pid_exists(9_999_999) is False


# ─── Tests de acquire_lock() ──────────────────────────────────────────────────

class TestAcquireLock:
    def test_adquiere_y_libera_lock(self, tmp_path, monkeypatch):
        """acquire_lock crea el archivo lock y lo elimina al salir."""
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

    def test_lock_liberado_en_excepcion(self, tmp_path, monkeypatch):
        """El lock se libera aunque el cuerpo lance excepción."""
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))

        with pytest.raises(ValueError):
            with lock_util.acquire_lock(timeout=5):
                raise ValueError("error simulado")

        assert not lock_file.exists()

    def test_escribe_pid_propio_en_lock(self, tmp_path, monkeypatch):
        """El archivo lock contiene el PID del proceso que lo adquirió."""
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))

        with lock_util.acquire_lock(timeout=5):
            content = lock_file.read_text().strip()
            assert int(content) == os.getpid()

    @pytest.mark.slow
    def test_timeout_si_lock_tomado_por_proceso_vivo(self, tmp_path, monkeypatch):
        """Lanza TimeoutError si el lock está tomado por el proceso actual (vivo)."""
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))

        lock_file.write_text(str(os.getpid()))  # PID actual = proceso vivo

        with pytest.raises(TimeoutError):
            with lock_util.acquire_lock(timeout=3):
                pass


# ─── Tests de is_locked() ─────────────────────────────────────────────────────

class TestIsLocked:
    def test_sin_lock_file_retorna_false(self, tmp_path, monkeypatch):
        """is_locked() retorna False si no existe el archivo lock."""
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))

        assert lock_util.is_locked() is False

    def test_con_lock_del_proceso_actual_retorna_true(self, tmp_path, monkeypatch):
        """is_locked() retorna True si el lock tiene el PID del proceso actual."""
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))
        lock_file.write_text(str(os.getpid()))

        assert lock_util.is_locked() is True

    def test_con_lock_huerfano_retorna_false(self, tmp_path, monkeypatch, mocker):
        """is_locked() retorna False si el PID del lock está muerto."""
        import lock_util
        lock_file = tmp_path / "test.lock"
        monkeypatch.setattr(lock_util, "LOCK_FILE", str(lock_file))
        lock_file.write_text("99999")
        mocker.patch("lock_util.pid_exists", return_value=False)

        assert lock_util.is_locked() is False


# ─── Tests de safe_replace() ──────────────────────────────────────────────────

class TestSafeReplace:
    def test_reemplaza_archivo_existente(self, tmp_path):
        """Reemplaza dst con src cuando dst ya existe."""
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
        """Renombra src a dst cuando dst no existe."""
        from lock_util import safe_replace
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("contenido")

        result = safe_replace(str(src), str(dst))

        assert result is True
        assert dst.read_text() == "contenido"
        assert not src.exists()


# ─── Tests de sync_utils (ejecutados aquí para agrupar utilidades) ─────────────

class TestSyncUtils:
    def test_safe_decimal_formato_venezolano(self):
        from sync_utils import safe_decimal
        assert safe_decimal("1.500,50") == 1500.50

    def test_safe_decimal_formato_punto(self):
        from sync_utils import safe_decimal
        assert safe_decimal("1500.50") == 1500.50

    def test_safe_decimal_prefijo_bs(self):
        from sync_utils import safe_decimal
        assert safe_decimal("Bs. 1.500,50") == 1500.50

    def test_safe_decimal_none(self):
        from sync_utils import safe_decimal
        assert safe_decimal(None) == 0.0

    def test_safe_decimal_string_vacio(self):
        from sync_utils import safe_decimal
        assert safe_decimal("") == 0.0

    def test_safe_decimal_invalido(self):
        from sync_utils import safe_decimal
        assert safe_decimal("abc") == 0.0

    def test_exponential_backoff_techo(self):
        from sync_utils import exponential_backoff
        assert exponential_backoff(100) == 15.0

    def test_exponential_backoff_primer_intento(self):
        from sync_utils import exponential_backoff
        assert exponential_backoff(1) == 1.5
