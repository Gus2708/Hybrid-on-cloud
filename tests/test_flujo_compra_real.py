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


# ── Helpers para tests de es_ajuste ──────────────────────────────────────────
def _setup_mock_compra_env(monkeypatch, initial_db, *, fail_ajuste=False,
                           fail_post_ajuste_read=False, stock_inicial_alta=0.0):
    """Monta un entorno falso completo (UI + DBISAM) para probar registrar_compra."""
    import abrir_hybrid

    state = {
        "db": {k: dict(v) for k, v in initial_db.items()},
        "compras_cargadas": [],
        "ajustes_single": [],
        "ajustes_lote": [],
        "altas": [],
        "totalizado": False,
        "cancelado": False,
    }

    monkeypatch.setattr(abrir_hybrid, "asegurar_hybrid", lambda: (True, "OK"))
    monkeypatch.setattr(fcr.hpw, "_db_precio_usd",
                        lambda cod: state["db"][cod]["precio"] if cod in state["db"] else None)

    def fake_crear_producto(codigo, descripcion, referencia, costo, precio, commit=False, cerrar_ficha=True):
        state["altas"].append((codigo, commit))
        if commit:
            state["db"][codigo] = {
                "existencia": stock_inicial_alta,
                "costo": float(costo),
                "precio": float(precio),
            }
        return {"ok": True, "etapa": "commit" if commit else "preview", "detalle": "alta ok"}

    monkeypatch.setattr(fcr, "crear_producto", fake_crear_producto)
    monkeypatch.setattr(fcr.fsr, "_cerrar_ficha_si_abierta", lambda: None)
    monkeypatch.setattr(fcr.colisiones, "revisar_lote",
                        lambda cods: ({c: c for c in cods}, {}))
    monkeypatch.setattr(fcr.dbex, "existencia_batch",
                        lambda cods: {c: (state["db"][c]["existencia"], []) for c in cods if c in state["db"]})
    monkeypatch.setattr(fcr.dbex, "existencia",
                        lambda cod: (state["db"][cod]["existencia"], []) if cod in state["db"] else (0.0, []))

    monkeypatch.setattr(fcr, "abrir_compras", lambda: 1001)
    monkeypatch.setattr(fcr.fp, "_win", lambda hwnd: object())
    monkeypatch.setattr(fcr.fp, "_find_hwnd", lambda cls: 1001 if cls == fcr.COMPRAS_CLASS else None)
    monkeypatch.setattr(fcr, "fijar_clasificacion", lambda com: None)
    monkeypatch.setattr(fcr, "seleccionar_proveedor", lambda com, cod, nom=None: None)

    def fake_cargar_item(codigo, cantidad, costo, precio, commit, es_primero=False, clave_busqueda=None):
        state["compras_cargadas"].append({
            "codigo": codigo, "cantidad": float(cantidad),
            "costo": float(costo), "precio": float(precio), "commit": commit,
        })
        if commit:
            prod = state["db"].setdefault(codigo, {"existencia": 0.0, "costo": 0.0, "precio": 0.0})
            prod["existencia"] += float(cantidad)
            prod["costo"] = float(costo)
            prod["precio"] = float(precio)

    monkeypatch.setattr(fcr, "cargar_item", fake_cargar_item)
    monkeypatch.setattr(fcr, "_cancelar_compra", lambda h: state.__setitem__("cancelado", True))
    monkeypatch.setattr(fcr, "_salir_compras", lambda: None)
    monkeypatch.setattr(fcr, "_totalizar_compra", lambda h, doc: state.__setitem__("totalizado", True) or True)
    monkeypatch.setattr("time.sleep", lambda s: None)

    lecturas = [0]

    def fake_leer_items_db_batch(cods):
        lecturas[0] += 1
        if fail_post_ajuste_read and lecturas[0] >= 2:
            raise fcr.VerificacionIndisponible("H: no responde tras ajuste")
        return {
            c: (
                state["db"][c]["existencia"],
                state["db"][c]["costo"],
                state["db"][c]["precio"],
            )
            for c in cods
        }

    monkeypatch.setattr(fcr, "_leer_items_db_batch", fake_leer_items_db_batch)

    def fake_ajustar_stock(codigo, cantidad, commit=False, delta=False, codigo_esperado=None):
        objetivo = codigo_esperado or codigo
        state["ajustes_single"].append({
            "codigo": codigo, "cantidad": float(cantidad),
            "commit": commit, "delta": delta, "codigo_esperado": objetivo,
        })
        if fail_ajuste:
            return {"ok": False, "etapa": "carga/conteo", "detalle": "error simulado en Ajustes"}
        target = state["db"][objetivo]["existencia"] + float(cantidad) if delta else float(cantidad)
        if commit:
            state["db"][objetivo]["existencia"] = target
        return {
            "ok": True,
            "etapa": "commit" if commit else "preview",
            "detalle": f"Stock {'ajustado' if commit else 'preview'}={target}",
        }

    def fake_ajustar_stock_lote(items_lote, commit=False):
        state["ajustes_lote"].append({"items": list(items_lote), "commit": commit})
        if fail_ajuste:
            return {
                "ok": False,
                "etapa": "carga/conteo",
                "detalle": "error simulado en lote de Ajustes",
                "resultados": {
                    it["item_id"]: {"ok": False, "etapa": "carga/conteo", "detalle": "fallo"}
                    for it in items_lote
                },
            }
        resultados = {}
        for it in items_lote:
            cod_real = it.get("codigo_esperado") or it["codigo"]
            target = (
                float(it["target"])
                if it.get("target") is not None
                else state["db"][cod_real]["existencia"] + float(it["delta"])
            )
            if commit:
                state["db"][cod_real]["existencia"] = target
            resultados[it["item_id"]] = {
                "ok": True,
                "etapa": "commit" if commit else "preview",
                "detalle": f"target={target}",
            }
        return {
            "ok": True,
            "etapa": "commit" if commit else "preview",
            "detalle": "lote ok",
            "resultados": resultados,
        }

    monkeypatch.setattr(fcr.fsr, "ajustar_stock", fake_ajustar_stock)
    monkeypatch.setattr(fcr.fsr, "ajustar_stock_lote", fake_ajustar_stock_lote)
    return state


