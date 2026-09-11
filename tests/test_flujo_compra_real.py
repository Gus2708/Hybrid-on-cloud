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


def test_leer_items_db_batch_exitoso(monkeypatch):
    """Verifica que _leer_items_db_batch combine existencia y precios correctamente."""
    monkeypatch.setattr(fcr.dbex, "existencia_batch", lambda cods: {
        "A": (10.0, []), "B": (20.0, [])
    })
    monkeypatch.setattr(fcr.hpw, "_db_valores_usd_batch", lambda cods: {
        "A": (100.0, 50.0), "B": (200.0, 150.0)
    })
    res = fcr._leer_items_db_batch(["A", "B"])
    assert res == {
        "A": (10.0, 50.0, 100.0),   # (existencia, costo, precio)
        "B": (20.0, 150.0, 200.0),
    }


def test_leer_items_db_batch_reintenta_y_recupera(monkeypatch):
    """Verifica resiliencia ante OSError temporal en share de red H:."""
    intentos = [0]
    monkeypatch.setattr(fcr, "ESPERA_LECTURA_DB", 0.001)

    def mock_existencia(cods):
        intentos[0] += 1
        if intentos[0] == 1:
            raise OSError("Share de red H: no accesible")
        return {"A": (5.0, [])}

    monkeypatch.setattr(fcr.dbex, "existencia_batch", mock_existencia)
    monkeypatch.setattr(fcr.hpw, "_db_valores_usd_batch", lambda cods: {"A": (10.0, 2.0)})

    res = fcr._leer_items_db_batch(["A"])
    assert res["A"] == (5.0, 2.0, 10.0)
    assert intentos[0] == 2



def test_confirmar_lo_que_pregunte_acepta_inmediato_si_no_hay(monkeypatch):
    """Regresión: cargar_item invoca _confirmar_lo_que_pregunte con el kwarg
    inmediato_si_no_hay. La firma local debe aceptarlo (antes solo existía en
    flujo_pedido_real, y el TypeError escapaba del `except CompraError` de
    registrar_compra, saltándose el cancelado todo-o-nada)."""
    import inspect

    params = inspect.signature(fcr._confirmar_lo_que_pregunte).parameters
    assert "inmediato_si_no_hay" in params
    assert params["inmediato_si_no_hay"].default is False

    monkeypatch.setattr(fcr.fp, "_find_hwnd", lambda cls: None)
    # Sin diálogo en pantalla debe volver ya mismo, sin agotar el timeout.
    assert fcr._confirmar_lo_que_pregunte(timeout=30, inmediato_si_no_hay=True) is False


def test_espera_costos_precios_no_se_recorta():
    """Recortar este presupuesto hace concluir 'ítem at-min' por impaciencia y
    saltarse el tecleo del precio, algo que la verificación contra DBISAM no
    detecta (valida existencia, no precio)."""
    assert fcr.ESPERA_COSTOS_PRECIOS >= 8


def test_guardar_ficha_alta_mantiene_ficha_abierta_si_cerrar_ficha_false(monkeypatch):
    """Verifica que _guardar_ficha_alta NO cierre la Ficha si cerrar_ficha=False."""
    clics = []
    cerrada = []
    monkeypatch.setattr(fcr.fp, "_find_hwnd", lambda cls: 5555 if cls == fcr.fp.FICHA_CLASS else None)
    monkeypatch.setattr(fcr.win32gui, "GetWindowRect", lambda hwnd: (100, 100, 900, 700))
    monkeypatch.setattr(fcr.fpr, "_focus", lambda hwnd: None)
    monkeypatch.setattr(fcr.ri, "click", lambda x, y: clics.append((x, y)))
    monkeypatch.setattr(fcr.fsr, "_cerrar_ficha_si_abierta", lambda: cerrada.append(True))
    monkeypatch.setattr("time.sleep", lambda s: None)

    # 1. Con cerrar_ficha=False -> Guarda, Cancela insert sobrante, pero NO cierra la Ficha
    fcr._guardar_ficha_alta(cerrar_ficha=False)
    assert len(clics) == 2
    assert cerrada == []

    # 2. Con cerrar_ficha=True -> Guarda, Cancela y cierra la Ficha
    fcr._guardar_ficha_alta(cerrar_ficha=True)
    assert len(clics) == 4
    assert cerrada == [True]

