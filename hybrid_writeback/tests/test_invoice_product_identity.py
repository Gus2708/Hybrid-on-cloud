"""Tests for the opt-in strict product identity path of invoice-origin purchases.

Standard-library unittest only. Everything that touches the UI, DBISAM, network or
Hybrid session is a fake: native modules are replaced in ``sys.modules`` before
``flujo_compra_real`` is imported, ``pydbisam`` is a synthetic in-memory catalog and
all Ficha/Compras effects are recorded by a ``Mundo`` object. No real ``.dat`` file,
window or credential is ever touched, and no test reads Git history.

Run from the repository root:
    python -m unittest discover -s hybrid_writeback/tests -p test_invoice_product_identity.py -v
"""
import importlib
import inspect
import logging
import os
import sys
import types
import unittest
from unittest import mock

HW_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if HW_DIR not in sys.path:
    sys.path.insert(0, HW_DIR)

import invoice_product_identity as ipi  # noqa: E402  (pure, stdlib only)

CODIGO = "0075912345678"          # scanned physical barcode, leading zeros on purpose
REFERENCIA = "FAC-00123/B"        # printed invoice supplier code
DESCRIPCION = "ALICATE PRESION 10"
SECRETO_REF = "REF-SECRETO-77"
SECRETO_DESC = "DESC-SECRETA-88"


def setUpModule():
    logging.disable(logging.CRITICAL)   # the flows log every UI step; keep test output pristine


def tearDownModule():
    logging.disable(logging.NOTSET)


class FlujoError(Exception):
    pass


class PrecioError(Exception):
    pass


class Mundo:
    """Synthetic world: DBISAM catalog (optional read-after-save lag) + UI effect log."""

    def __init__(self):
        self.catalogo = {"SEED-1": ("", "SEMILLA")}   # visible on disk: codigo -> (ref, desc)
        self.pendiente = None                          # saved, not yet visible
        self.retraso_inicial = 0                       # catalog reads that still miss it
        self.retraso = 0
        self.version = 0                               # fake mtime of the catalog
        self.lecturas = 0                              # PyDBISAM.rows() calls
        self.fallo_lectura = None
        self.eventos = []
        self.ui = {"codigo": "", "referencia": "", "descripcion": ""}
        self.ui_forzada = {}                           # field -> text shown whatever is typed
        self.sin_control = set()                       # Ficha controls that cannot be located
        self.persistida = {}                           # field -> value stored instead of the UI text
        self.numeros = (0.0, 5.0, 8.0)                 # existencia, costo, precio after save
        self.numeros_error = None

    def evento(self, nombre, *args):
        self.eventos.append((nombre,) + args)

    def n(self, nombre):
        return sum(1 for e in self.eventos if e[0] == nombre)

    def rows(self):
        self.lecturas += 1
        if self.fallo_lectura is not None:
            raise self.fallo_lectura
        if self.pendiente is not None:
            if self.retraso > 0:
                self.retraso -= 1
            else:
                cod, ref, desc = self.pendiente
                self.catalogo[cod] = (ref, desc)
                self.pendiente = None
                self.version += 1
        return [(c, r, d) for c, (r, d) in self.catalogo.items()]

    def guardar(self):
        self.pendiente = (self.ui["codigo"],
                          self.persistida.get("referencia", self.ui["referencia"]),
                          self.persistida.get("descripcion", self.ui["descripcion"]))
        self.retraso = self.retraso_inicial


class CampoFalso:
    def __init__(self, mundo, nombre):
        self.mundo, self.nombre = mundo, nombre

    def window_text(self):
        return self.mundo.ui_forzada.get(self.nombre, self.mundo.ui[self.nombre])


class FalsoTiempo:
    def __init__(self, mundo):
        self.mundo, self._t = mundo, 0.0

    def sleep(self, s):
        self.mundo.evento("sleep", s)

    def time(self):
        self._t += 1.0
        return self._t


