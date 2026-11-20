import json
import sys
import types
from types import SimpleNamespace

import pytest

import bot_writeback_registry as bwr


@pytest.fixture
def reg_path(tmp_path, monkeypatch):
    path = tmp_path / "bot_writeback_ajustes.json"
    monkeypatch.setattr(bwr, "REGISTRY_FILE", str(path))
    return path


def _fake_pydbisam_module(hdr_cols, hdr_rows, det_cols, det_rows):
    class FakePyDBISAM:
        def __init__(self, path):
            self.path = path
            if "TTransaccioninv" in path:
                self._cols = hdr_cols
                self._rows = hdr_rows
            elif "TDetalleInv" in path:
                self._cols = det_cols
                self._rows = det_rows
            else:
                raise FileNotFoundError(path)

        @property
        def _columns(self):
            return [SimpleNamespace(name=n) for n in self._cols]

        def fields(self):
            return list(self._cols)

        def rows(self):
            return list(self._rows)

    mod = types.ModuleType("pydbisam")
    mod.PyDBISAM = FakePyDBISAM
    return mod


class TestBotWritebackRegistry:
    def test_inflight_matches_same_machine_and_persists_id(self, reg_path):
        token = bwr.registrar_inflight(
            orden_id=35975,
            items=[{"codigo": "01567", "delta": 75.0}],
            max_inv_id_before=634,
            machine="DESKTOP-U9B6562",
            now=1000.0,
        )
        assert token

        # Older or equal ID must not match
        assert bwr.es_ajuste_del_bot(634, "DESKTOP-U9B6562", [{"codigo": "01567", "cantidad": 75.0}], now=1010.0) is False

        # Matching new ID consumes the inflight intent and persists 635
        assert bwr.es_ajuste_del_bot(635, " desktop-u9b6562 ", [{"codigo": "01567", "cantidad": 75.0}], now=1010.0) is True

        # Subsequent calls for 635 still return True via bot_inv_ids
        assert bwr.es_ajuste_del_bot(635, "DESKTOP-U9B6562", [{"codigo": "01567", "cantidad": 75.0}], now=2000.0) is True

        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert saved["bot_inv_ids"] == [635]
        assert saved["inflight"] == []

    def test_chunked_batch_consumes_items_one_to_one(self, reg_path):
        bwr.registrar_inflight(
            orden_id=35961,
            items=[
                {"codigo": "A1", "delta": 5.0},
                {"codigo": "A2", "delta": -3.0},
                {"codigo": "A3", "delta": 12.0},
            ],
            max_inv_id_before=620,
            machine="DESKTOP-U9B6562",
            now=1000.0,
        )

        # First document covers 2 items
        assert bwr.es_ajuste_del_bot(
            621,
            "DESKTOP-U9B6562",
            [{"codigo": "A1", "cantidad": 5.0}, {"codigo": "A2", "cantidad": -3.0}],
            now=1005.0,
        ) is True

        # Second document covers the remaining 1 item
        assert bwr.es_ajuste_del_bot(
            622,
            "DESKTOP-U9B6562",
            [{"codigo": "A3", "cantidad": 12.0}],
            now=1008.0,
        ) is True

        # A later manual adjustment on the same machine with identical item must NOT match
        assert bwr.es_ajuste_del_bot(
            623,
            "DESKTOP-U9B6562",
            [{"codigo": "A3", "cantidad": 12.0}],
            now=1015.0,
        ) is False

        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert saved["bot_inv_ids"] == [621, 622]
        assert saved["inflight"] == []

    def test_different_machine_manual_adjustment_never_suppressed(self, reg_path):
        bwr.registrar_inflight(
            orden_id=35975,
            items=[{"codigo": "01567", "delta": 75.0}],
            max_inv_id_before=634,
            machine="DESKTOP-U9B6562",
            now=1000.0,
        )

        assert bwr.es_ajuste_del_bot(
            635,
            "PRINCIPAL",
            [{"codigo": "01567", "cantidad": 75.0}],
            now=1005.0,
        ) is False

        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert saved["bot_inv_ids"] == []
        assert len(saved["inflight"]) == 1

    def test_different_code_or_delta_on_same_machine_never_suppressed(self, reg_path):
        bwr.registrar_inflight(
            orden_id=35975,
            items=[{"codigo": "01567", "delta": 75.0}],
            max_inv_id_before=634,
            machine="DESKTOP-U9B6562",
            now=1000.0,
        )

        assert bwr.es_ajuste_del_bot(635, "DESKTOP-U9B6562", [{"codigo": "01567", "cantidad": 70.0}], now=1005.0) is False
        assert bwr.es_ajuste_del_bot(635, "DESKTOP-U9B6562", [{"codigo": "99999", "cantidad": 75.0}], now=1005.0) is False
        assert bwr.es_ajuste_del_bot(635, "", [{"codigo": "01567", "cantidad": 75.0}], now=1005.0) is False

    def test_expired_inflight_is_pruned_and_returns_false(self, reg_path):
        bwr.registrar_inflight(
            orden_id=35975,
            items=[{"codigo": "01567", "delta": 75.0}],
            max_inv_id_before=634,
            machine="DESKTOP-U9B6562",
            now=1000.0,
        )

        expired_now = 1000.0 + bwr.INFLIGHT_TTL_SECONDS + 1.0
        assert bwr.es_ajuste_del_bot(
            635,
            "DESKTOP-U9B6562",
            [{"codigo": "01567", "cantidad": 75.0}],
            now=expired_now,
        ) is False

        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert saved["inflight"] == []

    def test_cancelar_inflight_removes_entry(self, reg_path):
        token = bwr.registrar_inflight(
            orden_id=35975,
            items=[{"codigo": "01567", "delta": 75.0}],
            max_inv_id_before=634,
            machine="DESKTOP-U9B6562",
            now=1000.0,
        )
        bwr.cancelar_inflight(token)

        assert bwr.es_ajuste_del_bot(
            635,
            "DESKTOP-U9B6562",
            [{"codigo": "01567", "cantidad": 75.0}],
            now=1005.0,
        ) is False

    def test_confirmar_desde_dbisam_promotes_only_matching_bot_docs(self, reg_path, tmp_path, monkeypatch):
        hdr_cols = ["THT_AUTOINCREMENT", "THT_STATUS", "THT_MACHINENAME"]
        hdr_rows = [
            [634, "1", "DESKTOP-U9B6562"],   # <= max_inv_id_before -> ignored
            [635, "4", "DESKTOP-U9B6562"],   # voided status=4 -> ignored
            [636, "1", "PRINCIPAL"],         # different machine -> ignored
            [637, "1", "DESKTOP-U9B6562"],   # bot chunk 1
            [638, "1", "DESKTOP-U9B6562"],   # bot chunk 2
            [639, "1", "DESKTOP-U9B6562"],   # later manual on same machine -> not in remaining
        ]
        det_cols = ["TBT_OPERACION_AUTOINCREMENT", "TBT_CODIGO", "TBT_CANTIDAD"]
        det_rows = [
            [634, "01567", 10.0],
            [635, "01567", 10.0],
            [636, "01567", 10.0],
            [637, "01567", 10.0],
            [638, "05166", -4.0],
            [639, "05166", -4.0],
        ]
        fake_mod = _fake_pydbisam_module(hdr_cols, hdr_rows, det_cols, det_rows)
        monkeypatch.setitem(sys.modules, "pydbisam", fake_mod)

        assert bwr.obtener_max_inv_id(base_db_dir=str(tmp_path)) == 639

        token = bwr.registrar_inflight(
            orden_id=36000,
            items=[{"codigo": "01567", "delta": 10.0}, {"codigo": "05166", "delta": -4.0}],
            max_inv_id_before=634,
            machine="DESKTOP-U9B6562",
            now=1000.0,
        )

        matched = bwr.confirmar_desde_dbisam(token, base_db_dir=str(tmp_path), now=1005.0)
        assert matched == [637, 638]

        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert saved["bot_inv_ids"] == [637, 638]
        assert saved["inflight"] == []

        # Manual doc 639 on same machine is untouched
        assert bwr.es_ajuste_del_bot(639, "DESKTOP-U9B6562", [{"codigo": "05166", "cantidad": -4.0}], now=1010.0) is False

    def test_confirmar_desde_dbisam_leaves_inflight_if_dbisam_unreadable(self, reg_path, tmp_path, monkeypatch):
        class BrokenPyDBISAM:
            def __init__(self, path):
                raise OSError("H: offline")

        mod = types.ModuleType("pydbisam")
        mod.PyDBISAM = BrokenPyDBISAM
        monkeypatch.setitem(sys.modules, "pydbisam", mod)

        token = bwr.registrar_inflight(
            orden_id=36001,
            items=[{"codigo": "01567", "delta": 5.0}],
            max_inv_id_before=639,
            machine="DESKTOP-U9B6562",
            now=1000.0,
        )

        assert bwr.confirmar_desde_dbisam(token, base_db_dir=str(tmp_path), now=1002.0) == []
        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert len(saved["inflight"]) == 1