# ── Tests unitarios para cálculo de deltas/secuencia (es_ajuste) ──────────────
class TestCalculoAjusteExistencia:
    def test_es_ajuste_false_mantiene_comportamiento_aditivo(self):
        item = {"codigo": "A", "cantidad": 5.0, "es_ajuste": False}
        assert fcr.calcular_existencia_esperada(item, 10.0) == 15.0
        info = fcr.calcular_ajuste_item(item, 10.0, existencia_post_compra=15.0)
        assert info["requiere_ajuste"] is False
        assert info["delta"] == 0.0
        assert info["target"] == 15.0

    def test_es_ajuste_true_stock_previo_positivo(self):
        """Stock previo=10, compra por cantidad=5 -> post-compra=15 -> delta=-10 -> target=5."""
        item = {"codigo": "POS", "cantidad": 5.0, "es_ajuste": True, "es_nuevo": False}
        assert fcr.calcular_existencia_esperada(item, 10.0) == 5.0

        # Proyección pre-compra (preview)
        info_prev = fcr.calcular_ajuste_item(item, 10.0)
        assert info_prev["requiere_ajuste"] is True
        assert info_prev["existencia_base"] == 15.0
        assert info_prev["delta"] == -10.0
        assert info_prev["target"] == 5.0

        # Cálculo real post-compra (commit)
        info_post = fcr.calcular_ajuste_item(item, 10.0, existencia_post_compra=15.0)
        assert info_post["requiere_ajuste"] is True
        assert info_post["delta"] == -10.0
        assert info_post["target"] == 5.0

    def test_es_ajuste_true_stock_previo_negativo(self):
        """Stock previo=-3, compra por cantidad=5 -> post-compra=2 -> delta=+3 -> target=5."""
        item = {"codigo": "NEG", "cantidad": 5.0, "es_ajuste": True, "es_nuevo": False}
        assert fcr.calcular_existencia_esperada(item, -3.0) == 5.0
        info = fcr.calcular_ajuste_item(item, -3.0, existencia_post_compra=2.0)
        assert info["requiere_ajuste"] is True
        assert info["delta"] == 3.0
        assert info["target"] == 5.0

    def test_es_ajuste_true_stock_previo_cero_no_requiere_ajuste(self):
        """Stock previo=0, compra por cantidad=5 -> post-compra=5 -> delta=0 -> no abre Ajustes."""
        item = {"codigo": "CERO", "cantidad": 5.0, "es_ajuste": True, "es_nuevo": False}
        info = fcr.calcular_ajuste_item(item, 0.0, existencia_post_compra=5.0)
        assert info["requiere_ajuste"] is False
        assert info["delta"] == 0.0
        assert info["target"] == 5.0
        assert info["motivo"] == "ya_en_target"

    def test_es_ajuste_true_es_nuevo_arranca_en_cero_vs_desviado(self):
        """es_nuevo=True arrancando en 0 no requiere ajuste; si no arrancó en 0 sí ajusta."""
        item = {"codigo": "NEW", "cantidad": 5.0, "es_ajuste": True, "es_nuevo": True}
        info_ok = fcr.calcular_ajuste_item(item, 0.0, existencia_post_compra=5.0)
        assert info_ok["requiere_ajuste"] is False
        assert info_ok["delta"] == 0.0

        # Si por algún motivo previo no arrancó en 0 (ej. quedó en 3 antes -> post=8)
        info_fix = fcr.calcular_ajuste_item(item, 3.0, existencia_post_compra=8.0)
        assert info_fix["requiere_ajuste"] is True
        assert info_fix["delta"] == -3.0
        assert info_fix["target"] == 5.0

    def test_armar_lote_ajustes_compra_filtra_y_preserva_claves(self):
        items = [
            {"codigo": "NORM", "cantidad": 4.0, "es_ajuste": False},
            {"codigo": "CERO", "cantidad": 5.0, "es_ajuste": True},
            {"codigo": "POS", "cantidad": 5.0, "es_ajuste": True},
            {"codigo": "NEG", "cantidad": 5.0, "es_ajuste": True},
        ]
        ex_antes = {"NORM": 2.0, "CERO": 0.0, "POS": 10.0, "NEG": -3.0}
        ex_post = {"NORM": 6.0, "CERO": 5.0, "POS": 15.0, "NEG": 2.0}
        claves = {"POS": "759000111", "NEG": "NEG"}

        lote, errores = fcr.armar_lote_ajustes_compra(
            items, ex_antes, existencias_post_compra=ex_post, claves_busqueda=claves
        )
        assert errores == {}
        assert [x["codigo_esperado"] for x in lote] == ["POS", "NEG"]
        assert lote[0]["codigo"] == "759000111"
        assert lote[0]["delta"] == -10.0
        assert lote[0]["target"] == 5.0
        assert lote[1]["delta"] == 3.0
        assert lote[1]["target"] == 5.0


