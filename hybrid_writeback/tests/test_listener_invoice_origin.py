"""Public-flow tests for the invoice-origin check in listener_compras.

The real ``listener_compras.procesar_compra`` / ``_politica_resultado`` run on top of the
real ``flujo_compra_real`` strict path. Everything external is fake and installed in
``sys.modules`` BEFORE the production modules are imported: ``listener_base`` (so no
config, log file or network is touched), the REST transport (scripted
``es_compra_de_factura`` answers, purchase header PATCH log, item rows), the Hybrid/native
UI modules and a synthetic DBISAM catalog (see test_invoice_product_identity.py).

Run from the repository root:
    python -m unittest discover -s hybrid_writeback/tests -p test_listener_invoice_origin.py -v
"""
import contextlib
import importlib
import io
import json
import logging
import os
import socket
import sys
import types
import unittest
import urllib.error

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from test_invoice_product_identity import (  # noqa: E402  (shared fakes, not the test cases)
    CODIGO, DESCRIPCION, REFERENCIA, SECRETO_DESC, FlujoBase, setUpModule as _silenciar,
    tearDownModule as _restaurar)

setUpModule, tearDownModule = _silenciar, _restaurar

SECRETO_HTTP = "CUERPO-HTTP-SECRETO-99"


class RestStatusInesperado(Exception):
    """Mirror of listener_base.RestStatusInesperado (the real one is covered in
    test_listener_base_rest_status.py)."""

    def __init__(self, status):
        super().__init__(f"HTTP {status} inesperado")
        self.status = status


def http_error(codigo):
    return urllib.error.HTTPError("https://fake.invalid/rest/v1/rpc/es_compra_de_factura", codigo,
                                  "x", {}, io.BytesIO(SECRETO_HTTP.encode()))


class Red:
    """Scripted stand-in for listener_base.rest (same return/raise contract)."""

    def __init__(self, mundo):
        self.mundo = mundo
        self.rpc = True            # value returned, exception raised, or callable(body)
        self.rpc_estado = 200      # HTTP status the fake server answers with
        self.expected = []         # expected_status passed on each call
        self.filas = []            # compras_app_items rows
        self.parches = []          # bodies PATCHed on the purchase header, in order
        self.llamadas = []         # (method, path, body)

    def __call__(self, method, path, body=None, extra_headers=None, expected_status=None):
        self.llamadas.append((method, path, body))
        self.expected.append(expected_status)
        self.mundo.evento("http", method, path.split("?")[0])
        if (method, path) == ("POST", "rpc/es_compra_de_factura"):
            r = self.rpc
            if isinstance(r, BaseException):
                raise r
            if expected_status is not None and self.rpc_estado != expected_status:
                raise RestStatusInesperado(self.rpc_estado)
            return r(body) if callable(r) else r
        if method == "GET" and path.startswith("compras_app_items?"):
            return self.filas
        if method == "PATCH" and path.startswith("compras_app?id=eq."):
            self.parches.append(body)
            return None
        raise AssertionError(f"unexpected REST call {method} {path}")


class ListenerBase(FlujoBase):
    def setUp(self):
        super().setUp()
        m = self.mundo
        self.red = Red(m)
        self.escritura = True

        lb = types.ModuleType("listener_base")
        lb.AVISO_SIN_SERVICE_KEY = None
        lb.setup_logging = lambda nombre, archivo: logging.getLogger(nombre)
        lb.check_hybrid_write_enabled = lambda: self.escritura
        lb.hay_pendientes_prioritarios = lambda: False
        lb.correr_loop = lambda *a, **k: None
        lb.rest = self.red
        lb.RestStatusInesperado = RestStatusInesperado

        @contextlib.contextmanager
        def control_seguro(texto, ocultar_scripts=None):
            m.evento("control_seguro")
            yield

        sc = types.ModuleType("safety_control")
        sc.control_seguro = control_seguro
        sys.modules["listener_base"] = lb          # undone by FlujoBase's patch.dict cleanup
        sys.modules["safety_control"] = sc
        sys.modules.pop("listener_compras", None)
        self.lc = importlib.import_module("listener_compras")
        self.assertIs(self.lc.flujo_compra_real, self.fcr)

        # Spy on the real registrar_compra: same call, recorded kwargs.
        self.llamadas_registrar = []
        original = self.fcr.registrar_compra

        def espia(*args, **kwargs):
            self.llamadas_registrar.append((args, kwargs))
            return original(*args, **kwargs)

        self.fcr.registrar_compra = espia

    # ── helpers ──────────────────────────────────────────────────────────────
    def fila(self, codigo=CODIGO, referencia=REFERENCIA, descripcion=DESCRIPCION, es_nuevo=True):
        return {"codigo_producto": codigo, "descripcion": descripcion, "referencia": referencia,
                "es_nuevo": es_nuevo, "cantidad": 2, "costo": 5, "precio": 8}

    def procesar(self, filas=None, cid=7, intentos_previos=0):
        self.red.filas = [self.fila()] if filas is None else filas
        compra = {"id": cid, "proveedor_codigo": "PROV1", "proveedor_nombre": "Proveedor",
                  "backend_intentos": intentos_previos, "numero_documento": "123456"}
        self.lc.procesar_compra(compra)
        return self.red.parches[-1] if self.red.parches else None

    def posicion(self, nombre):
        return next(i for i, e in enumerate(self.mundo.eventos) if e[0] == nombre)

    def sin_efectos_de_hybrid(self):
        for efecto in ("abrir_hybrid", "control_seguro", "abrir_ficha", "guardar", "abrir_compras",
                       "cargar_item", "totalizar"):
            self.assertEqual(self.mundo.n(efecto), 0, efecto)
        self.assertEqual(self.llamadas_registrar, [])