class FlujoBase(unittest.TestCase):
    """Imports flujo_compra_real + colisiones against fakes, fresh for every test."""

    def setUp(self):
        m = self.mundo = Mundo()

        fp = types.ModuleType("flujo_precio")
        fp.FlujoError = FlujoError
        fp.FICHA_CLASS = "TTConfigForm"
        fp.PRECIOS_CLASS = "TFHCostosPrecios"
        fp._find_hwnd = lambda clase: 100 if clase == fp.FICHA_CLASS else None
        fp._win = lambda h: mock.MagicMock()

        fpr = types.ModuleType("flujo_precio_real")
        fpr.PrecioError = PrecioError
        fpr.GUARDAR_REL = (240, 60)
        fpr.abrir_ficha = lambda: (m.evento("abrir_ficha"), 100)[1]
        fpr.abrir_costos_precios = lambda: m.evento("abrir_costos_precios")
        fpr.escribir_precio = lambda precio, iva: m.evento("escribir_precio", precio)
        fpr.iva_producto = lambda codigo: 0.16
        fpr._click_boton_dialogo = lambda titulo: (m.evento("boton", titulo), True)[1]
        fpr._focus = lambda h: None

        fsr = types.ModuleType("flujo_stock_real")
        fsr._cerrar_ficha_si_abierta = lambda: m.evento("cerrar_ficha")

        hpw = types.ModuleType("hybrid_price_writer")
        hpw._db_precio_usd = lambda c: 10.0 if c in m.catalogo else None
        hpw._db_costo_usd = lambda c: 5.0
        hpw._db_valores_usd_batch = lambda cs: {}
        hpw._num = lambda t: float(t)

        dbex = types.ModuleType("read_db_existencia")
        dbex.existencia = lambda c: (10.0, [])
        dbex.existencia_batch = lambda cs: {c: (10.0, []) for c in cs}

        abrir = types.ModuleType("abrir_hybrid")
        abrir.asegurar_hybrid = lambda: (m.evento("abrir_hybrid"), (True, "ok"))[1]
        abrir.cerrar_aislada = lambda: None

        pydb = types.ModuleType("pydbisam")

        class PyDBISAM:
            def __init__(self, ruta):
                pass

            def fields(self):
                return ["PRD_CODIGO", "PRD_REFERENCIA", "PRD_DESCRIPCION"]

            def rows(self):
                return m.rows()

        pydb.PyDBISAM = PyDBISAM

        win32gui = mock.MagicMock()
        win32gui.GetWindowRect.return_value = (0, 0, 0, 0)

        parche = mock.patch.dict(sys.modules, {
            "win32gui": win32gui, "win32con": mock.MagicMock(),
            "flujo_precio": fp, "flujo_precio_real": fpr, "flujo_stock_real": fsr,
            "hybrid_price_writer": hpw, "read_db_existencia": dbex,
            "realinput": mock.MagicMock(), "abrir_hybrid": abrir, "pydbisam": pydb,
        })
        parche.start()
        self.addCleanup(parche.stop)
        for nombre in ("flujo_compra_real", "colisiones"):
            sys.modules.pop(nombre, None)
        self.col = importlib.import_module("colisiones")
        self.fcr = importlib.import_module("flujo_compra_real")
        # No native/UI module may have been imported for real.
        self.assertNotIn("pywinauto", sys.modules)

        self.col.os = types.SimpleNamespace(
            path=types.SimpleNamespace(getmtime=lambda p: m.version))
        self.mtime_constante = False

        def campos(hf):
            return {n: (None if n in m.sin_control else CampoFalso(m, n))
                    for n in ("codigo", "referencia", "descripcion")}

        def escribir(campo, valor, lento=False):
            m.ui[campo.nombre] = valor
            m.evento("escribir", campo.nombre, valor)
            return campo.window_text().strip()

        def leer_item_db(codigo):
            if m.numeros_error is not None:
                raise m.numeros_error
            return m.numeros

        def guardar(cerrar_ficha=True):
            m.evento("guardar")
            m.guardar()

        def cancelar(hf):
            m.evento("cancelar_ficha")

        self.fcr.time = FalsoTiempo(m)
        for nombre, valor in {
            "_campos_ficha": campos,
            "_escribir_campo_ficha": escribir,
            "_escribir_costo_alta": lambda costo: m.evento("costo", costo),
            "_guardar_ficha_alta": guardar,
            "_cancelar_ficha_alta": cancelar,
            "_leer_item_db": leer_item_db,
            "abrir_compras": lambda: (m.evento("abrir_compras"), 200)[1],
            "fijar_clasificacion": lambda com: m.evento("clasificacion"),
            "seleccionar_proveedor": lambda com, cod, nom=None: m.evento("proveedor", cod),
            "cargar_item": lambda codigo, *a, **kw: m.evento("cargar_item", codigo),
            "_totalizar_compra": lambda hcom, doc: m.evento("totalizar"),
            "_salir_compras": lambda: m.evento("salir_compras"),
            "_cancelar_compra": lambda hcom: m.evento("cancelar_compra"),
            # stock before is 0.0 (fake below) and every test item buys 2.0
            "_leer_items_db_batch": lambda cs: {c: (2.0, 5.0, 8.0) for c in cs},
        }.items():
            setattr(self.fcr, nombre, valor)
        self.fcr.dbex.existencia_batch = lambda cs: {c: (0.0, []) for c in cs}

    # ── helpers ──────────────────────────────────────────────────────────────
    def crear(self, codigo=CODIGO, referencia=REFERENCIA, descripcion=DESCRIPCION,
              commit=True, **kw):
        return self.fcr.crear_producto(codigo, descripcion, referencia, 5.0, 8.0,
                                       commit=commit, **kw)

    def item(self, codigo=CODIGO, referencia=REFERENCIA, descripcion=DESCRIPCION, **kw):
        base = {"codigo": codigo, "cantidad": 2.0, "costo": 5.0, "precio": 8.0,
                "es_nuevo": True, "referencia": referencia, "descripcion": descripcion}
        base.update(kw)
        return base

    def comprar(self, items, commit=True, **kw):
        return self.fcr.registrar_compra("PROV1", items, "123456", commit=commit, **kw)

    def sembrar(self, codigo=CODIGO, referencia=REFERENCIA, descripcion=DESCRIPCION):
        self.mundo.catalogo[codigo] = (referencia, descripcion)
        self.mundo.version += 1


