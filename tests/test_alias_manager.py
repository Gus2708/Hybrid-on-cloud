"""Tests de alias_manager: equivalencias de códigos de proveedores vs HybridLiteOS.
"""
import os
import sys
import json
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hybrid_writeback")))
import alias_manager as am


@pytest.fixture
def temp_alias_file(tmp_path, monkeypatch):
    """Crea un archivo temporal de alias aislado para no tocar el de producción."""
    p = tmp_path / "test_alias.json"
    data = {
        "THINNER-01": {
            "codigo_sistema": "THINNER-M",
            "proveedor": "FLORIPAINT",
            "descripcion": "SOLVENTE MULTIUSO FLORIPAINT"
        },
        "OLD-001": "NEW-001"
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(am, "RUTA_ALIAS", str(p))
    return p


def test_resolver_alias_existente_con_proveedor(temp_alias_file):
    res = am.resolver_alias("THINNER-01", proveedor="FLORIPAINT")
    assert res == "THINNER-M"


def test_resolver_alias_existente_sin_proveedor(temp_alias_file):
    res = am.resolver_alias("THINNER-01")
    assert res == "THINNER-M"


def test_resolver_alias_string_simple(temp_alias_file):
    res = am.resolver_alias("OLD-001")
    assert res == "NEW-001"


def test_resolver_alias_no_coincide_proveedor(temp_alias_file):
    res = am.resolver_alias("THINNER-01", proveedor="OTRO_PROVEEDOR")
    assert res == "THINNER-01"


def test_resolver_alias_no_registrado(temp_alias_file):
    res = am.resolver_alias("F-401-01")
    assert res == "F-401-01"


def test_resolver_alias_espacios_en_blanco(temp_alias_file):
    res = am.resolver_alias("  THINNER-01  ")
    assert res == "THINNER-M"


def test_resolver_alias_valores_vacios(temp_alias_file):
    assert am.resolver_alias("") == ""
    assert am.resolver_alias(None) is None


def test_resolver_alias_sin_archivo(tmp_path, monkeypatch):
    monkeypatch.setattr(am, "RUTA_ALIAS", str(tmp_path / "inexistente.json"))
    assert am.resolver_alias("THINNER-01") == "THINNER-01"


def test_resolver_alias_archivo_corrupto(tmp_path, monkeypatch):
    corrupto = tmp_path / "corrupto.json"
    corrupto.write_text("ESTO NO ES UN JSON", encoding="utf-8")
    monkeypatch.setattr(am, "RUTA_ALIAS", str(corrupto))
    assert am.resolver_alias("THINNER-01") == "THINNER-01"


def test_registrar_alias_nuevo(tmp_path, monkeypatch):
    p = tmp_path / "nuevo_alias.json"
    monkeypatch.setattr(am, "RUTA_ALIAS", str(p))
    
    ok = am.registrar_alias(
        "PROV-999",
        "SYS-999",
        proveedor="TEST_PROV",
        descripcion="Producto de prueba"
    )
    assert ok is True
    assert p.exists()
    
    res = am.resolver_alias("PROV-999", proveedor="TEST_PROV")
    assert res == "SYS-999"