class TestFlujoCompraConAjuste:
    def test_registrar_compra_commit_mixta_secuencia_y_verificacion(self, monkeypatch):
        """Compra mixta: normal + stock previo positivo + negativo + cero + es_nuevo (0 y !=0)."""
        state = _setup_mock_compra_env(
            monkeypatch,
            initial_db={
                "NORM": {"existencia": 2.0, "costo": 1.0, "precio": 2.0},
                "POS": {"existencia": 10.0, "costo": 3.0, "precio": 5.0},
                "NEG": {"existencia": -3.0, "costo": 4.0, "precio": 6.0},
                "CERO": {"existencia": 0.0, "costo": 2.0, "precio": 3.0},
            },
            stock_inicial_alta=0.0,
        )
        items = [
            {"codigo": "NORM", "cantidad": 4.0, "costo": 1.2, "precio": 2.5, "es_ajuste": False},
            {"codigo": "POS", "cantidad": 5.0, "costo": 3.5, "precio": 5.5, "es_ajuste": True},
            {"codigo": "NEG", "cantidad": 5.0, "costo": 4.1, "precio": 6.5, "es_ajuste": True},
            {"codigo": "CERO", "cantidad": 5.0, "costo": 2.2, "precio": 3.5, "es_ajuste": True},
            {"codigo": "NEW", "cantidad": 5.0, "costo": 7.0, "precio": 10.0,
             "es_nuevo": True, "es_ajuste": True, "descripcion": "PRODUCTO NUEVO"},
        ]

        res = fcr.registrar_compra("PROV1", items, "1001", commit=True)

        assert res["ok"] is True
        assert res["etapa"] == "commit"
        assert state["totalizado"] is True
        # Todas las líneas se compraron por su cantidad exacta con costo/precio reales
        assert [(c["codigo"], c["cantidad"]) for c in state["compras_cargadas"]] == [
            ("NORM", 4.0), ("POS", 5.0), ("NEG", 5.0), ("CERO", 5.0), ("NEW", 5.0),
        ]
        # Solo POS y NEG necesitaron Ajustes de Inventario (CERO y NEW quedaron ya en 5.0)
        assert len(state["ajustes_lote"]) == 1
        lote = state["ajustes_lote"][0]["items"]
        assert [(it["codigo_esperado"], it["target"], it["delta"]) for it in lote] == [
            ("POS", 5.0, -10.0),
            ("NEG", 5.0, 3.0),
        ]
        # Existencias, costos y precios finales exactos en DBISAM
        assert state["db"]["NORM"]["existencia"] == 6.0
        assert state["db"]["POS"] == {"existencia": 5.0, "costo": 3.5, "precio": 5.5}
        assert state["db"]["NEG"] == {"existencia": 5.0, "costo": 4.1, "precio": 6.5}
        assert state["db"]["CERO"] == {"existencia": 5.0, "costo": 2.2, "precio": 3.5}
        assert state["db"]["NEW"] == {"existencia": 5.0, "costo": 7.0, "precio": 10.0}
        assert "[es_ajuste] VERIFICADO" in res["resultados"]["POS"]["detalle"]
        assert "[alta_producto] [es_ajuste] VERIFICADO" in res["resultados"]["NEW"]["detalle"]

    def test_registrar_compra_es_nuevo_no_arranca_en_cero_corrige_en_ajustes(self, monkeypatch):
        """Si un ítem es_nuevo=True y es_ajuste=True no arrancó en 0, se corrige al target."""
        state = _setup_mock_compra_env(
            monkeypatch,
            initial_db={},
            stock_inicial_alta=3.0,  # anomalía simulada: no arrancó en 0
        )
        items = [
            {"codigo": "NEWX", "cantidad": 5.0, "costo": 7.0, "precio": 10.0,
             "es_nuevo": True, "es_ajuste": True, "descripcion": "NUEVO CON ANOMALIA"},
        ]

        res = fcr.registrar_compra("PROV1", items, "1002", commit=True)

        assert res["ok"] is True
        assert res["etapa"] == "commit"
        assert len(state["ajustes_single"]) == 1
        assert state["ajustes_single"][0]["codigo_esperado"] == "NEWX"
        assert state["ajustes_single"][0]["cantidad"] == 5.0
        assert state["ajustes_single"][0]["delta"] is False
        assert state["db"]["NEWX"]["existencia"] == 5.0

    def test_registrar_compra_preview_valida_compras_y_ajustes_sin_guardar(self, monkeypatch):
        state = _setup_mock_compra_env(
            monkeypatch,
            initial_db={"POS": {"existencia": 10.0, "costo": 3.0, "precio": 5.0}},
        )
        items = [
            {"codigo": "POS", "cantidad": 5.0, "costo": 3.5, "precio": 5.5, "es_ajuste": True},
        ]

        res = fcr.registrar_compra("PROV1", items, "1003", commit=False)

        assert res["ok"] is True
        assert res["etapa"] == "preview"
        assert state["cancelado"] is True
        assert state["totalizado"] is False
        assert len(state["ajustes_single"]) == 1
        assert state["ajustes_single"][0]["commit"] is False
        assert state["ajustes_single"][0]["cantidad"] == 5.0
        assert state["db"]["POS"]["existencia"] == 10.0

    def test_fallo_ajuste_post_compra_retorna_etapa_no_reintentable(self, monkeypatch):
        import listener_compras as lc

        _setup_mock_compra_env(
            monkeypatch,
            initial_db={"POS": {"existencia": 10.0, "costo": 3.0, "precio": 5.0}},
            fail_ajuste=True,
        )
        items = [
            {"codigo": "POS", "cantidad": 5.0, "costo": 3.5, "precio": 5.5, "es_ajuste": True},
        ]

        res = fcr.registrar_compra("PROV1", items, "1004", commit=True)
        assert res["ok"] is False
        assert res["etapa"] == "ajuste_inventario:carga/conteo"

        monkeypatch.setattr(lc.lb, "check_hybrid_write_enabled", lambda: True)
        status, detalle = lc._politica_resultado(res, intentos=1)
        assert status == "error"
        assert "NO reencolar" in detalle

    def test_verificacion_indisponible_post_ajuste_marca_error_sin_doble_aviso(self, monkeypatch):
        import listener_compras as lc

        _setup_mock_compra_env(
            monkeypatch,
            initial_db={"POS": {"existencia": 10.0, "costo": 3.0, "precio": 5.0}},
            fail_post_ajuste_read=True,
        )
        items = [
            {"codigo": "POS", "cantidad": 5.0, "costo": 3.5, "precio": 5.5, "es_ajuste": True},
        ]

        res = fcr.registrar_compra("PROV1", items, "1005", commit=True)
        assert res["ok"] is False
        assert res["etapa"] == "ajuste_inventario:verificacion_indisponible"

        monkeypatch.setattr(lc.lb, "check_hybrid_write_enabled", lambda: True)
        status, detalle = lc._politica_resultado(res, intentos=1)
        assert status == "error"
        assert "TOTALIZADOS" in detalle
        assert "NO reencolar" in detalle

    def test_parse_items_soporta_sufijo_tres_puntos_y_flag_ajuste(self):
        items = fcr._parse_items("01404:5...:0.50:1.00,02233:3:2.00:3.50,03344:7:1.00:2.00:ajuste")
        assert items == [
            {"codigo": "01404", "cantidad": 5.0, "costo": 0.50, "precio": 1.00, "es_ajuste": True},
            {"codigo": "02233", "cantidad": 3.0, "costo": 2.00, "precio": 3.50, "es_ajuste": False},
            {"codigo": "03344", "cantidad": 7.0, "costo": 1.00, "precio": 2.00, "es_ajuste": True},
        ]

    def test_ajustar_stock_lote_respeta_target_explicito(self, monkeypatch):
        import abrir_hybrid

        monkeypatch.setattr(abrir_hybrid, "asegurar_hybrid", lambda: (True, "OK"))
        monkeypatch.setattr(fcr.fsr.dbex, "existencia", lambda cod: (15.0, []))
        capturado = {}

        def fake_lote_un_doc(chunk, targets, existencias_antes, commit):
            capturado["targets"] = dict(targets)
            return {
                "ok": True,
                "etapa": "preview",
                "detalle": "ok",
                "resultados": {it["item_id"]: {"ok": True, "etapa": "preview", "detalle": "ok"} for it in chunk},
            }

        monkeypatch.setattr(fcr.fsr, "_lote_un_documento", fake_lote_un_doc)
        res = fcr.fsr.ajustar_stock_lote(
            [
                {"item_id": "A", "codigo": "A", "delta": -10.0, "target": 5.0},
                {"item_id": "B", "codigo": "B", "delta": 2.0},
            ],
            commit=False,
        )
        assert res["ok"] is True
        assert capturado["targets"] == {"A": 5.0, "B": 17.0}