# ══ Pure identity rules ══════════════════════════════════════════════════════
class TestValidarIdentidad(unittest.TestCase):
    def test_conserva_literal_ceros_mayusculas_y_puntuacion(self):
        e = ipi.validar_identidad("0075912345678", "AbC-007/x.Z", "Alicate 10\" tipo R2")
        self.assertEqual((e.codigo, e.referencia, e.descripcion),
                         ("0075912345678", "AbC-007/x.Z", "Alicate 10\" tipo R2"))

    def test_referencia_faltante_se_acepta_vacia(self):
        self.assertEqual(ipi.validar_identidad("A1", None, "D").referencia, "")
        self.assertEqual(ipi.validar_identidad("A1", "", "D").referencia, "")

    def test_limites_80_codigo_y_100_referencia(self):
        ipi.validar_identidad("c" * 80, "r" * 100, "D")
        with self.assertRaises(ipi.IdentidadInvalida):
            ipi.validar_identidad("c" * 81, "", "D")
        with self.assertRaises(ipi.IdentidadInvalida):
            ipi.validar_identidad("A1", "r" * 101, "D")

    def test_rechaza_vacios_espacios_exteriores_y_control(self):
        for args in [("", "", "D"), ("A1", "", ""), (" A1", "", "D"), ("A1 ", "", "D"),
                     ("A1", " R", "D"), ("A1", "R ", "D"), ("A1", "", " D"),
                     ("A\n1", "", "D"), ("A1", "R\t1", "D"), ("A1", "", "D\r")]:
            with self.subTest(args=args), self.assertRaises(ipi.IdentidadInvalida):
                ipi.validar_identidad(*args)

    def test_no_convierte_tipos(self):
        for args in [(123, "", "D"), ("A1", 7, "D"), ("A1", "", 5.5), (None, "", "D"),
                     ("A1", "", None), (True, "", "D")]:
            with self.subTest(args=args), self.assertRaises(ipi.IdentidadInvalida):
                ipi.validar_identidad(*args)

    def test_rechaza_centinela_fail_que_el_lector_no_representa(self):
        with self.assertRaises(ipi.IdentidadInvalida):
            ipi.validar_identidad("Fail", "", "D")
        with self.assertRaises(ipi.IdentidadInvalida):
            ipi.validar_identidad("A1", "Fail", "D")

    def test_el_error_no_filtra_los_valores(self):
        with self.assertRaises(ipi.IdentidadInvalida) as cm:
            ipi.validar_identidad("A1", " " + SECRETO_REF, SECRETO_DESC)
        self.assertNotIn("SECRET", str(cm.exception))


