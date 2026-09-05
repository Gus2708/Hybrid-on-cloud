"""test_flujo_pedido_real.py — Tests unitarios y de regresión para flujo_pedido_real y listener_pedidos.

Cubre:
  1. Parseo de ítems con y sin precio manual.
  2. Resolución de alias de proveedores en pedidos.
  3. Detección de duplicados post-alias (prevención de colisiones en el mismo documento).
  4. Pre-vuelo de colisiones código vs referencia (SinClaveSegura -> aborto fail-closed).
  5. Carga de ítems con clave segura (código vs código de barras / referencia).
  6. Comportamiento inmediato de _confirmar_lo_que_pregunte si no hay diálogo.
  7. Tolerancia de precio (0.01 exacto) y verificación contra DBISAM (_evaluar_pedido_db).
  8. Resiliencia de lectura SMB con reintentos en _verificar_pedido_db.
  9. Verificación en pantalla (_verificar_producto_cargado) con clave alternativa.
 10. Integración con listener_pedidos.get_items() y resolución de alias.
"""
import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hybrid_writeback")))
import flujo_pedido_real as fpr
import listener_pedidos as lp
import alias_manager as am
import colisiones


# ─── 1. Parseo de Ítems ───────────────────────────────────────────────────────
def test_parse_items_sin_precio():
    spec = "01404:2,03618:1.5"
    items = fpr._parse_items(spec)
    assert len(items) == 2
    assert items[0] == {"codigo": "01404", "cantidad": 2.0, "precio": None}
    assert items[1] == {"codigo": "03618", "cantidad": 1.5, "precio": None}


def test_parse_items_con_precio_manual():
    spec = "01404:2:15.50, 03618:1:4.00"
    items = fpr._parse_items(spec)
    assert len(items) == 2
    assert items[0] == {"codigo": "01404", "cantidad": 2.0, "precio": 15.50}
    assert items[1] == {"codigo": "03618", "cantidad": 1.0, "precio": 4.00}


def test_parse_items_invalidos():
    with pytest.raises(ValueError, match="Ítem inválido"):
        fpr._parse_items("01404")

    with pytest.raises(ValueError, match="código vacío"):
        fpr._parse_items(":2")

    with pytest.raises(ValueError):
        fpr._parse_items("01404:no_numero")


# ─── 2. Tolerancia de Precio y Constantes ──────────────────────────────────────
def test_constante_tolerancia_precio():
    """TOL_PRECIO debe ser exactamente 0.01 (1 centavo)."""
    assert fpr.TOL_PRECIO == 0.01


# ─── 3. Comportamiento Inmediato de _confirmar_lo_que_pregunte ────────────────
def test_confirmar_inmediato_si_no_hay(monkeypatch):
    """Si no hay ventana de diálogo y se pasa inmediato_si_no_hay=True,
    debe retornar False de inmediato sin esperar el timeout."""
    monkeypatch.setattr(fpr.fp, "_find_hwnd", lambda cls: 0)

    t0 = time.time()
    res = fpr._confirmar_lo_que_pregunte(timeout=3.0, inmediato_si_no_hay=True)
    dt = time.time() - t0

    assert res is False
    assert dt < 0.1, f"Tardó {dt:.3f}s; debía retornar casi instantáneo."


# ─── 4. Verificación en Pantalla: Código vs Clave de Búsqueda ─────────────────
def test_verificar_producto_cargado_acepta_codigo_o_clave(monkeypatch):
    """_verificar_producto_cargado debe aceptar que la celda contenga
    el código principal o la referencia tecleada para evitar colisión."""
    # Simular celda con el código principal
    monkeypatch.setattr(fpr, "_fila_activa", lambda h: (100, {"codigo": "01404", "descripcion": "PRODUCTO A"}))
    fpr._verificar_producto_cargado(1234, "01404", clave_busqueda="7453014040001")

    # Simular celda con la referencia tecleada (código de barras)
    monkeypatch.setattr(fpr, "_fila_activa", lambda h: (100, {"codigo": "7453014040001", "descripcion": "PRODUCTO A"}))
    fpr._verificar_producto_cargado(1234, "01404", clave_busqueda="7453014040001")

    # Si la celda contiene otro producto diferente, debe lanzar PedidoError
    monkeypatch.setattr(fpr, "_fila_activa", lambda h: (100, {"codigo": "99999", "descripcion": "OTRO PRODUCTO"}))
    with pytest.raises(fpr.PedidoError, match="no llegó a la grilla"):
        fpr._verificar_producto_cargado(1234, "01404", clave_busqueda="7453014040001")

    # Si la celda no tiene descripción, debe lanzar PedidoError
    monkeypatch.setattr(fpr, "_fila_activa", lambda h: (100, {"codigo": "01404", "descripcion": ""}))
    with pytest.raises(fpr.PedidoError, match="quedó sin descripción"):
        fpr._verificar_producto_cargado(1234, "01404", clave_busqueda="7453014040001")


