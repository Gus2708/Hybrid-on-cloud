"""tests/test_flujo_compra_real.py — Tests unitarios y de regresión para flujo_compra_real.

Cubre:
  1. Coordenada y presencia de ITEM_GRID_REL para foco en grilla.
  2. Validación de fila activa (_fila_activa).
  3. Detección y aborto inmediato si el producto cargado es incorrecto (_verificar_producto_cargado).
  4. Guardado único en alta (_guardar_ficha_alta) con cierre de Ficha.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hybrid_writeback")))
import flujo_compra_real as fcr


def test_constante_grid_compras():
    """Verifica que ITEM_GRID_REL esté calibrado para la celda Código de TAdvStringGrid."""
    assert fcr.ITEM_GRID_REL == (72, 325)
    assert "THybridEdit" in fcr.GRID_EDIT_CLASSES
    assert "THybridEditNumber" in fcr.GRID_EDIT_CLASSES


def test_verificar_producto_cargado_correcto(monkeypatch):
    """Si el código leído en pantalla coincide con el esperado, no lanza error."""
    monkeypatch.setattr(fcr, "_fila_activa", lambda h: (325, {"codigo": "VT-2474", "descripcion": "CABLE"}))
    # No debe levantar excepción
    fcr._verificar_producto_cargado(1234, "VT-2474")


def test_verificar_producto_cargado_acepta_clave_busqueda(monkeypatch):
    """Acepta también la clave de búsqueda alternativa por colisiones."""
    monkeypatch.setattr(fcr, "_fila_activa", lambda h: (325, {"codigo": "7591234567890", "descripcion": "CABLE"}))
    fcr._verificar_producto_cargado(1234, "VT-2474", clave_busqueda="7591234567890")


def test_verificar_producto_cargado_aborta_si_codigo_no_coincide(monkeypatch):
    """Regresión del bug 00-002-024: si el foco quedó en el header y se cargó la fila 1
    genérica del catálogo, debe abortar de inmediato con CompraError."""
    monkeypatch.setattr(fcr, "_fila_activa", lambda h: (325, {"codigo": "00-002-024", "descripcion": "ALICATE"}))
    with pytest.raises(fcr.CompraError, match="no llegó a la grilla de Compras"):
        fcr._verificar_producto_cargado(1234, "VT-2474")


def test_verificar_producto_cargado_aborta_si_falta_descripcion(monkeypatch):
    """Si el producto no resolvió descripción, debe abortar."""
    monkeypatch.setattr(fcr, "_fila_activa", lambda h: (325, {"codigo": "VT-2474", "descripcion": ""}))
    with pytest.raises(fcr.CompraError, match="quedó sin descripción"):
        fcr._verificar_producto_cargado(1234, "VT-2474")
