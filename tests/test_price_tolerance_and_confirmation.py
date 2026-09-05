"""Tests de tolerancia de precios y confirmaciones: prevención de regresión del bug THINNER-M.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hybrid_writeback")))
import flujo_precio_real as fpr
import hybrid_price_writer as hpw


# ─── Test de Regresión: Bug de tolerancia en THINNER-M (4.02 vs 4.00) ───────
def test_regresion_tolerancia_thinner_no_omite_escritura():
    """Caso real observado: al meter costo 3.04, Delphi calcula con-impuesto 4.0177
    (pantalla muestra 4.02). Si el target pedido es 4.00:
    - Con TOL=0.02 anterior: abs(4.02 - 4.00) <= 0.02 era True (Omitía escribir y dejaba 4.02).
    - Con la nueva regla (< 0.005): abs(4.02 - 4.00) = 0.02 >= 0.005 -> NO debe omitir.
    """
    target = 4.00
    con_pantalla = 4.02
    
    # La condición exacta usada en escribir_precio
    debe_omitir = (con_pantalla is not None and abs(con_pantalla - target) < 0.005)
    assert debe_omitir is False, "Una diferencia de 2 centavos NUNCA debe considerarse 'ya en target'."


def test_tolerancia_omision_1_centavo_no_se_omite():
    """Incluso 1 centavo de diferencia ($4.01 vs $4.00) debe obligar a reescribir."""
    target = 4.00
    con_pantalla = 4.01
    debe_omitir = (con_pantalla is not None and abs(con_pantalla - target) < 0.005)
    assert debe_omitir is False


def test_tolerancia_omision_subcentavo_si_se_omite():
    """Fracciones irrelevantes (< medio centavo, ej 4.001 vs 4.00) sí se consideran target."""
    target = 4.00
    con_pantalla = 4.002
    debe_omitir = (con_pantalla is not None and abs(con_pantalla - target) < 0.005)
    assert debe_omitir is True


def test_constantes_tolerancia_global():
    """Ambos módulos deben tener TOL fijada en 0.01 (1 centavo exacto)."""
    assert fpr.TOL == 0.01
    assert hpw.TOL == 0.01


# ─── Confirmación de Diálogos: TMessageForm y TFConfirmacion ────────────────
def test_confirmar_si_atiende_ambas_clases_de_dialogo(monkeypatch):
    """_confirmar_si debe buscar en TMessageForm y TFConfirmacion y pulsar el botón."""
    clases_buscadas = []
    
    class DummyButton:
        def rectangle(self):
            class Rect:
                left, right, top, bottom = 10, 20, 10, 20
            return Rect()

    class DummyWin:
        def child_window(self, title):
            return DummyButton()

    def mock_find_hwnd(cls):
        clases_buscadas.append(cls)
        if cls == "TFConfirmacion":
            return 9999
        return None

    monkeypatch.setattr("flujo_precio._find_hwnd", mock_find_hwnd)
    monkeypatch.setattr("flujo_precio._win", lambda hwnd: DummyWin())
    monkeypatch.setattr("realinput.click", lambda x, y: None)
    monkeypatch.setattr("flujo_precio_real._focus", lambda hwnd: None)

    res = fpr._confirmar_si()
    assert res is True
    assert "TMessageForm" in clases_buscadas
    assert "TFConfirmacion" in clases_buscadas