class TestOrigenDesconocidoFallaCerrado(ListenerBase):
    RESPUESTAS = {
        "http 401": http_error(401), "http 403": http_error(403), "http 404": http_error(404),
        "http 400": http_error(400), "http 500": http_error(500),
        "timeout": socket.timeout("timed out"), "red": urllib.error.URLError("sin ruta"),
        "json malformado": json.JSONDecodeError("x", "y", 0),
        "null": None, "string true": "true", "string false": "false", "numero 1": 1,
        "numero 0": 0, "lista": [True], "objeto": {"es": True}, "string vacio": "",
    }

    def test_ninguna_respuesta_no_verificable_se_degrada_a_manual(self):
        for nombre, respuesta in self.RESPUESTAS.items():
            with self.subTest(respuesta=nombre):
                self.setUp()
                self.red.rpc = respuesta
                final = self.procesar()
                self.assertEqual(final["backend_status"], "pendiente")
                self.assertIn("origen", final["backend_resultado"])
                self.sin_efectos_de_hybrid()
                self.assertEqual(self.mundo.eventos.count(("http", "POST", "rpc/es_compra_de_factura")), 1)

    def test_solo_el_estado_200_literal_cuenta_aunque_el_cuerpo_sea_booleano(self):
        for estado in (201, 202, 203, 204, 206):
            for cuerpo in (True, False):
                with self.subTest(estado=estado, cuerpo=cuerpo):
                    self.setUp()
                    self.red.rpc, self.red.rpc_estado = cuerpo, estado
                    final = self.procesar()
                    self.assertEqual(final["backend_status"], "pendiente")
                    self.assertIn(f"HTTP {estado}", final["backend_resultado"])
                    self.sin_efectos_de_hybrid()

    def test_el_rpc_exige_expected_status_200(self):
        self.procesar()
        self.assertEqual([e for e, c in zip(self.red.expected, self.red.llamadas) if c[0] == "POST"], [200])
        self.assertEqual([e for e, c in zip(self.red.expected, self.red.llamadas) if c[0] != "POST"],
                         [None] * len([c for c in self.red.llamadas if c[0] != "POST"]))

    def test_agotados_los_intentos_queda_en_error_visible(self):
        self.red.rpc = http_error(404)
        final = self.procesar(intentos_previos=2)
        self.assertEqual(final["backend_status"], "error")
        self.assertIn("origen", final["backend_resultado"])
        self.assertIn("404", final["backend_resultado"])
        self.sin_efectos_de_hybrid()

    def test_el_resultado_no_filtra_cuerpos_ni_mensajes_crudos(self):
        for rpc in (http_error(403), socket.timeout(SECRETO_HTTP), ValueError(SECRETO_HTTP)):
            with self.subTest(rpc=type(rpc).__name__):
                self.setUp()
                self.red.rpc = rpc
                final = self.procesar()
                self.assertNotIn("SECRETO", final["backend_resultado"])

    def test_id_invalido_no_llama_al_rpc_y_falla_cerrado(self):
        for cid in (0, -3, None, True, "7", 7.0):
            with self.subTest(cid=cid):
                self.setUp()
                final = self.procesar(cid=cid)
                self.assertEqual(final["backend_status"], "pendiente")
                self.assertEqual([c for c in self.red.llamadas if c[0] == "POST"], [])
                self.sin_efectos_de_hybrid()

    def test_empty_items_keep_their_previous_behavior_without_origin_call(self):
        final = self.procesar(filas=[])
        self.assertIn("Esperando items", final["backend_resultado"])
        self.assertEqual([c for c in self.red.llamadas if c[0] == "POST"], [])


