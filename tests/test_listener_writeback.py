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
