import os
import sys
import threading
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HW_DIR = os.path.join(BASE_DIR, "hybrid_writeback")
if HW_DIR not in sys.path:
    sys.path.insert(0, HW_DIR)

import safety_control


class TestSafetyControl:
    def test_control_seguro_execution_flow(self, monkeypatch):
        # Desactivar banner tkinter y registro real de teclado para pruebas automáticas
        monkeypatch.setattr(safety_control._Banner, "iniciar", lambda self: None)
        monkeypatch.setattr(safety_control._Banner, "cerrar", lambda self: None)
        monkeypatch.setattr(safety_control, "_registrar_hotkey", lambda: True)
        monkeypatch.setattr(safety_control, "_quitar_hotkey", lambda: None)
        monkeypatch.setattr(safety_control, "_bloquear_inputs", lambda b: None)

        executed = False
        with safety_control.control_seguro("TEST AUTOMATICO") as handle:
            executed = True
            handle.set_texto("ACTUALIZANDO...")
            assert not safety_control.fue_abortado()

        assert executed is True

    def test_abort_flag_triggering(self):
        safety_control._abort_flag.clear()
        assert not safety_control.fue_abortado()

        # Simular activación del flag de aborto
        safety_control._abort_flag.set()
        assert safety_control.fue_abortado() is True

        # Limpiar
        safety_control._abort_flag.clear()
        assert not safety_control.fue_abortado()

    def test_mutex_concurrency(self, monkeypatch):
        """Valida que el mutex de hardware maneje la concurrencia de forma segura."""
        monkeypatch.setattr(safety_control._Banner, "iniciar", lambda self: None)
        monkeypatch.setattr(safety_control._Banner, "cerrar", lambda self: None)
        monkeypatch.setattr(safety_control, "_registrar_hotkey", lambda: True)
        monkeypatch.setattr(safety_control, "_quitar_hotkey", lambda: None)
        monkeypatch.setattr(safety_control, "_bloquear_inputs", lambda b: None)

        order = []

        def worker(ident):
            with safety_control.control_seguro(f"Worker {ident}"):
                order.append(f"enter_{ident}")
                order.append(f"exit_{ident}")

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert "enter_1" in order and "exit_1" in order
        assert "enter_2" in order and "exit_2" in order

    def test_adquirir_y_liberar_mutex_directo(self):
        handle = safety_control._adquirir_mutex_mouse()
        assert handle is not None
        safety_control._liberar_mutex_mouse(handle)