class TestCompararYClasificar(unittest.TestCase):
    ESP = ipi.IdentidadEsperada("0075", "FAC-1", "ALICATE")

    def test_comparacion_exacta_sin_normalizar(self):
        ok = {"codigo": "0075", "referencia": "FAC-1", "descripcion": "ALICATE"}
        self.assertEqual(ipi.comparar(self.ESP, ok), ())
        self.assertEqual(ipi.comparar(self.ESP, dict(ok, codigo="75")), ("codigo",))
        self.assertEqual(ipi.comparar(self.ESP, dict(ok, referencia="fac-1")), ("referencia",))
        self.assertEqual(ipi.comparar(self.ESP, dict(ok, descripcion="Alicate")), ("descripcion",))
        self.assertEqual(ipi.comparar(self.ESP, {"codigo": "0075"}),
                         ("referencia", "descripcion"))

    def test_clasificar_ausente_coincide_y_discrepa(self):
        cat = {"ref_de": {"X": ""}, "desc_de": {"X": "x"}}
        self.assertEqual(ipi.clasificar_existencia(self.ESP, cat), ("ausente", ()))
        cat["ref_de"]["0075"], cat["desc_de"]["0075"] = "FAC-1", "OTRO"
        self.assertEqual(ipi.clasificar_existencia(self.ESP, cat), ("discrepa", ("descripcion",)))
        cat["ref_de"]["0075"] = ""
        self.assertEqual(ipi.clasificar_existencia(self.ESP, cat),
                         ("discrepa", ("referencia", "descripcion")))
        cat["ref_de"]["0075"], cat["desc_de"]["0075"] = "FAC-1", "ALICATE"
        self.assertEqual(ipi.clasificar_existencia(self.ESP, cat), ("coincide", ()))

    def test_codigo_con_otra_capitalizacion_discrepa(self):
        esp = ipi.IdentidadEsperada("abc-1", "", "D")
        cat = {"ref_de": {"ABC-1": ""}, "desc_de": {"ABC-1": "D"}}
        self.assertEqual(ipi.clasificar_existencia(esp, cat), ("discrepa", ("codigo",)))


class TestVerificarConReintentos(unittest.TestCase):
    ESP = ipi.IdentidadEsperada("A1", "R1", "D1")
    OK = {"codigo": "A1", "referencia": "R1", "descripcion": "D1"}

    def correr(self, lecturas, intentos=3):
        cola, dormidos, llamadas = list(lecturas), [], []

        def leer(codigo):
            llamadas.append(codigo)
            v = cola.pop(0)
            if isinstance(v, Exception):
                raise v
            return v

        v = ipi.verificar_con_reintentos(self.ESP, leer, intentos, 7, dormido(dormidos),
                                         (OSError,))
        return v, len(llamadas), dormidos

    def test_retraso_luego_coincide(self):
        v, lecturas, dormidos = self.correr([None, None, self.OK])
        self.assertEqual((v.estado, lecturas, dormidos), ("ok", 3, [7, 7]))

    def test_agotamiento_acotado_ausente(self):
        v, lecturas, dormidos = self.correr([None, None, None])
        self.assertEqual((v.estado, lecturas, dormidos), ("ausente", 3, [7, 7]))

    def test_discrepancia_persistente_lista_campos(self):
        mal = dict(self.OK, referencia="OTRA")
        v, lecturas, _ = self.correr([mal, mal, mal])
        self.assertEqual((v.estado, v.campos, lecturas), ("discrepa", ("referencia",), 3))

    def test_ilegible_agotado_y_recuperado(self):
        v, lecturas, _ = self.correr([OSError("h"), OSError("h"), OSError("h")])
        self.assertEqual((v.estado, lecturas), ("ilegible", 3))
        v, lecturas, _ = self.correr([OSError("h"), self.OK])
        self.assertEqual((v.estado, lecturas), ("ok", 2))

    def test_coincidencia_inmediata_no_duerme(self):
        v, lecturas, dormidos = self.correr([self.OK])
        self.assertEqual((v.estado, lecturas, dormidos), ("ok", 1, []))

    def test_otros_errores_no_se_tragan(self):
        with self.assertRaises(RuntimeError):
            self.correr([RuntimeError("bug")])


def dormido(registro):
    return registro.append


# ══ colisiones: fresh identity read ══════════════════════════════════════════
class TestColisionesLecturaFresca(FlujoBase):
    def test_identidad_fresca_ve_el_cambio_aunque_el_mtime_no_cambie(self):
        m = self.mundo
        self.col.os = types.SimpleNamespace(path=types.SimpleNamespace(getmtime=lambda p: 1.0))
        self.col._catalogo()  # Warm the legacy cache independently of strict reads.
        self.assertIsNone(self.col.identidad(CODIGO))
        m.catalogo[CODIGO] = (REFERENCIA, DESCRIPCION)            # mtime unchanged
        self.assertEqual(self.col._catalogo()["ref_de"].get(CODIGO), None)   # stale cache
        self.assertEqual(self.col.identidad(CODIGO),
                         {"codigo": CODIGO, "referencia": REFERENCIA, "descripcion": DESCRIPCION})

    def test_referencia_fail_se_lee_vacia_y_ausente_es_none(self):
        self.mundo.catalogo["P1"] = ("Fail", "desc")
        self.assertEqual(self.col._catalogo()["ref_de"]["P1"], "")
        self.assertIsNone(self.col.identidad("NO-EXISTE"))

    def test_referencia_fail_permanece_ilegible_en_identidad_estricta(self):
        self.sembrar(referencia="Fail")
        self.assertEqual(self.col.identidad(CODIGO)["referencia"], "Fail")
        self.assertEqual(self.col._catalogo()["ref_de"][CODIGO], "")

    def test_lectura_por_defecto_sigue_cacheada(self):
        self.col._catalogo()
        antes = self.mundo.lecturas
        self.col._catalogo()
        self.assertEqual(self.mundo.lecturas, antes)

    def test_catalogo_ilegible_se_propaga(self):
        self.mundo.fallo_lectura = OSError("H: caida")
        with self.assertRaises(self.col.CatalogoIlegible):
            self.col.identidad(CODIGO)