# ─── 5. Evaluación de Pedido en DBISAM (_evaluar_pedido_db) ───────────────────
def test_evaluar_pedido_db_exitoso():
    header = {
        "THT_DOCUMENTO": "00005001",
        "THT_RIFCLIENTE": "V12345678",
        "THT_PERSONACONTACTO": "CLIENTE DE PRUEBA",
        "THT_FACTORREFERENCIAL": 36.50,
        "THT_STATUS": 4,
    }
    detalle = [
        {"TBT_CODIGO": "01404", "TBT_CANTIDAD": 2.0, "TBT_PRECIODEVENTA": 36.50 * 10.0},  # $10.00
        {"TBT_CODIGO": "03618", "TBT_CANTIDAD": 1.0, "TBT_PRECIODEVENTA": 36.50 * 5.0},   # $5.00
    ]
    items = [
        {"codigo": "01404", "cantidad": 2.0, "precio": 10.00},
        {"codigo": "03618", "cantidad": 1.0, "precio": None},  # precio maestro
    ]

    ok, msg, doc = fpr._evaluar_pedido_db(header, detalle, "V12345678", items, cliente_nombre="CLIENTE DE PRUEBA")
    assert ok is True
    assert doc == "00005001"
    assert "VERIFICADO" in msg


def test_evaluar_pedido_db_descuadre_cantidad():
    header = {
        "THT_DOCUMENTO": "00005002",
        "THT_RIFCLIENTE": "V12345678",
        "THT_PERSONACONTACTO": "CLIENTE",
        "THT_FACTORREFERENCIAL": 36.50,
    }
    detalle = [
        {"TBT_CODIGO": "01404", "TBT_CANTIDAD": 1.0, "TBT_PRECIODEVENTA": 365.0},
    ]
    items = [{"codigo": "01404", "cantidad": 2.0, "precio": None}]

    ok, msg, doc = fpr._evaluar_pedido_db(header, detalle, "V12345678", items)
    assert ok is False
    assert "cantidad en DB=1.0, esperaba 2.0" in msg


def test_evaluar_pedido_db_descuadre_precio():
    header = {
        "THT_DOCUMENTO": "00005003",
        "THT_RIFCLIENTE": "V12345678",
        "THT_PERSONACONTACTO": "CLIENTE",
        "THT_FACTORREFERENCIAL": 10.0,
    }
    detalle = [
        {"TBT_CODIGO": "01404", "TBT_CANTIDAD": 1.0, "TBT_PRECIODEVENTA": 100.0},  # $10.00 en USD
    ]
    # Se esperaba $10.05 (diferencia 5 centavos > TOL_PRECIO=0.01)
    items = [{"codigo": "01404", "cantidad": 1.0, "precio": 10.05}]

    ok, msg, doc = fpr._evaluar_pedido_db(header, detalle, "V12345678", items)
    assert ok is False
    assert "precio en DB=$10.00, esperaba $10.05" in msg


def test_evaluar_pedido_db_tolerancia_precio_un_centavo():
    """Diferencia de <= 0.01 sí debe ser aceptada."""
    header = {
        "THT_DOCUMENTO": "00005004",
        "THT_RIFCLIENTE": "V12345678",
        "THT_PERSONACONTACTO": "CLIENTE",
        "THT_FACTORREFERENCIAL": 100.0,
    }
    # En DB: 1000.0 / 100.0 = $10.00. Esperado: $10.01. abs diff = 0.01 <= 0.01
    detalle = [
        {"TBT_CODIGO": "01404", "TBT_CANTIDAD": 1.0, "TBT_PRECIODEVENTA": 1000.0},
    ]
    items = [{"codigo": "01404", "cantidad": 1.0, "precio": 10.01}]

    ok, msg, doc = fpr._evaluar_pedido_db(header, detalle, "V12345678", items)
    assert ok is True


