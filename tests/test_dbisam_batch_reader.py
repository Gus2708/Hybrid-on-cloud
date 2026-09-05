"""Tests de _db_valores_usd_batch: lectura streaming de lotes en DBISAM.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hybrid_writeback")))
import hybrid_price_writer as hpw


class MockPyDBISAM:
    def __init__(self, path):
        self.path = path

    def fields(self):
        return ["TPC_CODIGOPRODUCTO", "TPC_TIPO", "TPC_COSTOACTUAL", "TPC_PVPCONIMPUESTO1"]

    def rows(self):
        return [
            # F-401-01 en Bs (TIPO=0, debe ser ignorado)
            ["F-401-01", 0, 4828.17, 8137.37],
            # F-401-01 en USD (TIPO=1, debe ser extraído)
            ["F-401-01", 1, 5.57, 7.00],
            # F-402-01 en USD
            ["F-402-01", 1, 5.57, 7.00],
            # OTRO-01 en Bs
            ["OTRO-01", 0, 100.0, 200.0],
            # F-790-04 en USD
            ["F-790-04", 1, 23.83, 30.00],
        ]


def test_db_valores_usd_batch_extrae_tipo1(monkeypatch):
    """Debe extraer solo los registros TIPO=1 (USD) para los códigos pedidos."""
    monkeypatch.setattr("read_db_precio.pydbisam.PyDBISAM", MockPyDBISAM)

    codigos = ["F-401-01", "F-402-01", "F-790-04"]
    res = hpw._db_valores_usd_batch(codigos)

    assert len(res) == 3
    assert res["F-401-01"] == (7.00, 5.57)
    assert res["F-402-01"] == (7.00, 5.57)
    assert res["F-790-04"] == (30.00, 23.83)


def test_db_valores_usd_batch_ignora_tipo0(monkeypatch):
    """Si solo existe registro TIPO=0 (Bs), no debe extraerse como valor USD."""
    monkeypatch.setattr("read_db_precio.pydbisam.PyDBISAM", MockPyDBISAM)

    codigos = ["OTRO-01"]
    res = hpw._db_valores_usd_batch(codigos)
    assert "OTRO-01" not in res


def test_db_valores_usd_batch_codigos_inexistentes(monkeypatch):
    """Códigos que no están en la tabla no deben figurar en el dict retornado."""
    monkeypatch.setattr("read_db_precio.pydbisam.PyDBISAM", MockPyDBISAM)

    codigos = ["NO-EXISTE-99"]
    res = hpw._db_valores_usd_batch(codigos)
    assert res == {}