# ══ crear_producto ═══════════════════════════════════════════════════════════
class TestCrearProductoPorDefecto(FlujoBase):
    """Opt-in contract: without identidad_estricta the old behavior is unchanged."""

    def test_firma_estricta_desactivada_por_defecto(self):
        p = inspect.signature(self.fcr.crear_producto).parameters["identidad_estricta"]
        self.assertIs(p.default, False)
        p = inspect.signature(self.fcr.registrar_compra).parameters["identidad_estricta"]
        self.assertIs(p.default, False)

    def test_referencia_distinta_en_pantalla_sigue_siendo_solo_aviso(self):
        self.mundo.ui_forzada["referencia"] = "OTRA"
        res = self.crear()
        self.assertEqual(res["etapa"], "commit")
        self.assertEqual(self.mundo.n("guardar"), 1)

    def test_commit_no_lee_el_catalogo_de_identidad(self):
        res = self.crear()
        self.assertEqual(res["detalle"],
                         f"Producto {CODIGO} ({DESCRIPCION}) dado de alta y VERIFICADO en DB: "
                         f"existencia=0.0 costo=5.0 precio=8.0.")
        self.assertEqual(self.mundo.lecturas, 0)

    def test_campo_referencia_ausente_no_bloquea(self):
        self.mundo.sin_control.add("referencia")
        self.assertEqual(self.crear()["etapa"], "commit")

    def test_preview_mensaje_original(self):
        res = self.crear(commit=False)
        self.assertEqual(res["etapa"], "preview")
        self.assertEqual(res["detalle"],
                         f"Alta de {CODIGO} ({DESCRIPCION}) verificada en pantalla "
                         f"(costo=5.0, precio=8.0) y DESCARTADA (sin --commit; "
                         f"el producto NO quedó creado, así que este ítem no se compra en preview).")

    def test_normaliza_espacios_como_antes(self):
        res = self.crear(codigo=f" {CODIGO} ", referencia=f" {REFERENCIA} ")
        self.assertEqual(res["etapa"], "commit")
        self.assertIn(("escribir", "codigo", CODIGO), self.mundo.eventos)


