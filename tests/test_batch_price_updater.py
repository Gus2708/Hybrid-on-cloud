"""Tests de batch_price_updater: extracción segura de precios/costos, checkpoints y prefiltrado.
"""
import os
import sys
import json
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hybrid_writeback")))
from batch_price_updater import BatchPriceUpdater


@pytest.fixture
def updater(tmp_path):
    log_f = str(tmp_path / "test.log")
    ckpt_f = str(tmp_path / "test_ckpt.json")
    return BatchPriceUpdater(log_path=log_f, checkpoint_path=ckpt_f)


# ─── Extracción segura de precios (REGRESIÓN CRÍTICA: Precios en 0) ─────────
def test_extraer_precio_distintas_claves():
    assert BatchPriceUpdater._extraer_precio({"precio": 15.5}) == 15.5
    assert BatchPriceUpdater._extraer_precio({"precio_nuevo": 20.0}) == 20.0
    assert BatchPriceUpdater._extraer_precio({"precio_venta": 7.0}) == 7.0
    assert BatchPriceUpdater._extraer_precio({"precio_venta_sugerido_25": 10.0}) == 10.0
    assert BatchPriceUpdater._extraer_precio({"precio_venta_sugerido_35": 12.0}) == 12.0
    assert BatchPriceUpdater._extraer_precio({"pvp": 25.0}) == 25.0
    assert BatchPriceUpdater._extraer_precio({"pvp_con_impuesto": 30.0}) == 30.0
    assert BatchPriceUpdater._extraer_precio({"precio": "14.50"}) == 14.5


def test_extraer_precio_rechaza_cero_o_negativo():
    """REGRESIÓN: Nunca debe aceptar 0, '0', 0.0 o negativos como precio válido."""
    assert BatchPriceUpdater._extraer_precio({"precio": 0}) is None
    assert BatchPriceUpdater._extraer_precio({"precio": 0.0}) is None
    assert BatchPriceUpdater._extraer_precio({"precio": "0"}) is None
    assert BatchPriceUpdater._extraer_precio({"precio": "0.00"}) is None
    assert BatchPriceUpdater._extraer_precio({"precio": -10.0}) is None
    assert BatchPriceUpdater._extraer_precio({"precio": ""}) is None
    assert BatchPriceUpdater._extraer_precio({"precio": None}) is None
    assert BatchPriceUpdater._extraer_precio({}) is None
    assert BatchPriceUpdater._extraer_precio({"otro_campo": 15.0}) is None


# ─── Extracción segura de costos ─────────────────────────────────────────────
def test_extraer_costo_distintas_claves():
    assert BatchPriceUpdater._extraer_costo({"costo": 8.5}) == 8.5
    assert BatchPriceUpdater._extraer_costo({"nuevo_costo": 12.0}) == 12.0
    assert BatchPriceUpdater._extraer_costo({"costo_nuevo": 14.0}) == 14.0
    assert BatchPriceUpdater._extraer_costo({"costo_unitario": 5.57}) == 5.57
    assert BatchPriceUpdater._extraer_costo({"costo_usd": 18.55}) == 18.55
    assert BatchPriceUpdater._extraer_costo({"costo": "8.50"}) == 8.5


def test_extraer_costo_rechaza_cero_o_negativo():
    assert BatchPriceUpdater._extraer_costo({"costo": 0}) is None
    assert BatchPriceUpdater._extraer_costo({"costo": 0.0}) is None
    assert BatchPriceUpdater._extraer_costo({"costo": "-5.0"}) is None
    assert BatchPriceUpdater._extraer_costo({"costo": ""}) is None
    assert BatchPriceUpdater._extraer_costo({}) is None


# ─── Checkpoints: Persistencia y Recuperación ────────────────────────────────
def test_checkpoint_vacio_al_inicio(updater):
    ckpt = updater._cargar_checkpoint()
    assert ckpt["completados"] == []
    assert ckpt["fallidos"] == {}
    assert ckpt["ultimo_indice"] == 0


def test_guardar_y_cargar_checkpoint(updater):
    data = {
        "completados": ["F-401-01", "F-402-01"],
        "fallidos": {"F-999-99": "Error de prueba"},
        "ultimo_indice": 2
    }
    updater._guardar_checkpoint(data)
    
    leido = updater._cargar_checkpoint()
    assert leido["completados"] == ["F-401-01", "F-402-01"]
    assert leido["fallidos"] == {"F-999-99": "Error de prueba"}
    assert leido["ultimo_indice"] == 2


# ─── Prefiltrado DBISAM ──────────────────────────────────────────────────────
def test_prefiltrado_omite_items_al_dia(updater, monkeypatch):
    """Si la base de datos ya tiene el precio y costo meta, el lote NO debe tocarlos."""
    items = [
        {"codigo": "F-401-01", "precio": 7.0, "costo": 5.57},
        {"codigo": "F-402-01", "precio": 7.0, "costo": 5.57}
    ]
    # Simular que DBISAM ya tiene exactamente esos valores
    monkeypatch.setattr("hybrid_price_writer._db_valores_usd_batch", 
                        lambda cods: {"F-401-01": (7.0, 5.57), "F-402-01": (7.0, 5.57)})

    res = updater.procesar_lote(items, commit=False)
    assert res["ok"] is True
    assert res["actualizados"] == 0
    assert res["ya_al_dia"] == 2
    assert res["total"] == 2


def test_prefiltrado_detecta_items_con_diferencias(updater, monkeypatch):
    """Si DBISAM difiere en precio o costo, debe enviarse a pendientes."""
    items = [
        {"codigo": "F-401-01", "precio": 7.0, "costo": 5.57},
        {"codigo": "F-401-04", "precio": 24.0, "costo": 18.55}
    ]
    # F-401-01 ya está al día, pero F-401-04 difiere en precio (está en 20.0)
    monkeypatch.setattr("hybrid_price_writer._db_valores_usd_batch", 
                        lambda cods: {"F-401-01": (7.0, 5.57), "F-401-04": (20.0, 18.55)})

    # Mock de Ficha para que no intente automatizar ventanas reales en este test unitario
    monkeypatch.setattr("flujo_compra_real._salir_compras", lambda: None)
    monkeypatch.setattr("flujo_precio_real.abrir_ficha", lambda: 1234)
    monkeypatch.setattr("flujo_stock_real._cerrar_ficha_si_abierta", lambda: None)
    
    llamados = []
    def mock_set_precio_costo(cod, **kwargs):
        llamados.append(cod)
        return {"ok": True, "etapa": "preview"}
    monkeypatch.setattr("flujo_precio_real.set_precio_costo", mock_set_precio_costo)

    res = updater.procesar_lote(items, commit=False)
    # Solo F-401-04 debió ser procesado en UI
    assert llamados == ["F-401-04"]
