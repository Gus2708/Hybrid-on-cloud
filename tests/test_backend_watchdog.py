import os
import pytest
import backend_watchdog


class TestBackendWatchdog:
    def test_is_alive_current_process(self):
        # El proceso actual de pytest está vivo
        pid = os.getpid()
        assert backend_watchdog.is_alive(pid) is True

    def test_is_alive_nonexistent_pid(self):
        # PIDs no válidos o inexistentes retornan False
        assert backend_watchdog.is_alive(None) is False
        assert backend_watchdog.is_alive(0) is False
        assert backend_watchdog.is_alive(-1) is False
        assert backend_watchdog.is_alive(9999999) is False

    def test_rotate_log(self, tmp_path, monkeypatch):
        log_file = tmp_path / "test_watchdog.log"
        # Crear archivo que supere el umbral
        log_file.write_bytes(b"A" * 1000)
        monkeypatch.setattr(backend_watchdog, "LOG_FILE", str(log_file))
        monkeypatch.setattr(backend_watchdog, "_MAX_LOG_BYTES", 500)

        backend_watchdog._rotate_log()

        # Debe existir el .1 rotado
        bak_file = tmp_path / "test_watchdog.log.1"
        assert bak_file.exists()

    def test_cleanup_removes_lock(self, tmp_path, monkeypatch):
        lock_file = tmp_path / "watchdog.lock"
        lock_file.write_text("12345", encoding="utf-8")
        monkeypatch.setattr(backend_watchdog, "LOCK_FILE", str(lock_file))

        backend_watchdog._cleanup()
        assert not lock_file.exists()