class TestCrearProductoEstricto(FlujoBase):
    def test_nuevo_con_codigo_y_referencia_correctos(self):
        res = self.crear(identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (True, "commit"))
        self.assertIn("verificada en el catálogo con lectura fresca", res["detalle"])
        self.assertEqual(self.mundo.n("guardar"), 1)
        escritos = [e[1:] for e in self.mundo.eventos if e[0] == "escribir"]
        self.assertEqual(escritos, [("codigo", CODIGO), ("referencia", REFERENCIA),
                                    ("descripcion", DESCRIPCION)])

    def test_referencia_en_pantalla_distinta_no_guarda(self):
        self.mundo.ui_forzada["referencia"] = "OTRA"
        res = self.crear(identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "campos"))
        self.assertIn("referencia", res["detalle"])
        self.assertEqual(self.mundo.n("guardar"), 0)
        self.assertEqual(self.mundo.n("cancelar_ficha"), 1)
        self.assertEqual(self.mundo.n("abrir_costos_precios"), 0)

    def test_descripcion_o_codigo_en_pantalla_distintos_no_guardan_ni_filtran(self):
        for campo in ("descripcion", "codigo"):
            with self.subTest(campo=campo):
                self.setUp()
                self.mundo.ui_forzada[campo] = SECRETO_DESC
                res = self.crear(descripcion=SECRETO_DESC + "x", identidad_estricta=True)
                self.assertEqual((res["ok"], res["etapa"]), (False, "campos"))
                self.assertIn(campo, res["detalle"])
                self.assertNotIn("SECRET", res["detalle"])
                self.assertEqual(self.mundo.n("guardar"), 0)

    def test_control_de_referencia_ausente_bloquea(self):
        for referencia in (REFERENCIA, ""):
            with self.subTest(referencia=referencia):
                self.setUp()
                self.mundo.sin_control.add("referencia")
                res = self.crear(referencia=referencia, identidad_estricta=True)
                self.assertEqual((res["ok"], res["etapa"]), (False, "campos"))
                self.assertEqual(self.mundo.n("guardar"), 0)

    def test_referencia_vacia_esperada_exige_campo_vacio(self):
        res = self.crear(referencia=None, identidad_estricta=True)
        self.assertEqual(res["etapa"], "commit")
        self.setUp()
        self.mundo.ui["referencia"] = "PRELLENADO"
        res = self.crear(referencia=None, identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "campos"))
        self.assertEqual(self.mundo.n("guardar"), 0)

    def test_referencia_solo_espacios_no_cuenta_como_vacia_en_pantalla(self):
        for commit in (False, True):
            with self.subTest(commit=commit):
                self.setUp()
                self.mundo.ui["referencia"] = "   "
                res = self.crear(referencia=None, commit=commit, identidad_estricta=True)
                self.assertEqual((res["ok"], res["etapa"]), (False, "campos"))
                self.assertEqual(self.mundo.n("guardar"), 0)
                self.assertEqual(self.mundo.n("abrir_costos_precios"), 0)

    def test_referencia_fail_despues_de_guardar_no_verifica_un_vacio(self):
        self.mundo.persistida["referencia"] = "Fail"
        res = self.crear(referencia=None, identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "verificacion_db"))
        self.assertEqual(self.mundo.n("guardar"), 1)

    def test_valor_no_soportado_falla_antes_de_abrir_la_ficha(self):
        for kw in ({"codigo": "c" * 81}, {"referencia": "r" * 101}, {"referencia": f" {REFERENCIA}"},
                   {"descripcion": ""}, {"codigo": 12345}):
            with self.subTest(kw=kw):
                self.setUp()
                res = self.crear(identidad_estricta=True, **kw)
                self.assertEqual((res["ok"], res["etapa"]), (False, "campos"))
                self.assertEqual(self.mundo.n("abrir_ficha"), 0)
                self.assertEqual(self.mundo.eventos, [])

    def test_preview_no_confirma_nada_y_no_afirma_persistencia(self):
        res = self.crear(commit=False, identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (True, "preview"))
        self.assertIn("sin prueba de persistencia", res["detalle"])
        self.assertEqual(self.mundo.n("guardar"), 0)
        self.assertEqual(self.mundo.lecturas, 0)

    def test_retraso_de_lectura_luego_coincide_sin_guardar_dos_veces(self):
        self.mundo.retraso_inicial = 2
        res = self.crear(identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (True, "commit"))
        self.assertEqual(self.mundo.n("guardar"), 1)
        self.assertEqual(self.mundo.n("abrir_ficha"), 1)
        self.assertEqual(self.mundo.lecturas, 3)

    def test_agotamiento_acotado_no_recrea_ni_reintenta_guardado(self):
        self.mundo.retraso_inicial = 10 ** 6
        res = self.crear(identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "verificacion_db"))
        self.assertIn("no apareció", res["detalle"])
        self.assertEqual(self.mundo.lecturas, self.fcr.REINTENTOS_LECTURA_DB)
        self.assertEqual(self.mundo.n("guardar"), 1)
        self.assertEqual(self.mundo.n("abrir_ficha"), 1)

    def test_referencia_persistida_distinta_se_detecta_sin_filtrar_valores(self):
        self.mundo.persistida["referencia"] = SECRETO_REF
        res = self.crear(identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "verificacion_db"))
        self.assertIn("referencia", res["detalle"])
        self.assertNotIn("SECRET", res["detalle"])
        self.assertEqual(self.mundo.n("guardar"), 1)

    def test_catalogo_ilegible_tras_guardar_es_verificacion_indisponible(self):
        self.mundo.fallo_lectura = OSError("H: caida")
        res = self.crear(identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "verificacion_indisponible"))
        self.assertIn("identidad", res["detalle"])
        self.assertEqual(self.mundo.n("guardar"), 1)

    def test_numeros_ilegibles_conserva_etapa_y_avisa_que_la_identidad_no_se_verifico(self):
        self.mundo.numeros_error = self.fcr.VerificacionIndisponible("H: caida")
        res = self.crear(identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "verificacion_indisponible"))
        self.assertIn("identidad no verificada", res["detalle"])
        self.assertEqual(self.mundo.n("guardar"), 1)

    def test_semantica_numerica_igual_costo_distinto_sigue_fallando(self):
        self.mundo.numeros = (0.0, 9.0, 8.0)
        res = self.crear(identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "verificacion_db"))
        self.assertIn("costo en DB", res["detalle"])


