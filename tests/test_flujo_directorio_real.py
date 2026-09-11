"""tests/test_flujo_directorio_real.py — Tests unitarios para el alta de clientes y proveedores.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hybrid_writeback")))
import flujo_directorio_real as fdr
import read_db_directorio as rdb


def test_codigo_desde_rif():
    assert rdb.codigo_desde_rif("J-31440341-9") == "J314403419"
    assert rdb.codigo_desde_rif("V-12.345.678") == "V12345678"
    assert rdb.codigo_desde_rif("  E-82194012  ") == "E82194012"
    assert rdb.codigo_desde_rif("") == ""


def test_norm_strings():
    assert rdb._norm("  juan   carlos   perez  ") == "JUAN CARLOS PEREZ"
    assert rdb._norm_rif("J - 12345678 - 9") == "J123456789"


class DummyControl:
    def __init__(self, top, left, text=""):
        self._top = top
        self._left = left
        self._text = text

    def rectangle(self):
        class Rect:
            def __init__(self, t, l):
                self.top = t
                self.left = l
        return Rect(self._top, self._left)

    def window_text(self):
        return self._text


def test_localizar_campos_single_pass(monkeypatch):
    """Verifica que _localizar_campos encuentre los controles por tops en una sola pasada."""
    fake_edits = [
        DummyControl(top=162, left=40),   # top~160: codigo
        DummyControl(top=199, left=42),   # top~198: nombre
        DummyControl(top=346, left=38),   # top~345: rif
        DummyControl(top=346, left=250),  # columna derecha (left > LEFT_MAX), debe ignorarse
    ]

    class FakeForm:
        def descendants(self, class_name):
            assert class_name == "THybridEdit"
            return fake_edits

    monkeypatch.setattr(fdr.fp, "_win", lambda h: FakeForm())
    monkeypatch.setattr(fdr.win32gui, "GetWindowRect", lambda h: (0, 0, 800, 600))

    tops = {"codigo": 160, "nombre": 198, "rif": 345}
    controles = fdr._localizar_campos(1234, tops)

    assert controles["codigo"] is fake_edits[0]
    assert controles["nombre"] is fake_edits[1]
    assert controles["rif"] is fake_edits[2]


def test_responder_inmediato_si_no_hay_dialogo(monkeypatch):
    """Verifica que _responder retorne False rapidamente cuando no hay dialogo."""
    monkeypatch.setattr(fdr.fp, "_find_hwnd", lambda cls: None)
    import time
    t0 = time.time()
    res = fdr._responder(["Aceptar"], timeout=0.1)
    duracion = time.time() - t0

    assert res is False
    assert duracion < 0.25


def test_existe_codigo_db_mock(monkeypatch):
    """Verifica la logica optimizada de existe_codigo con pydbisam mockeado."""
    class FakeDB:
        def fields(self):
            return ["CLT_CODIGO", "CLT_DESCRIPCION", "CLT_RIF"]

        def rows(self):
            return [
                ["V11111111", "PEDRO", "V-11111111"],
                ["J222222220", "EMPRESA X", "J-22222222-0"],
            ]

    monkeypatch.setattr(rdb.pydbisam, "PyDBISAM", lambda path: FakeDB())

    assert rdb.existe_codigo("cliente", "V-11111111") is True
    assert rdb.existe_codigo("cliente", "J-22222222-0") is True
    assert rdb.existe_codigo("cliente", "V-99999999") is False


def test_verificar_directorio_db_mock(monkeypatch):
    """Verifica la logica optimizada de verificar con pydbisam mockeado."""
    class FakeDB:
        def fields(self):
            return ["CLT_CODIGO", "CLT_DESCRIPCION", "CLT_RIF", "BASE_AUTOINCREMENT"]

        def rows(self):
            return [
                ["V11111111", "PEDRO PEREZ", "V-11111111", 10],
                ["V22222222", "PEDRO PEREZ", "V-22222222", 15],
            ]

    monkeypatch.setattr(rdb.pydbisam, "PyDBISAM", lambda path: FakeDB())

    ok, cod, det = rdb.verificar("cliente", "PEDRO PEREZ", "V-22222222")
    assert ok is True
    assert cod == "V22222222"
    assert "VERIFICADA en DB" in det