class TestListenerComprasEsAjuste:
    def test_get_items_lee_y_mapea_es_ajuste(self, monkeypatch):
        import listener_compras as lc

        paths_llamados = []

        def fake_rest(method, path, **kwargs):
            paths_llamados.append(path)
            return [
                {
                    "codigo_producto": "01404",
                    "descripcion": "CLAVOS",
                    "referencia": None,
                    "es_nuevo": False,
                    "es_ajuste": True,
                    "cantidad": 5,
                    "costo": 1.0,
                    "precio": 2.0,
                },
                {
                    "codigo_producto": "02233",
                    "descripcion": "MARTILLO",
                    "referencia": "REF1",
                    "es_nuevo": False,
                    "cantidad": 3,
                    "costo": 4.0,
                    "precio": 6.0,
                },
            ]

        monkeypatch.setattr(lc.lb, "rest", fake_rest)
        items = lc.get_items(99)
        assert "es_ajuste" in paths_llamados[0]
        assert items[0]["es_ajuste"] is True
        assert items[0]["cantidad"] == 5.0
        assert items[1]["es_ajuste"] is False

    def test_get_items_fallback_si_columna_es_ajuste_no_existe_aun(self, monkeypatch):
        import io
        import urllib.error
        import listener_compras as lc

        lc._AVISO_SIN_COL_ES_AJUSTE = False
        paths_llamados = []

        def fake_rest(method, path, **kwargs):
            paths_llamados.append(path)
            if "es_ajuste" in path:
                fp = io.BytesIO(
                    b'{"code":"42703","message":"column compras_app_items.es_ajuste does not exist"}'
                )
                raise urllib.error.HTTPError(
                    "https://example.supabase.co/rest/v1/compras_app_items",
                    400,
                    "Bad Request",
                    {},
                    fp,
                )
            return [
                {
                    "codigo_producto": "02233",
                    "descripcion": "MARTILLO",
                    "referencia": None,
                    "es_nuevo": False,
                    "cantidad": 3,
                    "costo": 4.0,
                    "precio": 6.0,
                }
            ]

        monkeypatch.setattr(lc.lb, "rest", fake_rest)
        items = lc.get_items(155)
        assert len(paths_llamados) == 2
        assert "es_ajuste" in paths_llamados[0]
        assert "es_ajuste" not in paths_llamados[1]
        assert len(items) == 1
        assert items[0]["codigo"] == "02233"
        assert items[0]["es_ajuste"] is False

    def test_procesar_compra_usa_control_seguro_y_marca_error_si_falla_ajuste(self, monkeypatch):
        import listener_compras as lc
        from contextlib import contextmanager

        eventos = []
        actualizaciones = []

        class FakeBanner:
            def set_texto(self, txt):
                eventos.append(("banner", txt))

        @contextmanager
        def fake_control_seguro(msg, ocultar_scripts=None):
            eventos.append(("lock_enter", msg))
            yield FakeBanner()
            eventos.append(("lock_exit", msg))

        monkeypatch.setattr(lc, "control_seguro", fake_control_seguro)
        monkeypatch.setattr(lc.lb, "check_hybrid_write_enabled", lambda: True)
        monkeypatch.setattr(lc, "update_compra",
                            lambda cid, **fields: actualizaciones.append((cid, fields)) or True)
        monkeypatch.setattr(lc, "get_items", lambda cid: [
            {"codigo": "POS", "cantidad": 5.0, "costo": 3.5, "precio": 5.5,
             "es_nuevo": False, "es_ajuste": True, "referencia": None, "descripcion": "POS"}
        ])

        def fake_registrar_compra(prov, items, doc, commit=False, proveedor_nombre=None, banner=None):
            assert banner is not None
            assert items[0]["es_ajuste"] is True
            banner.set_texto("AJUSTANDO EXISTENCIA FIJA")
            return {"ok": False, "etapa": "ajuste_inventario:carga/conteo", "detalle": "fallo UI"}

        monkeypatch.setattr(lc.flujo_compra_real, "registrar_compra", fake_registrar_compra)

        lc.procesar_compra({"id": 77, "proveedor_codigo": "P1", "proveedor_nombre": "PROV", "backend_intentos": 0})

        assert eventos[0][0] == "lock_enter"
        assert ("banner", "AJUSTANDO EXISTENCIA FIJA") in eventos
        assert eventos[-1][0] == "lock_exit"
        assert actualizaciones[-1][1]["backend_status"] == "error"
        assert "NO reencolar" in actualizaciones[-1][1]["backend_resultado"]

    def test_procesar_pendientes_pospone_si_hybrid_bloqueado(self, monkeypatch):
        import listener_compras as lc
        import hybrid_health as hh

        monkeypatch.setattr(hh, "verificar_hybrid_listo",
                            lambda target_pid=None: (False, "modal bloqueante", [{"motivo": "modal"}]))
        llamados = []
        monkeypatch.setattr(lc, "procesar_compra", lambda *a, **kw: llamados.append(True))

        lc.procesar_pendientes([{"id": 1, "proveedor_codigo": "P1"}])
        assert llamados == []