# ─── 6. Reintentos SMB en _verificar_pedido_db ────────────────────────────────
def test_verificar_pedido_db_reintenta_y_recupera(monkeypatch):
    """Simula que el archivo DBISAM en H: tarda en hacer flush y arroja None
    en el 1er intento, pero aparece en el 2do intento."""
    llamadas = 0

    header = {
        "THT_DOCUMENTO": "00005005",
        "THT_RIFCLIENTE": "V12345678",
        "THT_PERSONACONTACTO": "CLIENTE",
        "THT_FACTORREFERENCIAL": 1.0,
    }
    detalle = [{"TBT_CODIGO": "01404", "TBT_CANTIDAD": 1.0, "TBT_PRECIODEVENTA": 5.0}]

    def fake_ultimo():
        nonlocal llamadas
        llamadas += 1
        if llamadas == 1:
            return None, []
        return header, detalle

    monkeypatch.setattr(fpr, "_ultimo_pedido_db", fake_ultimo)
    monkeypatch.setattr(time, "sleep", lambda s: None)  # no demorar el test

    items = [{"codigo": "01404", "cantidad": 1.0, "precio": None}]
    ok, msg, doc = fpr._verificar_pedido_db("V12345678", items, max_intentos=3)

    assert llamadas == 2
    assert ok is True
    assert doc == "00005005"


# ─── 7. Pre-vuelo de Colisiones y Alias en registrar_pedido ───────────────────
def test_registrar_pedido_resuelve_alias_y_detecta_duplicados(monkeypatch):
    """Si dos ítems vienen con códigos distintos pero uno es alias del otro,
    la resolución de alias los unifica y el detector de duplicados debe
    abortar ANTES de tocar nada."""
    monkeypatch.setattr(am, "resolver_alias", lambda cod: "THINNER-M" if cod == "THINNER-01" else cod)

    items = [
        {"codigo": "THINNER-01", "cantidad": 1.0, "precio": None},
        {"codigo": "THINNER-M", "cantidad": 2.0, "precio": None},
    ]

    res = fpr.registrar_pedido("V12345678", items, commit=False)
    assert res["ok"] is False
    assert res["etapa"] == "navegacion"
    assert "Códigos duplicados" in res["detalle"]
    assert "thinner-m" in res["detalle"]


def test_registrar_pedido_aborto_fail_closed_por_colision(monkeypatch):
    """Si un producto tiene colisión y no tiene clave segura (SinClaveSegura),
    registrar_pedido debe abortar en etapa 'navegacion' sin abrir Hybrid."""
    monkeypatch.setattr(am, "resolver_alias", lambda cod: cod)

    def fake_revisar_lote(codigos):
        return {}, {"09999": "El código '09999' está interceptado sin salida segura"}

    monkeypatch.setattr(colisiones, "revisar_lote", fake_revisar_lote)

    items = [{"codigo": "09999", "cantidad": 1.0, "precio": None}]
    res = fpr.registrar_pedido("V12345678", items, commit=False)

    assert res["ok"] is False
    assert res["etapa"] == "navegacion"
    assert "sin clave de búsqueda segura" in res["detalle"]
    assert "09999" in res["detalle"]


# ─── 8. listener_pedidos: get_items() Resuelve Alias ─────────────────────────
def test_listener_pedidos_get_items_aplica_alias(monkeypatch):
    """listener_pedidos.get_items debe traducir el código_producto según los alias."""
    monkeypatch.setattr(lp.lb, "rest", lambda method, path: [
        {"codigo_producto": "THINNER-01", "descripcion": "THINNER", "cantidad": 5.0, "precio": 3.50},
        {"codigo_producto": "01404", "descripcion": "BROCHA", "cantidad": 2.0, "precio": None},
    ])
    monkeypatch.setattr(am, "resolver_alias", lambda cod: "THINNER-M" if cod == "THINNER-01" else cod)

    items = lp.get_items(999)
    assert len(items) == 2
    assert items[0] == {"codigo": "THINNER-M", "cantidad": 5.0, "precio": 3.50}
    assert items[1] == {"codigo": "01404", "cantidad": 2.0, "precio": None}