# ══ registrar_compra ═════════════════════════════════════════════════════════
class TestRegistrarCompraPorDefecto(FlujoBase):
    def test_codigo_existente_con_descripcion_distinta_se_compra_como_existente(self):
        self.sembrar(descripcion="OTRA COSA", referencia="")
        it = self.item()
        res = self.comprar([it])
        self.assertTrue(res["ok"])
        self.assertEqual(self.mundo.n("abrir_ficha"), 0)
        self.assertEqual(self.mundo.n("cargar_item"), 1)
        self.assertFalse(it["es_nuevo"])
        self.assertEqual(self.mundo.lecturas, 1)   # only the collision pre-flight read

    def test_preview_mensaje_original_y_item_nuevo_no_se_carga(self):
        res = self.comprar([self.item()], commit=False)
        self.assertEqual(res["etapa"], "preview")
        self.assertEqual(res["detalle"],
                         "Preview de 1 ítem(s) verificado(s) en pantalla y DESCARTADO (sin "
                         "--commit; documento cancelado completo). Los ítems es_nuevo NO se "
                         "cargaron en la grilla (ver asimetría preview/commit en el docstring).")
        self.assertEqual(self.mundo.n("cargar_item"), 0)

    def test_valores_con_espacios_no_se_validan_como_antes(self):
        res = self.comprar([self.item(referencia=f" {REFERENCIA} ")])
        self.assertTrue(res["ok"])


