import os
import sys
import datetime
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HW_DIR = os.path.join(BASE_DIR, "hybrid_writeback")
if HW_DIR not in sys.path:
    sys.path.insert(0, HW_DIR)

import listener_base as lb
import listener_writeback as lw


class TestListenerWritebackPolicy:
    def test_reintentable_stage_under_max_retries(self):
        res = {"ok": False, "etapa": "abrir_hybrid", "detalle": "Ventana no abrió"}
        status, resultado = lw._politica_resultado(res, intentos=1)
        assert status == "pendiente"
        assert "Ventana no abrió" in resultado

    def test_reintentable_stage_exceeded_max_retries(self):
        res = {"ok": False, "etapa": "carga/conteo", "detalle": "Error conteo"}
        status, resultado = lw._politica_resultado(res, intentos=3)
        assert status == "error"

    def test_ambiguous_stage_causes_immediate_error(self):
        res = {"ok": False, "etapa": "post_commit_check", "detalle": "Timeout post commit"}
        status, resultado = lw._politica_resultado(res, intentos=0)
        assert status == "error"
        assert "fallo en etapa ambigua" in resultado

    def test_successful_commit_completes(self, monkeypatch):
        monkeypatch.setattr(lb, "check_hybrid_write_enabled", lambda: True)
        res = {"ok": True, "etapa": "commit", "detalle": "Ajuste aplicado"}
        status, resultado = lw._politica_resultado(res, intentos=0)
        assert status == "completado"


class TestVentanaHoraria:
    def test_ventana_diurna(self):
        ventana = lb._parse_ventana("08:00-18:00")
        assert ventana is not None
        assert lb._dentro_de_ventana(ventana, datetime.time(12, 0)) is True
        assert lb._dentro_de_ventana(ventana, datetime.time(7, 59)) is False
        assert lb._dentro_de_ventana(ventana, datetime.time(18, 0)) is False
        assert lb._dentro_de_ventana(ventana, datetime.time(20, 0)) is False

    def test_ventana_nocturna_cruce_medianoche(self):
        ventana = lb._parse_ventana("22:00-06:00")
        assert ventana is not None
        assert lb._dentro_de_ventana(ventana, datetime.time(23, 0)) is True
        assert lb._dentro_de_ventana(ventana, datetime.time(2, 30)) is True
        assert lb._dentro_de_ventana(ventana, datetime.time(5, 59)) is True
        assert lb._dentro_de_ventana(ventana, datetime.time(6, 0)) is False
        assert lb._dentro_de_ventana(ventana, datetime.time(15, 0)) is False

    def test_ventana_invalida_falla_cerrado(self):
        with pytest.raises(ValueError):
            lb._parse_ventana("invalid-format")


class TestCambioDeteccion:
    def test_tiene_stock_cambio(self):
        assert lw._tiene_stock_cambio({"delta": 5, "nueva_existencia": 15}) is True
        assert lw._tiene_stock_cambio({"delta": 0, "nueva_existencia": 10}) is False
        assert lw._tiene_stock_cambio({"delta": None, "nueva_existencia": 10}) is False

    def test_tiene_precio_cambio(self):
        assert lw._tiene_precio_cambio({"precio_actual": 10.0, "nuevo_precio": 12.0}) is True
        assert lw._tiene_precio_cambio({"precio_actual": 10.0, "nuevo_precio": 10.0}) is False
        assert lw._tiene_precio_cambio({"precio_actual": None, "nuevo_precio": 12.0}) is False

    def test_tiene_metadata_cambio(self):
        assert lw._tiene_metadata_cambio({"nueva_descripcion": "Nuevo nombre"}) is True
        assert lw._tiene_metadata_cambio({"nueva_referencia": "REF-99"}) is True
        assert lw._tiene_metadata_cambio({"nueva_descripcion": "   ", "nueva_referencia": None}) is False


class TestPreflightGuardrail:
    def test_preflight_bloqueado_pospone_sin_control_seguro_ni_quemar_intentos(self, monkeypatch):
        import hybrid_health as hh

        monkeypatch.setattr(hh, "verificar_hybrid_listo",
                            lambda target_pid=None: (False, "diálogo modal TMessageForm", [{"motivo": "modal"}]))

        control_seguro_llamado = []
        def _fake_control_seguro(**kwargs):
            control_seguro_llamado.append(True)
            from contextlib import nullcontext
            return nullcontext()

        monkeypatch.setattr(lw, "control_seguro", _fake_control_seguro)

        actualizados = []
        monkeypatch.setattr(lw, "update_item", lambda iid, **kwargs: (actualizados.append((iid, kwargs)), True)[1])

        items = [{"id": 1, "orden_id": 100, "codigo_producto": "01", "delta": 1, "nueva_existencia": 10}]
        lw.procesar_pendientes(items)

        assert len(control_seguro_llamado) == 0
        assert len(actualizados) == 0

    def test_preflight_limpio_procede_a_control_seguro(self, monkeypatch):
        import hybrid_health as hh

        monkeypatch.setattr(hh, "verificar_hybrid_listo",
                            lambda target_pid=None: (True, "HybridLite listo", []))

        control_seguro_llamado = []
        def _fake_control_seguro(**kwargs):
            control_seguro_llamado.append(True)
            from contextlib import nullcontext
            return nullcontext()

        monkeypatch.setattr(lw, "control_seguro", _fake_control_seguro)
        monkeypatch.setattr(lw, "_procesar_pendientes_impl", lambda items, banner=None: None)

        items = [{"id": 1, "orden_id": 100, "codigo_producto": "01", "delta": 1, "nueva_existencia": 10}]
        lw.procesar_pendientes(items)

        assert len(control_seguro_llamado) == 1


