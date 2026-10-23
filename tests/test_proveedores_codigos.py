"""Supplier listeners: model codes inside the description are tried as exact codes."""
import importlib.util
import os

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _load(name):
    path = os.path.join(ROOT, "microservicios", name, f"{name}_listener.py")
    spec = importlib.util.spec_from_file_location(f"{name}_listener", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LISTENERS = [_load("maxcam"), _load("corpnorte")]


@pytest.mark.parametrize("listener", LISTENERS, ids=["maxcam", "corpnorte"])
class TestCodigosEnDescripcion:
    def test_extrae_codigos_de_modelo(self, listener):
        assert listener.codigos_en_descripcion("APAGADOR C/TOMA ACRILICO VERDE TROEN TR-ATG-1K1C") == ["TR-ATG-1K1C"]

    def test_extrae_codigos_sin_guion(self, listener):
        assert listener.codigos_en_descripcion("CERRADURA AUXILIAR DT102AC BRONCE") == ["DT102AC"]

    def test_ignora_medidas_y_palabras(self, listener):
        assert listener.codigos_en_descripcion("TUBO HERRERIA 2X1X0.80X6MTS 42.5KG 3/4 1/2\" 10A CEMENTO") == []

    def test_sin_descripcion(self, listener):
        assert listener.codigos_en_descripcion(None) == []


@pytest.mark.parametrize("listener", LISTENERS, ids=["maxcam", "corpnorte"])
def test_resolver_manda_los_codigos_de_la_descripcion(listener, monkeypatch):
    producto = {"codigo_interno": "00312", "codigo_barras": "7453078513560", "referencia": "7453078513560",
                "descripcion": "APAGADOR C/TOMA ACRILICO VERDE TROEN TR-ATG-1K1C"}
    pedidos = []

    def fake_http(method, url, headers=None, body=None, timeout=30):
        if "/rest/v1/productos" in url:
            return [producto]
        if "/disponibilidad" in url:
            pedidos.append(url)
            return {"encontrado": "TR-ATG-1K1C" in url, "disponible": True}
        raise AssertionError(f"no debe caer a similitud: {url}")

    monkeypatch.setattr(listener, "http", fake_http)
    monkeypatch.setattr(listener, "candidato", lambda info, similitud, *a: {"similitud": similitud})

    resultado = listener.resolver("00312")

    assert resultado == {"metodo": "codigo", "candidatos": [{"similitud": 1.0}]}
    assert len(pedidos) == 1