class TestRegistrarCompraEstricta(FlujoBase):
    def espiar_lectura_fresca(self):
        llamadas = []
        original = self.col.catalogo_fresco
        self.col.catalogo_fresco = lambda: (llamadas.append(1), original())[1]
        return llamadas

    def test_producto_nuevo_se_crea_estricto_y_luego_se_compra(self):
        res = self.comprar([self.item()], identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (True, "commit"))
        self.assertEqual(self.mundo.n("guardar"), 1)
        self.assertEqual(self.mundo.n("cargar_item"), 1)
        self.assertIn(("escribir", "referencia", REFERENCIA), self.mundo.eventos)

    def test_codigo_existente_con_identidad_igual_no_recrea_y_se_compra(self):
        self.sembrar()
        it = self.item()
        res = self.comprar([it], identidad_estricta=True)
        self.assertTrue(res["ok"])
        self.assertEqual(self.mundo.n("abrir_ficha"), 0)
        self.assertEqual(self.mundo.n("guardar"), 0)
        self.assertEqual(self.mundo.n("cargar_item"), 1)
        self.assertFalse(it["es_nuevo"])

    def test_codigo_existente_con_identidad_distinta_falla_cerrado_sin_tocar_nada(self):
        casos = {
            "descripcion": dict(descripcion=SECRETO_DESC),
            "referencia": dict(referencia=SECRETO_REF),
            "ambos": dict(referencia="", descripcion=SECRETO_DESC),
        }
        for nombre, kw in casos.items():
            with self.subTest(caso=nombre):
                self.setUp()
                self.sembrar(**kw)
                res = self.comprar([self.item()], identidad_estricta=True)
                self.assertEqual((res["ok"], res["etapa"]), (False, "navegacion"))
                self.assertIn("Nada se tocó", res["detalle"])
                self.assertNotIn("SECRET", res["detalle"])
                for efecto in ("abrir_hybrid", "abrir_ficha", "guardar", "cargar_item",
                               "totalizar", "abrir_compras"):
                    self.assertEqual(self.mundo.n(efecto), 0, efecto)
                self.assertEqual(self.mundo.catalogo[CODIGO][1], kw.get("descripcion", DESCRIPCION))

    def test_referencia_fail_existente_no_verifica_un_vacio_antes_de_hybrid(self):
        self.sembrar(referencia="Fail")
        res = self.comprar([self.item(referencia=None)], identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "navegacion"))
        self.assertEqual(self.mundo.eventos, [])

    def test_duplicados_con_identidades_distintas_ya_se_rechazan_sin_efectos(self):
        for commit in (False, True):
            with self.subTest(commit=commit):
                self.setUp()
                self.sembrar(referencia="SECOND")
                items = [self.item(referencia="FIRST"), self.item(referencia="SECOND")]
                before = repr((self.mundo.catalogo, items))
                res = self.comprar(items, commit=commit, identidad_estricta=True)
                self.assertEqual((res["ok"], res["etapa"]), (False, "navegacion"))
                self.assertEqual(self.mundo.eventos, [])
                self.assertEqual(repr((self.mundo.catalogo, items)), before)

    def test_campo_discrepante_se_nombra(self):
        self.sembrar(descripcion="OTRA")
        res = self.comprar([self.item()], identidad_estricta=True)
        self.assertIn("descripcion", res["detalle"])
        self.assertNotIn("referencia", res["detalle"])

    def test_codigo_existente_con_otra_capitalizacion_falla_cerrado(self):
        self.sembrar(codigo=CODIGO.lower().replace("0075", "ab75"))
        res = self.comprar([self.item(codigo="AB75912345678")], identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "navegacion"))
        self.assertEqual(self.mundo.n("abrir_ficha"), 0)

    def test_existe_solo_cuenta_si_la_identidad_se_verifico(self):
        # The master lookup claims the code exists, but the verified catalog snapshot says
        # it does not: strict mode must not treat an unverified existence as "already created".
        self.fcr.hpw._db_precio_usd = lambda c: 10.0
        res = self.comprar([self.item()], identidad_estricta=True)
        self.assertTrue(res["ok"])
        self.assertEqual(self.mundo.n("abrir_ficha"), 1)
        self.assertEqual(self.mundo.n("guardar"), 1)

    def test_un_conflicto_aborta_todas_las_altas_antes_de_crear_ninguna(self):
        self.sembrar(codigo="999", referencia="", descripcion="OTRA")
        items = [self.item(), self.item(codigo="999")]
        res = self.comprar(items, identidad_estricta=True)
        self.assertFalse(res["ok"])
        self.assertEqual(self.mundo.n("abrir_ficha"), 0)
        self.assertEqual(self.mundo.n("guardar"), 0)

    def test_catalogo_ilegible_en_la_verificacion_previa_falla_cerrado(self):
        self.mundo.fallo_lectura = OSError("H: caida")
        res = self.comprar([self.item()], identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "navegacion"))
        self.assertIn("Nada se tocó", res["detalle"])
        self.assertEqual(self.mundo.n("abrir_hybrid"), 0)

    def test_valor_no_soportado_falla_antes_de_abrir_hybrid(self):
        for kw in ({"referencia": f" {REFERENCIA}"}, {"codigo": "c" * 81}, {"referencia": "r" * 101}):
            with self.subTest(kw=kw):
                self.setUp()
                res = self.comprar([self.item(**kw)], identidad_estricta=True)
                self.assertEqual((res["ok"], res["etapa"]), (False, "navegacion"))
                self.assertEqual(self.mundo.n("abrir_hybrid"), 0)
                self.assertEqual(self.mundo.lecturas, 0)

    def test_alta_con_lectura_agotada_cancela_la_compra_sin_comprar(self):
        self.mundo.retraso_inicial = 10 ** 6
        res = self.comprar([self.item()], identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "alta_producto:verificacion_db"))
        self.assertEqual(self.mundo.n("guardar"), 1)
        for efecto in ("cargar_item", "totalizar", "abrir_compras"):
            self.assertEqual(self.mundo.n(efecto), 0, efecto)

    def test_alta_con_referencia_persistida_distinta_cancela_la_compra(self):
        self.mundo.persistida["referencia"] = "OTRA"
        res = self.comprar([self.item()], identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "alta_producto:verificacion_db"))
        self.assertEqual(self.mundo.n("totalizar"), 0)

    def test_preview_estricto_no_guarda_no_carga_y_no_afirma_persistencia(self):
        res = self.comprar([self.item()], commit=False, identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (True, "preview"))
        self.assertIn("sin prueba de persistencia", res["detalle"])
        self.assertEqual(self.mundo.n("guardar"), 0)
        self.assertEqual(self.mundo.n("cargar_item"), 0)

    def test_preview_estricto_tambien_falla_cerrado_con_identidad_distinta(self):
        self.sembrar(descripcion="OTRA")
        res = self.comprar([self.item()], commit=False, identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "navegacion"))

    def test_sin_productos_nuevos_no_hace_lectura_fresca_ni_cambia_el_flujo(self):
        llamadas = self.espiar_lectura_fresca()
        res = self.comprar([self.item(es_nuevo=False, codigo="SEED-1", referencia=None,
                                      descripcion=None)], identidad_estricta=True)
        self.assertTrue(res["ok"])
        self.assertEqual(llamadas, [])
        self.assertEqual(self.mundo.n("cargar_item"), 1)

    def test_lectura_previa_es_fresca_aunque_el_mtime_no_cambie(self):
        self.col.os = types.SimpleNamespace(path=types.SimpleNamespace(getmtime=lambda p: 1.0))
        self.col._catalogo()                                  # warms a stale cache
        self.mundo.catalogo[CODIGO] = (REFERENCIA, "OTRA")    # appears without mtime change
        res = self.comprar([self.item()], identidad_estricta=True)
        self.assertEqual((res["ok"], res["etapa"]), (False, "navegacion"))


if __name__ == "__main__":
    unittest.main()
