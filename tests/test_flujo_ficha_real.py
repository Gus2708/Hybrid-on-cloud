"""tests/test_flujo_ficha_real.py — Tests unitarios y de regresión para flujo_ficha_real.set_ficha."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hybrid_writeback")))
import abrir_hybrid
import flujo_ficha_real as ffr
import flujo_compra_real as fcr


class _FakeRect:
    left, top, right, bottom = 100, 190, 526, 215


class _FakeEdit:
    def __init__(self, text="", *, read_only=False):
        self.text = text
        self.cursor = len(text)
        self.read_only = read_only

    def rectangle(self):
        return _FakeRect()

    def set_focus(self):
        pass

    def window_text(self):
        return self.text


def _patch_ficha_env(monkeypatch, desc_ctrl):
    estado = {"guardado": 0, "cancelado": 0}

    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(abrir_hybrid, "asegurar_hybrid", lambda: (True, "OK"))
    monkeypatch.setattr(ffr.fpr, "_cerrar_residuales", lambda: None)
    monkeypatch.setattr(ffr.fpr, "cargar_producto", lambda codigo: None)
    monkeypatch.setattr(ffr.fpr, "_guardar_ficha", lambda: estado.__setitem__("guardado", estado["guardado"] + 1))
    monkeypatch.setattr(ffr.fp, "_find_hwnd", lambda cls: 9001 if cls == ffr.fp.FICHA_CLASS else None)
    monkeypatch.setattr(fcr, "_campos_ficha", lambda hf: {"codigo": None, "referencia": None, "descripcion": desc_ctrl})
    monkeypatch.setattr(fcr, "_cancelar_ficha_alta", lambda hf: estado.__setitem__("cancelado", estado["cancelado"] + 1))

    monkeypatch.setattr(fcr.ri, "click", lambda x, y: None)
    monkeypatch.setattr(fcr.ri, "select_all_field", lambda: None)
    monkeypatch.setattr(fcr.ri, "press", lambda name, hold=0.02: None)
    monkeypatch.setattr(fcr.ri, "clear_field", lambda: None)

    def fake_clear_hard(n=8):
        if not desc_ctrl.read_only:
            desc_ctrl.text = desc_ctrl.text[:-n] if n < len(desc_ctrl.text) else ""
            desc_ctrl.text = desc_ctrl.text[n:] if n < len(desc_ctrl.text) else ""
            desc_ctrl.cursor = 0

    def fake_type_text(valor, **kw):
        if not desc_ctrl.read_only:
            desc_ctrl.text = desc_ctrl.text[:desc_ctrl.cursor] + valor + desc_ctrl.text[desc_ctrl.cursor:]
            desc_ctrl.cursor += len(valor)

    monkeypatch.setattr(fcr.ri, "clear_hard", fake_clear_hard)
    monkeypatch.setattr(fcr.ri, "type_text", fake_type_text)
    return estado


def test_set_ficha_updates_long_description_and_commits(monkeypatch):
    """Regresión OC-35974: actualiza descripción larga en modo Modificar y guarda."""
    viejo = "CURVA 90GR PVC CONDUIT 3/4"
    nuevo = "CURVA 90GR PVC CONDUIT 3/4 PAVCO"
    desc_ctrl = _FakeEdit(viejo)
    estado = _patch_ficha_env(monkeypatch, desc_ctrl)

    res = ffr.set_ficha("01567", nueva_descripcion=nuevo, commit=True)

    assert res["ok"] is True
    assert res["etapa"] == "commit"
    assert desc_ctrl.text == nuevo
    assert estado["guardado"] == 1
    assert estado["cancelado"] == 0


def test_set_ficha_cancels_without_saving_when_field_cannot_clear(monkeypatch):
    """Si el campo de descripción no se deja vaciar, cancela la Ficha sin guardar."""
    viejo = "CURVA 90GR PVC CONDUIT 3/4"
    nuevo = "CURVA 90GR PVC CONDUIT 3/4 PAVCO"
    desc_ctrl = _FakeEdit(viejo, read_only=True)
    estado = _patch_ficha_env(monkeypatch, desc_ctrl)

    res = ffr.set_ficha("01567", nueva_descripcion=nuevo, commit=True)

    assert res["ok"] is False
    assert res["etapa"] == "escritura"
    assert viejo in res["detalle"]
    assert estado["cancelado"] == 1
    assert estado["guardado"] == 0