class TestEscribirCampoFicha:
    """Regresión para _escribir_campo_ficha / _limpiar_campo_ficha (OC-35974)."""

    @staticmethod
    def _setup_fake_edit(monkeypatch, initial_text="", *, read_only=False,
                         vcl_select_all_works=True, ctrl_a_works=True):
        class FakeRect:
            left, top, right, bottom = 100, 200, 500, 225

        class FakeControl:
            def __init__(self, text):
                self.text = text
                self.cursor = len(text)
                self.selected = False
                self.focus_calls = 0

            def rectangle(self):
                return FakeRect()

            def set_focus(self):
                self.focus_calls += 1

            def window_text(self):
                return self.text

        ctrl = FakeControl(initial_text)
        calls = []

        monkeypatch.setattr("time.sleep", lambda s: None)
        monkeypatch.setattr(fcr.ri, "click", lambda x, y: calls.append(("click", x, y)))

        def fake_select_all():
            calls.append(("select_all_field",))
            if vcl_select_all_works:
                ctrl.selected = True

        def fake_press(name, hold=0.02):
            calls.append(("press", name))
            if name == "BACKSPACE" and not read_only:
                if ctrl.selected:
                    ctrl.text = ""
                    ctrl.cursor = 0
                    ctrl.selected = False
                elif ctrl.cursor > 0:
                    ctrl.text = ctrl.text[:ctrl.cursor - 1] + ctrl.text[ctrl.cursor:]
                    ctrl.cursor -= 1

        def fake_clear_field():
            calls.append(("clear_field",))
            if not read_only and ctrl_a_works:
                ctrl.text = ""
                ctrl.cursor = 0
                ctrl.selected = False

        def fake_clear_hard(n=8):
            calls.append(("clear_hard", n))
            if not read_only:
                # Simula END + n*BACKSPACE + HOME + n*DELETE
                ctrl.text = ctrl.text[:-n] if n < len(ctrl.text) else ""
                ctrl.text = ctrl.text[n:] if n < len(ctrl.text) else ""
                ctrl.cursor = 0
                ctrl.selected = False

        def fake_type(kind, valor):
            calls.append((kind, valor, ctrl.text))
            if not read_only:
                if ctrl.selected:
                    ctrl.text = valor
                    ctrl.cursor = len(valor)
                    ctrl.selected = False
                else:
                    ctrl.text = ctrl.text[:ctrl.cursor] + valor + ctrl.text[ctrl.cursor:]
                    ctrl.cursor += len(valor)

        monkeypatch.setattr(fcr.ri, "select_all_field", fake_select_all)
        monkeypatch.setattr(fcr.ri, "press", fake_press)
        monkeypatch.setattr(fcr.ri, "clear_field", fake_clear_field)
        monkeypatch.setattr(fcr.ri, "clear_hard", fake_clear_hard)
        monkeypatch.setattr(fcr.ri, "type_text", lambda v, **kw: fake_type("type_text", v))
        monkeypatch.setattr(fcr.ri, "type_code", lambda v, **kw: fake_type("type_code", v))
        return ctrl, calls

    def test_oc35974_regression_clears_full_existing_description_via_clear_hard(self, monkeypatch):
        """Caso exacto OC-35974: si select_all y Ctrl+A no limpian, clear_hard(n)
        debe dimensionarse al largo actual (n >= 13) y vaciar todo antes de teclear."""
        viejo = "CURVA 90GR PVC CONDUIT 3/4"
        nuevo = "CURVA 90GR PVC CONDUIT 3/4 PAVCO"
        ctrl, calls = self._setup_fake_edit(
            monkeypatch, viejo, vcl_select_all_works=False, ctrl_a_works=False
        )

        resultado = fcr._escribir_campo_ficha(ctrl, nuevo, lento=False)

        assert resultado == nuevo
        hard_calls = [c for c in calls if c[0] == "clear_hard"]
        assert len(hard_calls) == 1
        assert hard_calls[0][1] >= 13
        type_calls = [c for c in calls if c[0] == "type_text"]
        assert type_calls == [("type_text", nuevo, "")]

    def test_fast_path_vcl_select_all_clears_long_text_without_clear_hard(self, monkeypatch):
        """Si Home+Shift+End + Backspace vacía el campo de 60 chars, no llama clear_field ni clear_hard."""
        ctrl, calls = self._setup_fake_edit(monkeypatch, "A" * 60)

        resultado = fcr._escribir_campo_ficha(ctrl, "DESCRIPCION NUEVA", lento=False)

        assert resultado == "DESCRIPCION NUEVA"
        assert ("select_all_field",) in calls
        assert ("clear_field",) not in calls
        assert all(c[0] != "clear_hard" for c in calls)

    def test_second_fast_path_ctrl_a_clears_without_clear_hard(self, monkeypatch):
        """Si Home+Shift+End falla pero Ctrl+A limpia, no cae a clear_hard."""
        ctrl, calls = self._setup_fake_edit(
            monkeypatch, "TEXTO PREVIO LARGO", vcl_select_all_works=False, ctrl_a_works=True
        )

        resultado = fcr._escribir_campo_ficha(ctrl, "NUEVO TEXTO", lento=False)

        assert resultado == "NUEVO TEXTO"
        assert ("select_all_field",) in calls
        assert ("clear_field",) in calls
        assert all(c[0] != "clear_hard" for c in calls)

    def test_already_empty_field_skips_clearing_and_types_directly(self, monkeypatch):
        """En modo alta (campo vacío), no envía ninguna tecla de borrado."""
        ctrl, calls = self._setup_fake_edit(monkeypatch, "")

        resultado = fcr._escribir_campo_ficha(ctrl, "01567", lento=True)

        assert resultado == "01567"
        assert [c[0] for c in calls] == ["click", "type_code"]

    def test_very_long_and_whitespace_only_fields_clear_completely(self, monkeypatch):
        """Textos de 120 chars y solo espacios se vacían por completo antes de escribir."""
        ctrl_long, calls_long = self._setup_fake_edit(
            monkeypatch, "X" * 120, vcl_select_all_works=False, ctrl_a_works=False
        )
        assert fcr._escribir_campo_ficha(ctrl_long, "CORTO") == "CORTO"
        assert [c for c in calls_long if c[0] == "type_text"] == [("type_text", "CORTO", "")]

        ctrl_ws, calls_ws = self._setup_fake_edit(
            monkeypatch, "   ", vcl_select_all_works=False, ctrl_a_works=False
        )
        assert fcr._escribir_campo_ficha(ctrl_ws, "LIMPIO") == "LIMPIO"
        assert [c for c in calls_ws if c[0] == "type_text"] == [("type_text", "LIMPIO", "")]

    def test_unclearable_field_aborts_without_typing(self, monkeypatch):
        """Si el campo no puede vaciarse (p.ej. solo lectura), reenfoca 1 vez,
        no teclea el valor nuevo y retorna el texto que quedó en pantalla."""
        viejo = "TEXTO BLOQUEADO"
        ctrl, calls = self._setup_fake_edit(
            monkeypatch, viejo, read_only=True, vcl_select_all_works=False, ctrl_a_works=False
        )

        resultado = fcr._escribir_campo_ficha(ctrl, "TEXTO NUEVO", lento=False)

        assert resultado == viejo
        assert ctrl.focus_calls == 2  # foco inicial + 1 reintento de foco
        assert all(c[0] not in ("type_text", "type_code") for c in calls)
        assert len([c for c in calls if c[0] == "clear_hard"]) == 2