class TestOrigenFactura(ListenerBase):
    def test_rpc_exacto_una_vez_y_antes_de_cualquier_efecto_de_hybrid(self):
        self.procesar()
        posts = [c for c in self.red.llamadas if c[0] == "POST"]
        self.assertEqual(posts, [("POST", "rpc/es_compra_de_factura", {"p_compra_id": 7})])
        rpc = self.mundo.eventos.index(("http", "POST", "rpc/es_compra_de_factura"))
        self.assertLess(rpc, self.posicion("control_seguro"))
        self.assertLess(rpc, self.posicion("abrir_hybrid"))

    def test_verdadero_activa_la_identidad_estricta_y_completa(self):
        final = self.procesar()
        (args, kwargs), = self.llamadas_registrar
        self.assertIs(kwargs["identidad_estricta"], True)
        self.assertEqual(final["backend_status"], "completado")
        self.assertEqual(self.mundo.n("guardar"), 1)
        self.assertIn(("escribir", "referencia", REFERENCIA), self.mundo.eventos)
        self.assertEqual(self.mundo.catalogo[CODIGO], (REFERENCIA, DESCRIPCION))

    def test_codigo_existente_con_identidad_igual_no_se_recrea(self):
        self.sembrar()
        final = self.procesar()
        self.assertEqual(final["backend_status"], "completado")
        self.assertEqual(self.mundo.n("abrir_ficha"), 0)
        self.assertEqual(self.mundo.n("cargar_item"), 1)

    def test_codigo_existente_con_identidad_distinta_falla_antes_de_hybrid_y_no_sobrescribe(self):
        self.sembrar(descripcion=SECRETO_DESC, referencia="")
        final = self.procesar()
        self.assertEqual(final["backend_status"], "pendiente")      # pre-write, existing policy
        self.assertIn("Nada se tocó", final["backend_resultado"])
        self.assertNotIn("SECRET", final["backend_resultado"])
        for efecto in ("abrir_hybrid", "abrir_ficha", "guardar", "cargar_item", "totalizar"):
            self.assertEqual(self.mundo.n(efecto), 0, efecto)
        self.assertEqual(self.mundo.catalogo[CODIGO], ("", SECRETO_DESC))

    def test_lectura_agotada_tras_guardar_es_error_sin_reintento_ni_compra(self):
        self.mundo.retraso_inicial = 10 ** 6
        final = self.procesar()
        self.assertEqual(final["backend_status"], "error")
        self.assertIn("no apareció", final["backend_resultado"])           # original failure kept
        self.assertIn("NO reintentar", final["backend_resultado"])
        self.assertEqual(len(self.llamadas_registrar), 1)
        self.assertEqual(self.mundo.n("guardar"), 1)
        self.assertEqual(self.mundo.n("abrir_ficha"), 1)
        for efecto in ("cargar_item", "totalizar", "abrir_compras"):
            self.assertEqual(self.mundo.n(efecto), 0, efecto)

    def test_referencia_persistida_distinta_es_error_sin_reintento(self):
        self.mundo.persistida["referencia"] = "OTRA"
        final = self.procesar()
        self.assertEqual(final["backend_status"], "error")
        self.assertIn("referencia", final["backend_resultado"])
        self.assertIn("NO reintentar", final["backend_resultado"])
        self.assertEqual(self.mundo.n("guardar"), 1)
        self.assertEqual(self.mundo.n("totalizar"), 0)

    def test_catalogo_ilegible_tras_guardar_es_error_sin_reintento(self):
        m, antes = self.mundo, self.mundo.rows

        def rows():                      # readable for the pre-flight, unreadable once saved
            if m.pendiente is not None:
                raise OSError("H: caida")
            return antes()

        m.rows = rows
        final = self.procesar()
        self.assertEqual(final["backend_status"], "error")
        self.assertIn("identidad no verificada", final["backend_resultado"])
        self.assertEqual(self.mundo.n("guardar"), 1)
        self.assertEqual(len(self.llamadas_registrar), 1)

    def test_fallo_en_pantalla_antes_de_guardar_sigue_siendo_reintentable(self):
        self.mundo.ui_forzada["referencia"] = "OTRA"
        final = self.procesar()
        self.assertEqual(final["backend_status"], "pendiente")
        self.assertEqual(self.mundo.n("guardar"), 0)

    def test_preview_no_guarda_y_no_afirma_persistencia(self):
        self.escritura = False
        final = self.procesar()
        self.assertEqual(final["backend_status"], "pendiente")
        self.assertTrue(final["backend_resultado"].startswith("[PREVIEW]"))
        self.assertIn("sin prueba de persistencia", final["backend_resultado"])
        self.assertEqual(self.mundo.n("guardar"), 0)


