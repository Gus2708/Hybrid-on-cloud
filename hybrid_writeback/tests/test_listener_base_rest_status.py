"""Tests for the optional ``expected_status`` guard of the REAL ``listener_base.rest``.

The production ``listener_base`` is imported for real, but only after a fake ``config``
module is installed in ``sys.modules`` (so no ``config.py``/``.env`` is read and no
``sys.exit`` can fire). ``urllib.request.urlopen`` is replaced by a scripted fake, so no
network is used; the transport logic under test is the production function itself.
``listener_compras`` is imported with ``flujo_compra_real``/``safety_control`` stubbed and
logging redirected, so no log file is created and no Hybrid/UI module is loaded.

Run from the repository root:
    python -m unittest discover -s hybrid_writeback/tests -p test_listener_base_rest_status.py -v
"""
import importlib
import inspect
import json
import logging
import os
import sys
import types
import unittest
import urllib.error
import urllib.request
from unittest import mock

HW_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if HW_DIR not in sys.path:
    sys.path.insert(0, HW_DIR)

REST_URL = "https://fake.invalid"
SERVICE_KEY = "svc-KEY-SECRETO"
ANON_KEY = "anon-KEY-SECRETO"


class Resp:
    """Fake urllib response: records body reads and whether it was closed."""

    def __init__(self, status, cuerpo=b""):
        self.status_code, self.cuerpo, self.lecturas, self.cerrada = status, cuerpo, 0, False

    def getcode(self):
        return self.status_code

    @property
    def status(self):
        return self.status_code

    def read(self):
        self.lecturas += 1
        return self.cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrada = True
        return False


class FalsoUrlopen:
    def __init__(self):
        self.respuesta = Resp(200, b"true")
        self.llamadas = []

    def __call__(self, req, timeout=None):
        self.llamadas.append((req, timeout))
        if isinstance(self.respuesta, BaseException):
            raise self.respuesta
        return self.respuesta


def http_error(codigo):
    return urllib.error.HTTPError(f"{REST_URL}/rest/v1/x", codigo, "x", {}, None)


class BaseRestTest(unittest.TestCase):
    def setUp(self):
        cfg = types.ModuleType("config")
        cfg.SUPABASE_REST_URL = REST_URL + "/"
        cfg.SUPABASE_ANON_KEY = ANON_KEY
        cfg.SUPABASE_SERVICE_KEY = SERVICE_KEY
        parche = mock.patch.dict(sys.modules, {"config": cfg})
        parche.start()
        self.addCleanup(parche.stop)
        sys.modules.pop("listener_base", None)
        self.lb = importlib.import_module("listener_base")
        self.urlopen = FalsoUrlopen()
        parche = mock.patch.object(self.lb.urllib.request, "urlopen", self.urlopen)
        parche.start()
        self.addCleanup(parche.stop)

    def llamar(self, *args, **kwargs):
        return self.lb.rest(*args, **kwargs)

    def peticion(self):
        (req, timeout), = self.urlopen.llamadas
        return req, timeout


