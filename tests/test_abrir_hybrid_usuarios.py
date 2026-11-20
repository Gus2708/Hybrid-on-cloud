import json
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HW_DIR = os.path.join(BASE_DIR, "hybrid_writeback")
if HW_DIR not in sys.path:
    sys.path.insert(0, HW_DIR)

import abrir_hybrid as ah
import listener_base as lb
import listener_compras as lc
import listener_directorio as ld
import listener_pedidos as lp
import listener_writeback as lw


GUSTAVO_UUID = "ca1d0a1f-c4e1-475a-89bb-728e3afad076"
OTRO_UUID = "9554912e-b6c2-4484-92f9-88b01ba92a95"


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    conf = tmp_path / "hybrid_login.json"
    sesiones = tmp_path / "hybrid_sesiones.json"
    conf.write_text(
        json.dumps(
            {
                "usuario": "SU",
                "clave": "test-default-pass",
                "usuarios_app": {
                    GUSTAVO_UUID: {
                        "nombre": "Gustavo",
                        "usuario": "TEST_GUS",
                        "clave": "test-gus-pass",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ah, "CONF", str(conf))
    monkeypatch.setattr(ah, "SESIONES_FILE", str(sesiones))
    monkeypatch.setattr(ah, "_AISLADO_PID", None)
    monkeypatch.setattr(ah, "_AISLADO_USUARIO", None)
    monkeypatch.setattr(ah, "_LANZADA_POR_NOSOTROS", False)
    monkeypatch.setattr(ah, "_CREADO_POR_ACTIVO", None)
    ah.fp.clear_target_pid()
    yield {"conf": conf, "sesiones": sesiones}
    ah.fp.clear_target_pid()


class TestResolucionCredenciales:
    def test_uuid_mapeado_resuelve_usuario_dedicado_case_insensitive(self, isolated_env):
        u, c, ded = ah._resolver_credenciales(GUSTAVO_UUID.upper())
        assert (u, c, ded) == ("TEST_GUS", "test-gus-pass", True)
        assert ah._creds(GUSTAVO_UUID) == ("TEST_GUS", "test-gus-pass")
        assert ah.usuario_hybrid_para(GUSTAVO_UUID) == "TEST_GUS"

    def test_uuid_no_mapeado_o_none_usa_default(self, isolated_env):
        assert ah._resolver_credenciales(OTRO_UUID) == ("SU", "test-default-pass", False)
        assert ah._resolver_credenciales(None) == ("SU", "test-default-pass", False)
        assert ah.usuario_hybrid_para(OTRO_UUID) == "SU"

    def test_conf_faltante_o_corrupto_cae_a_defaults(self, isolated_env, monkeypatch):
        isolated_env["conf"].write_text("{corrupt", encoding="utf-8")
        assert ah._resolver_credenciales(GUSTAVO_UUID) == (
            ah.DEFAULTS["usuario"],
            ah.DEFAULTS["clave"],
            False,
        )

        isolated_env["conf"].unlink()
        assert ah._resolver_credenciales(None) == (
            ah.DEFAULTS["usuario"],
            ah.DEFAULTS["clave"],
            False,
        )

    def test_sesion_para_restaura_contexto_incluso_con_excepcion(self, isolated_env):
        assert ah._CREADO_POR_ACTIVO is None
        with ah.sesion_para(OTRO_UUID):
            assert ah._CREADO_POR_ACTIVO == OTRO_UUID
            with pytest.raises(RuntimeError):
                with ah.sesion_para(GUSTAVO_UUID):
                    assert ah._CREADO_POR_ACTIVO == GUSTAVO_UUID
                    raise RuntimeError("boom")
            assert ah._CREADO_POR_ACTIVO == OTRO_UUID
        assert ah._CREADO_POR_ACTIVO is None


class TestAislamientoSesionesHybrid:
    def test_usuario_dedicado_no_adopta_ventana_sin_sesion_y_lanza_propia(self, isolated_env, monkeypatch):
        real_exists = os.path.exists
        monkeypatch.setattr(ah.os.path, "exists", lambda p: True if p == ah.EXE else real_exists(p))
        monkeypatch.setattr(ah.hh, "recuperar_si_colgado", lambda: ("sano", None))
        monkeypatch.setattr(ah, "_instancia_aislada_viva", lambda: (None, None))
        monkeypatch.setattr(ah.fp, "_find_hwnd", lambda cls: 100 if cls == ah.MAIN else None)
        monkeypatch.setattr(ah, "_pid_de", lambda hwnd: 10 if hwnd == 100 else 20)
        monkeypatch.setattr(ah.hh, "verificar_hybrid_listo", lambda target_pid=None: (True, "listo", []))
        monkeypatch.setattr(ah.fp, "_hwnds_de_clase", lambda cls: set())
        monkeypatch.setattr(ah.hh, "pids_hybrid", lambda: set())
        monkeypatch.setattr(ah.subprocess, "Popen", lambda *a, **kw: None)
        monkeypatch.setattr(
            ah.fp,
            "_esperar_ventana_nueva",
            lambda cls, antes, timeout=60: 200 if cls == ah.LOGIN else None,
        )

        login_calls = []

        def _fake_login(hlogin=None, timeout_main=60, antes_main=None, usuario=None, clave=None):
            login_calls.append((hlogin, usuario, clave))
            ah._AISLADO_PID = 20
            ah._AISLADO_USUARIO = usuario
            return True, f"Sesión iniciada ({usuario})"

        monkeypatch.setattr(ah, "hacer_login", _fake_login)

        with ah.sesion_para(GUSTAVO_UUID):
            ok, _ = ah.asegurar_hybrid()

        assert ok is True
        assert login_calls == [(200, "TEST_GUS", "test-gus-pass")]
        assert ah._AISLADO_PID == 20

    def test_usuario_dedicado_adopta_ventana_registrada_para_el_mismo_usuario(self, isolated_env, monkeypatch):
        isolated_env["sesiones"].write_text(json.dumps({"30": "TEST_GUS"}), encoding="utf-8")
        monkeypatch.setattr(ah.hh, "recuperar_si_colgado", lambda: ("sano", None))
        monkeypatch.setattr(ah, "_instancia_aislada_viva", lambda: (None, None))
        # First visible MAIN belongs to unmapped employee (hwnd 100 -> pid 10); hwnd 300 -> pid 30 is TEST_GUS
        monkeypatch.setattr(ah.fp, "_find_hwnd", lambda cls: 100 if cls == ah.MAIN else None)
        monkeypatch.setattr(ah.fp, "_hwnds_de_clase", lambda cls: {100, 300} if cls == ah.MAIN else set())
        monkeypatch.setattr(ah, "_pid_de", lambda hwnd: {100: 10, 300: 30}.get(hwnd))
        monkeypatch.setattr(ah.hh, "verificar_hybrid_listo", lambda target_pid=None: (True, "listo", []))
        popen_calls = []
        monkeypatch.setattr(ah.subprocess, "Popen", lambda *a, **kw: popen_calls.append(a))

        with ah.sesion_para(GUSTAVO_UUID):
            ok, msg = ah.asegurar_hybrid()

        assert ok is True
        assert "TEST_GUS" in msg
        assert ah._AISLADO_PID == 30
        assert ah._AISLADO_USUARIO == "TEST_GUS"
        assert ah._LANZADA_POR_NOSOTROS is False
        assert popen_calls == []

    def test_usuario_default_no_adopta_ventana_registrada_de_gus(self, isolated_env, monkeypatch):
        isolated_env["sesiones"].write_text(json.dumps({"30": "TEST_GUS"}), encoding="utf-8")
        real_exists = os.path.exists
        monkeypatch.setattr(ah.os.path, "exists", lambda p: True if p == ah.EXE else real_exists(p))
        monkeypatch.setattr(ah.hh, "recuperar_si_colgado", lambda: ("sano", None))
        monkeypatch.setattr(ah, "_instancia_aislada_viva", lambda: (None, None))
        monkeypatch.setattr(ah.fp, "_find_hwnd", lambda cls: 300 if cls == ah.MAIN else None)
        monkeypatch.setattr(ah.fp, "_hwnds_de_clase", lambda cls: {300} if cls == ah.MAIN else set())
        monkeypatch.setattr(ah, "_pid_de", lambda hwnd: {300: 30, 400: 40}.get(hwnd))
        monkeypatch.setattr(ah.hh, "verificar_hybrid_listo", lambda target_pid=None: (True, "listo", []))
        monkeypatch.setattr(ah.hh, "pids_hybrid", lambda: set())
        monkeypatch.setattr(ah.subprocess, "Popen", lambda *a, **kw: None)
        monkeypatch.setattr(
            ah.fp,
            "_esperar_ventana_nueva",
            lambda cls, antes, timeout=60: 400 if cls == ah.LOGIN else None,
        )

        login_calls = []
        monkeypatch.setattr(
            ah,
            "hacer_login",
            lambda hlogin=None, timeout_main=60, antes_main=None, usuario=None, clave=None: (
                login_calls.append(usuario),
                (True, "ok"),
            )[1],
        )

        with ah.sesion_para(OTRO_UUID):
            ok, _ = ah.asegurar_hybrid()

        assert ok is True
        assert login_calls == ["SU"]

    def test_cambio_de_usuario_en_instancia_propia_cierra_y_relanza(self, isolated_env, monkeypatch):
        real_exists = os.path.exists
        monkeypatch.setattr(ah.os.path, "exists", lambda p: True if p == ah.EXE else real_exists(p))
        ah._AISLADO_PID = 11
        ah._AISLADO_USUARIO = "SU"
        ah._LANZADA_POR_NOSOTROS = True

        monkeypatch.setattr(ah.hh, "recuperar_si_colgado", lambda: ("sano", None))
        monkeypatch.setattr(ah, "_instancia_aislada_viva", lambda: (ah.MAIN, 111))
        monkeypatch.setattr(ah.fp, "_find_hwnd", lambda cls: None)
        monkeypatch.setattr(ah.fp, "_hwnds_de_clase", lambda cls: set())
        monkeypatch.setattr(ah.hh, "pids_hybrid", lambda: set())
        monkeypatch.setattr(ah.subprocess, "Popen", lambda *a, **kw: None)
        monkeypatch.setattr(
            ah.fp,
            "_esperar_ventana_nueva",
            lambda cls, antes, timeout=60: 222 if cls == ah.LOGIN else None,
        )
        monkeypatch.setattr(ah, "_pid_de", lambda hwnd: 22 if hwnd == 222 else None)

        cerradas = []
        monkeypatch.setattr(
            ah,
            "cerrar_aislada",
            lambda: (
                cerradas.append(ah._AISLADO_PID),
                setattr(ah, "_AISLADO_PID", None),
                setattr(ah, "_AISLADO_USUARIO", None),
                setattr(ah, "_LANZADA_POR_NOSOTROS", False),
            ),
        )
        monkeypatch.setattr(
            ah,
            "hacer_login",
            lambda hlogin=None, timeout_main=60, antes_main=None, usuario=None, clave=None: (
                True,
                f"ok {usuario}",
            ),
        )

        with ah.sesion_para(GUSTAVO_UUID):
            ok, msg = ah.asegurar_hybrid()

        assert ok is True
        assert "TEST_GUS" in msg
        assert cerradas == [11]

    def test_cambio_de_usuario_en_instancia_adoptada_desacopla_sin_matar(self, isolated_env, monkeypatch):
        real_exists = os.path.exists
        monkeypatch.setattr(ah.os.path, "exists", lambda p: True if p == ah.EXE else real_exists(p))
        ah._AISLADO_PID = 15
        ah._AISLADO_USUARIO = "SU"
        ah._LANZADA_POR_NOSOTROS = False

        monkeypatch.setattr(ah.hh, "recuperar_si_colgado", lambda: ("sano", None))
        monkeypatch.setattr(ah, "_instancia_aislada_viva", lambda: (ah.MAIN, 150))
        monkeypatch.setattr(ah.fp, "_find_hwnd", lambda cls: None)
        monkeypatch.setattr(ah.fp, "_hwnds_de_clase", lambda cls: set())
        monkeypatch.setattr(ah.hh, "pids_hybrid", lambda: set())
        monkeypatch.setattr(ah.subprocess, "Popen", lambda *a, **kw: None)
        monkeypatch.setattr(
            ah.fp,
            "_esperar_ventana_nueva",
            lambda cls, antes, timeout=60: 250 if cls == ah.LOGIN else None,
        )
        monkeypatch.setattr(ah, "_pid_de", lambda hwnd: 25 if hwnd == 250 else None)

        cerradas = []
        monkeypatch.setattr(ah, "cerrar_aislada", lambda: cerradas.append(True))
        monkeypatch.setattr(
            ah,
            "hacer_login",
            lambda hlogin=None, timeout_main=60, antes_main=None, usuario=None, clave=None: (
                True,
                f"ok {usuario}",
            ),
        )

        with ah.sesion_para(GUSTAVO_UUID):
            ok, _ = ah.asegurar_hybrid()

        assert ok is True
        assert cerradas == []

    def test_fast_path_ficha_ignora_ficha_de_otro_usuario(self, isolated_env, monkeypatch):
        isolated_env["sesiones"].write_text(json.dumps({"10": "SU"}), encoding="utf-8")
        real_exists = os.path.exists
        monkeypatch.setattr(ah.os.path, "exists", lambda p: True if p == ah.EXE else real_exists(p))
        monkeypatch.setattr(ah.fp, "_find_hwnd", lambda cls: 900 if cls == ah.fp.FICHA_CLASS else None)
        monkeypatch.setattr(ah.hh, "responde", lambda hwnd, timeout_ms=100: True)
        monkeypatch.setattr(ah, "_pid_de", lambda hwnd: 10 if hwnd == 900 else 20)
        monkeypatch.setattr(ah.hh, "recuperar_si_colgado", lambda: ("sano", None))
        monkeypatch.setattr(ah, "_instancia_aislada_viva", lambda: (None, None))
        monkeypatch.setattr(ah.fp, "_hwnds_de_clase", lambda cls: set())
        monkeypatch.setattr(ah.hh, "pids_hybrid", lambda: set())
        monkeypatch.setattr(ah.subprocess, "Popen", lambda *a, **kw: None)
        monkeypatch.setattr(
            ah.fp,
            "_esperar_ventana_nueva",
            lambda cls, antes, timeout=60: 999 if cls == ah.LOGIN else None,
        )
        login_users = []
        monkeypatch.setattr(
            ah,
            "hacer_login",
            lambda hlogin=None, timeout_main=60, antes_main=None, usuario=None, clave=None: (
                login_users.append(usuario),
                (True, "ok"),
            )[1],
        )

        with ah.sesion_para(GUSTAVO_UUID):
            ok, _ = ah.asegurar_hybrid()

        assert ok is True
        assert login_users == ["TEST_GUS"]


class TestListenersSesionPorUsuario:
    def test_listener_writeback_agrupa_por_usuario_y_cierra_ficha_entre_grupos(self, isolated_env, monkeypatch):
        seen_sessions = []
        ficha_closes = []

        monkeypatch.setattr(lb, "check_hybrid_write_enabled", lambda: True)
        monkeypatch.setattr(lw, "update_item", lambda iid, **kwargs: True)
        monkeypatch.setattr(lw, "_tiene_costo_cambio", lambda item, cache: False)
        monkeypatch.setattr(
            lw,
            "_fase_stock_orden",
            lambda items_con_stock, orden_id=None: (
                seen_sessions.append((orden_id, ah._CREADO_POR_ACTIVO, ah.usuario_hybrid_para(ah._CREADO_POR_ACTIVO))),
                {
                    it["id"]: {"ok": True, "etapa": "commit", "detalle": "OK"}
                    for it in items_con_stock
                },
            )[1],
        )
        monkeypatch.setattr(lw.flujo_stock_real, "_cerrar_ficha_si_abierta", lambda: ficha_closes.append(True))
        monkeypatch.setattr(ah, "minimizar_aislada", lambda: None)

        items = [
            {
                "id": 1,
                "orden_id": 100,
                "codigo_producto": "A",
                "delta": 5,
                "nueva_existencia": 10,
                "ordenes_cambio": {"status": "emitido", "creado_por": GUSTAVO_UUID},
            },
            {
                "id": 2,
                "orden_id": 101,
                "codigo_producto": "B",
                "delta": -2,
                "nueva_existencia": 8,
                "ordenes_cambio": {"status": "emitido", "creado_por": OTRO_UUID},
            },
            {
                "id": 3,
                "orden_id": 102,
                "codigo_producto": "C",
                "delta": 1,
                "nueva_existencia": 3,
                "ordenes_cambio": {"status": "emitido", "creado_por": GUSTAVO_UUID},
            },
        ]

        lw._procesar_pendientes_impl(items)

        assert seen_sessions == [
            (100, GUSTAVO_UUID, "TEST_GUS"),
            (102, GUSTAVO_UUID, "TEST_GUS"),
            (101, OTRO_UUID, "SU"),
        ]
        assert len(ficha_closes) == 2
        assert ah._CREADO_POR_ACTIVO is None

    def test_listener_compras_pasa_creado_por_a_sesion(self, isolated_env, monkeypatch):
        observed = []
        monkeypatch.setattr(lb, "check_hybrid_write_enabled", lambda: True)
        monkeypatch.setattr(lc, "control_seguro", None)
        monkeypatch.setattr(lc, "update_compra", lambda cid, **kw: True)
        monkeypatch.setattr(lc, "get_items", lambda cid: [{"codigo": "01", "cantidad": 2, "costo": 1.0, "precio": 2.0}])
        monkeypatch.setattr(
            lc.flujo_compra_real,
            "registrar_compra",
            lambda *a, **kw: (
                observed.append((ah._CREADO_POR_ACTIVO, ah.usuario_hybrid_para(ah._CREADO_POR_ACTIVO))),
                {"ok": True, "etapa": "commit", "detalle": "OK"},
            )[1],
        )

        lc.procesar_compra(
            {
                "id": 55,
                "creado_por": GUSTAVO_UUID,
                "proveedor_codigo": "P1",
                "proveedor_nombre": "PROV",
                "backend_intentos": 0,
            }
        )

        assert observed == [(GUSTAVO_UUID, "TEST_GUS")]
        assert ah._CREADO_POR_ACTIVO is None

    def test_listener_pedidos_pasa_creado_por_a_sesion(self, isolated_env, monkeypatch):
        observed = []
        monkeypatch.setattr(lb, "check_hybrid_write_enabled", lambda: True)
        monkeypatch.setattr(lp, "control_seguro", None)
        monkeypatch.setattr(lp, "update_pedido", lambda pid, **kw: True)
        monkeypatch.setattr(lp, "get_items", lambda pid: [{"codigo": "01", "cantidad": 2, "precio": None}])
        monkeypatch.setattr(
            lp.flujo_pedido_real,
            "registrar_pedido",
            lambda *a, **kw: (
                observed.append((ah._CREADO_POR_ACTIVO, ah.usuario_hybrid_para(ah._CREADO_POR_ACTIVO))),
                {"ok": True, "etapa": "commit", "detalle": "OK", "documento": "0001"},
            )[1],
        )

        lp.procesar_pedido(
            {
                "id": 88,
                "creado_por": GUSTAVO_UUID,
                "cliente_codigo": "C1",
                "cliente_nombre": "CLI",
                "backend_intentos": 0,
            }
        )

        assert observed == [(GUSTAVO_UUID, "TEST_GUS")]
        assert ah._CREADO_POR_ACTIVO is None

    def test_listener_directorio_pasa_creado_por_a_sesion(self, isolated_env, monkeypatch):
        observed = []
        monkeypatch.setattr(lb, "check_hybrid_write_enabled", lambda: True)
        monkeypatch.setattr(ld, "update_fila", lambda *a, **kw: True)
        monkeypatch.setattr(
            ld.flujo_directorio_real,
            "registrar",
            lambda *a, **kw: (
                observed.append((ah._CREADO_POR_ACTIVO, ah.usuario_hybrid_para(ah._CREADO_POR_ACTIVO))),
                {"ok": True, "etapa": "commit", "detalle": "OK", "codigo": "J123"},
            )[1],
        )

        ld.procesar_registro(
            {
                "id": 99,
                "_tipo": "cliente",
                "creado_por": GUSTAVO_UUID,
                "nombre": "CLIENTE TEST",
                "rif": "J123",
                "backend_intentos": 0,
            }
        )

        assert observed == [(GUSTAVO_UUID, "TEST_GUS")]
        assert ah._CREADO_POR_ACTIVO is None