class TestOrigenManual(ListenerBase):
    def setUp(self):
        super().setUp()
        self.red.rpc = False

    def test_falso_conserva_los_mismos_kwargs_de_siempre(self):
        final = self.procesar()
        (args, kwargs), = self.llamadas_registrar
        self.assertEqual(kwargs, {"commit": True, "proveedor_nombre": "Proveedor"})
        self.assertEqual(args[0], "PROV1")
        self.assertEqual(args[2], "123456")
        self.assertEqual(final["backend_status"], "completado")
        self.assertNotIn("identidad", final["backend_resultado"])

    def test_falso_no_aplica_identidad_estricta_a_un_codigo_existente_distinto(self):
        self.sembrar(descripcion="OTRA COSA", referencia="")
        final = self.procesar()
        self.assertEqual(final["backend_status"], "completado")      # old behavior kept
        self.assertEqual(self.mundo.n("abrir_ficha"), 0)
        self.assertEqual(self.mundo.n("cargar_item"), 1)

    def test_falso_conserva_el_aviso_de_referencia_no_bloqueante(self):
        self.mundo.ui_forzada["referencia"] = "OTRA"
        final = self.procesar()
        self.assertEqual(final["backend_status"], "completado")
        self.assertEqual(self.mundo.n("guardar"), 1)


class TestPoliticaResultado(ListenerBase):
    def pol(self, etapa, intentos=1, ok=False, detalle="det", estricto=None, escritura=True):
        self.escritura = escritura
        res = {"ok": ok, "etapa": etapa, "detalle": detalle}
        if estricto is None:
            return self.lc._politica_resultado(res, intentos)
        return self.lc._politica_resultado(res, intentos, estricto=estricto)

    def test_origen_desconocido_es_reintentable_hasta_agotar(self):
        self.assertEqual(self.pol("origen_desconocido", 1), ("pendiente", "det"))
        self.assertEqual(self.pol("origen_desconocido", self.lc.MAX_INTENTOS), ("error", "det"))

    def test_etapas_manuales_sin_cambios(self):
        self.assertEqual(self.pol("commit", ok=True), ("completado", "det"))
        self.assertEqual(self.pol("preview", ok=True, escritura=False), ("pendiente", "[PREVIEW] det"))
        self.assertEqual(self.pol("navegacion", 1), ("pendiente", "det"))
        self.assertEqual(self.pol("navegacion", 3), ("error", "det"))
        self.assertEqual(self.pol("alta_producto:campos", 1), ("pendiente", "det"))
        self.assertEqual(self.pol("verificacion_indisponible"), ("error", "det"))
        self.assertEqual(self.pol("alta_producto:verificacion_indisponible"), ("error", "det"))
        generico = ("det | ATENCIÓN: la compra pudo quedar registrada a medias en HybridLite; "
                    "verificar ANTES de reencolar (riesgo de compra doble).")
        for etapa in ("totalizar", "verificacion_db", "alta_producto:verificacion_db", "excepcion"):
            self.assertEqual(self.pol(etapa), ("error", generico), etapa)

    def test_estricto_false_explicito_equivale_al_default(self):
        for etapa in ("alta_producto:verificacion_db", "totalizar", "navegacion"):
            self.assertEqual(self.pol(etapa, estricto=False), self.pol(etapa), etapa)

    def test_alta_estricta_con_lectura_fallida_es_error_con_aviso_de_no_reintentar(self):
        status, detalle = self.pol("alta_producto:verificacion_db", estricto=True)
        self.assertEqual(status, "error")
        self.assertTrue(detalle.startswith("det"))                # original failure first
        self.assertIn("NO reintentar", detalle)
        self.assertNotIn("compra doble", detalle)

    def test_otras_etapas_no_cambian_con_estricto(self):
        for etapa in ("totalizar", "verificacion_db", "navegacion", "carga_item",
                      "alta_producto:campos", "alta_producto:verificacion_indisponible"):
            self.assertEqual(self.pol(etapa, estricto=True), self.pol(etapa), etapa)


if __name__ == "__main__":
    unittest.main()