class TestRestPorDefecto(BaseRestTest):
    """Old callers: the new keyword changes nothing unless it is passed."""

    def test_firma_conserva_los_cuatro_parametros_y_el_nuevo_es_opcional(self):
        params = inspect.signature(self.lb.rest).parameters
        self.assertEqual(list(params)[:4], ["method", "path", "body", "extra_headers"])
        self.assertEqual(list(params)[4:], ["expected_status"])
        self.assertIsNone(params["expected_status"].default)

    def test_cualquier_2xx_con_json_sigue_igual(self):
        for status in (200, 201, 202, 203):
            with self.subTest(status=status):
                self.setUp()
                self.urlopen.respuesta = Resp(status, b"true")
                self.assertIs(self.llamar("POST", "rpc/x", body={"a": 1}), True)

    def test_cuerpo_vacio_sigue_siendo_none(self):
        self.urlopen.respuesta = Resp(204, b"")
        self.assertIsNone(self.llamar("PATCH", "t?id=eq.1", body={"a": 1}))

    def test_json_invalido_sigue_propagando_valueerror(self):
        self.urlopen.respuesta = Resp(200, b"{no")
        with self.assertRaises(ValueError):
            self.llamar("GET", "t")

    def test_errores_http_se_propagan_tal_cual(self):
        for codigo in (301, 400, 401, 403, 404, 500):
            with self.subTest(codigo=codigo):
                error = http_error(codigo)
                self.urlopen.respuesta = error
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    self.llamar("GET", "t")
                self.assertIs(cm.exception, error)

    def test_peticion_identica_para_cada_metodo_y_cabeceras(self):
        casos = [("GET", "t?select=id", None, None),
                 ("POST", "rpc/f", {"p": 1}, None),
                 ("PATCH", "t?id=eq.9", {"a": "b"}, {"Prefer": "return=minimal"}),
                 ("DELETE", "t?id=eq.9", None, {"Prefer": "return=representation"}),
                 ("POST", "rpc/f", {"p": 1}, {"Content-Type": "text/plain"})]
        for metodo, ruta, cuerpo, extra in casos:
            with self.subTest(metodo=metodo, ruta=ruta, extra=extra):
                esperada = {"Apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                            "Content-type": "application/json"}
                esperada.update({k.capitalize(): v for k, v in (extra or {}).items()})
                versiones = []
                for kw in ({}, {"expected_status": 200}):
                    self.setUp()
                    self.urlopen.respuesta = Resp(200, b"null")
                    self.llamar(metodo, ruta, cuerpo, extra, **kw)
                    req, timeout = self.peticion()
                    versiones.append((req.full_url, req.get_method(), dict(req.header_items()),
                                      req.data, timeout))
                self.assertEqual(versiones[0], versiones[1])
                url, met, cab, datos, timeout = versiones[0]
                self.assertEqual(url, f"{REST_URL}/rest/v1/{ruta}")
                self.assertEqual(met, metodo)
                self.assertEqual(cab, esperada)
                self.assertEqual(datos, None if cuerpo is None else json.dumps(cuerpo).encode("utf-8"))
                self.assertEqual(timeout, 30)


class TestRestEstadoEsperado(BaseRestTest):
    def test_estado_exacto_200_devuelve_el_json(self):
        for crudo, valor in ((b"true", True), (b"false", False)):
            with self.subTest(cuerpo=crudo):
                self.setUp()
                self.urlopen.respuesta = Resp(200, crudo)
                self.assertIs(self.llamar("POST", "rpc/x", body={"a": 1}, expected_status=200), valor)

    def test_otro_2xx_se_rechaza_antes_de_leer_el_cuerpo(self):
        for status in (201, 202, 203, 204, 206):
            with self.subTest(status=status):
                self.setUp()
                resp = self.urlopen.respuesta = Resp(status, b"true")
                with self.assertRaises(self.lb.RestStatusInesperado) as cm:
                    self.llamar("POST", "rpc/x", body={"a": 1}, expected_status=200)
                self.assertEqual(cm.exception.status, status)
                self.assertEqual(resp.lecturas, 0)
                self.assertTrue(resp.cerrada)

    def test_204_con_cuerpo_vacio_se_rechaza_con_esperado(self):
        resp = self.urlopen.respuesta = Resp(204, b"")
        with self.assertRaises(self.lb.RestStatusInesperado):
            self.llamar("POST", "rpc/x", expected_status=200)
        self.assertEqual(resp.lecturas, 0)

    def test_errores_http_se_propagan_igual_con_esperado(self):
        for codigo in (301, 400, 401, 403, 404, 500):
            with self.subTest(codigo=codigo):
                error = http_error(codigo)
                self.urlopen.respuesta = error
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    self.llamar("POST", "rpc/x", expected_status=200)
                self.assertIs(cm.exception, error)

    def test_el_error_de_estado_no_filtra_credenciales_ni_cuerpo(self):
        self.urlopen.respuesta = Resp(201, b"CUERPO-SECRETO")
        with self.assertRaises(self.lb.RestStatusInesperado) as cm:
            self.llamar("POST", "rpc/x", expected_status=200)
        texto = f"{cm.exception} {cm.exception!r}"
        for secreto in ("SECRETO", SERVICE_KEY, ANON_KEY, "Bearer"):
            self.assertNotIn(secreto, texto)

    def test_con_estado_200_el_json_invalido_sigue_propagando_valueerror(self):
        self.urlopen.respuesta = Resp(200, b"{no")
        with self.assertRaises(ValueError):
            self.llamar("POST", "rpc/x", expected_status=200)


class TestOrigenConRestReal(BaseRestTest):
    """es_compra_de_factura over the real rest(): only a literal 200 + exact boolean passes."""

    def setUp(self):
        super().setUp()
        self.lb.setup_logging = lambda nombre, archivo: logging.getLogger(nombre)
        stubs = {"flujo_compra_real": types.ModuleType("flujo_compra_real"),
                 "safety_control": types.ModuleType("safety_control")}
        stubs["safety_control"].control_seguro = None
        parche = mock.patch.dict(sys.modules, stubs)
        parche.start()
        self.addCleanup(parche.stop)
        sys.modules.pop("listener_compras", None)
        self.lc = importlib.import_module("listener_compras")
        self.addCleanup(logging.disable, logging.NOTSET)
        logging.disable(logging.CRITICAL)

    def test_200_booleano_exacto_pasa(self):
        for crudo, valor in ((b"true", True), (b"false", False)):
            with self.subTest(cuerpo=crudo):
                self.setUp()
                self.urlopen.respuesta = Resp(200, crudo)
                self.assertIs(self.lc.es_compra_de_factura(7), valor)
                req, timeout = self.peticion()
                self.assertEqual((req.full_url, req.get_method(), req.data, timeout),
                                 (f"{REST_URL}/rest/v1/rpc/es_compra_de_factura", "POST",
                                  b'{"p_compra_id": 7}', 30))

    def test_otro_estado_2xx_con_booleano_falla_cerrado_sin_leer_el_cuerpo(self):
        for status in (201, 202, 203, 204, 206):
            for crudo in (b"true", b"false", b""):
                with self.subTest(status=status, cuerpo=crudo):
                    self.setUp()
                    resp = self.urlopen.respuesta = Resp(status, crudo)
                    with self.assertRaises(self.lc.OrigenDesconocido) as cm:
                        self.lc.es_compra_de_factura(7)
                    self.assertIn(str(status), str(cm.exception))
                    self.assertEqual(resp.lecturas, 0)

    def test_estado_200_con_cuerpo_no_booleano_falla_cerrado(self):
        for crudo in (b"null", b'"true"', b"1", b"0", b"[]", b"{}", b"", b"{no"):
            with self.subTest(cuerpo=crudo):
                self.setUp()
                self.urlopen.respuesta = Resp(200, crudo)
                with self.assertRaises(self.lc.OrigenDesconocido):
                    self.lc.es_compra_de_factura(7)

    def test_errores_http_fallan_cerrado_con_su_codigo(self):
        for codigo in (301, 400, 401, 403, 404, 500):
            with self.subTest(codigo=codigo):
                self.urlopen.respuesta = http_error(codigo)
                with self.assertRaises(self.lc.OrigenDesconocido) as cm:
                    self.lc.es_compra_de_factura(7)
                self.assertIn(f"HTTP {codigo}", str(cm.exception))

    def test_el_mensaje_de_origen_no_filtra_credenciales(self):
        self.urlopen.respuesta = Resp(201, b"true")
        with self.assertRaises(self.lc.OrigenDesconocido) as cm:
            self.lc.es_compra_de_factura(7)
        for secreto in (SERVICE_KEY, ANON_KEY, "Bearer"):
            self.assertNotIn(secreto, str(cm.exception))

    def test_las_demas_llamadas_del_listener_no_usan_el_guard(self):
        self.urlopen.respuesta = Resp(201, b"[]")
        self.assertEqual(self.lc.get_items(5), [])           # any 2xx still accepted
        self.urlopen.respuesta = Resp(204, b"")
        self.assertTrue(self.lc.update_compra(5, backend_status="pendiente"))


if __name__ == "__main__":
    unittest.main()
