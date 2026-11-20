import json
import sys
import types
from types import SimpleNamespace
import pytest
import bot_writeback_registry as bwr
import sync_ajustes


def _build_sync_fake_pydbisam(tables):
    class FakePyDBISAM:
        def __init__(self, path):
            for key, spec in tables.items():
                if key in path:
                    self._cols = spec["cols"]
                    self._rows = spec["rows"]
                    self._columns = [SimpleNamespace(name=n, row_offset=0) for n in self._cols]
                    self._data_offset = 0
                    self._row_size = 4
                    self._total_rows = len(self._rows)
                    self._deleted_rows = 0
                    self._data = b"\x00\x00\x00\x00" * self._total_rows
                    return
            raise FileNotFoundError(path)

        def rows(self):
            return list(self._rows)

        def row(self, i):
            return self._rows[i]

    mod = types.ModuleType("pydbisam")
    mod.PyDBISAM = FakePyDBISAM
    return mod


class TestSyncAjustes:
    def test_decode_dbisam_time(self):
        assert sync_ajustes.decode_dbisam_time(0) == "00:00:00"
        assert sync_ajustes.decode_dbisam_time(3661000) == "01:01:01"
        assert sync_ajustes.decode_dbisam_time(86399000) == "23:59:59"
        assert sync_ajustes.decode_dbisam_time(None) == "00:00:00"
        assert sync_ajustes.decode_dbisam_time("no-int") == "00:00:00"

    def test_get_product_descriptions_from_csv(self, tmp_path):
        csv_file = tmp_path / "maestro.csv"
        content = "CODIGO_INTERNO,DESCRIPCION\n01-001,Pintura Blanca\n01-002,Brocha 2 pulg\n"
        csv_file.write_text(content, encoding="utf-8-sig")

        mapping = sync_ajustes.get_product_descriptions(str(csv_file))
        assert mapping["01-001"] == "Pintura Blanca"
        assert mapping["01-002"] == "Brocha 2 pulg"

    def test_get_product_descriptions_nonexistent_file(self):
        mapping = sync_ajustes.get_product_descriptions("non_existent_file.csv")
        assert mapping == {}

    def test_get_synced_transaction_ids_loads_cache(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps([["Inv", 100], ["Com", 200]]), encoding="utf-8")
        monkeypatch.setattr(sync_ajustes, "SYNCED_CACHE_FILE", str(cache_file))

        # Mock urllib para no llamar a Supabase
        monkeypatch.setattr(sync_ajustes.urllib.request, "urlopen", lambda req, timeout=30: (_ for _ in ()).throw(Exception("mocked")))

        synced = sync_ajustes.get_synced_transaction_ids()
        assert ("Inv", 100) in synced
        assert ("Com", 200) in synced

    def test_sync_manual_adjustments_skips_bot_and_tags_pc(self, tmp_path, monkeypatch):
        (tmp_path / "TTransaccioninv.dat").write_bytes(b"")
        (tmp_path / "TDetalleInv.Dat").write_bytes(b"")
        reg_file = tmp_path / "bot_writeback_ajustes.json"
        monkeypatch.setattr(bwr, "REGISTRY_FILE", str(reg_file))

        # Bot pre-registered doc 550 (or inflight for doc 550)
        bwr.registrar_inflight(
            orden_id=35975,
            items=[{"codigo": "01567", "delta": 75.0}],
            max_inv_id_before=549,
            machine="DESKTOP-U9B6562",
        )

        tables = {
            "TTransaccioninv.dat": {
                "cols": [
                    "THT_AUTOINCREMENT", "THT_DOCUMENTO", "THT_STATUS",
                    "THT_FECHAEMISION", "THT_DESCRIPCLASIFY", "THT_HORA", "THT_MACHINENAME",
                ],
                "rows": [
                    [550, "00000367", "1", "2026-11-20", "DESINCORPORACION", 0, "DESKTOP-U9B6562"],
                    [549, "00000291", "1", "2026-10-03", "DESINCORPORACION", 0, "PRINCIPAL"],
                    [551, "00000368", "1", "2026-11-20", "DESINCORPORACION", 0, "Fail"],
                ],
            },
            "TDetalleInv.Dat": {
                "cols": [
                    "TBT_CODIGO", "TBT_CANTIDAD", "TBT_EXISTANTERIOR",
                    "TBT_EXISTACTUAL", "TBT_OPERACION_AUTOINCREMENT", "TBT_MEMODETALLE",
                ],
                "rows": [
                    ["01567", 75.0, -25.0, 50.0, 550, None],
                    ["01567", -335.0, 335.0, 0.0, 549, None],
                    ["05166", 10.0, 0.0, 10.0, 551, None],
                ],
            },
        }
        monkeypatch.setitem(sys.modules, "pydbisam", _build_sync_fake_pydbisam(tables))

        inserted_parents = []
        inserted_children = []
        next_cloud_id = [9000]

        def _fake_parent(payload):
            inserted_parents.append(payload)
            next_cloud_id[0] += 1
            return next_cloud_id[0]

        def _fake_children(items):
            inserted_children.append(items)
            return True

        monkeypatch.setattr(sync_ajustes, "insert_parent_order", _fake_parent)
        monkeypatch.setattr(sync_ajustes, "insert_child_items", _fake_children)

        synced_ids = set()
        count = sync_ajustes.sync_manual_adjustments(str(tmp_path), synced_ids, {"01567": "CURVA", "05166": "TUBO"})

        assert count == 2
        assert ("Inv", 550) in synced_ids
        assert [p["nota"] for p in inserted_parents] == [
            "[Local Inv ID: 549] - [PC: PRINCIPAL] - Ajuste #00000291: DESINCORPORACION",
            "[Local Inv ID: 551] - Ajuste #00000368: DESINCORPORACION",
        ]
        assert len(inserted_children) == 2

    def test_sync_purchases_tags_pc_and_never_suppresses(self, tmp_path, monkeypatch):
        (tmp_path / "TTransaccioncom.dat").write_bytes(b"")
        (tmp_path / "TDetalleCom.Dat").write_bytes(b"")
        reg_file = tmp_path / "bot_writeback_ajustes.json"
        monkeypatch.setattr(bwr, "REGISTRY_FILE", str(reg_file))
        reg_file.write_text(json.dumps({"bot_inv_ids": [608], "inflight": []}), encoding="utf-8")

        tables = {
            "TTransaccioncom.dat": {
                "cols": [
                    "THT_AUTOINCREMENT", "THT_DOCUMENTO", "THT_STATUS",
                    "THT_FECHAEMISION", "THT_RIFCLIENTE", "THT_PERSONACONTACTO",
                    "THT_HORA", "THT_MACHINENAME",
                ],
                "rows": [
                    [608, "00000157", "1", "2026-11-19", "J123", "FERRETERIA ARCI", 0, "DESKTOP-U9B6562"],
                    [609, "00000158", "1", "2026-11-20", "", "PROVEEDOR B", 0, ""],
                ],
            },
            "TDetalleCom.Dat": {
                "cols": [
                    "TBT_CODIGO", "TBT_CANTIDAD", "TBT_EXISTANTERIOR",
                    "TBT_EXISTACTUAL", "TBT_OPERACION_AUTOINCREMENT", "TBT_MEMODETALLE",
                ],
                "rows": [
                    ["21891", 10.0, 0.0, 10.0, 608, None],
                    ["21892", 5.0, 0.0, 5.0, 609, None],
                ],
            },
        }
        monkeypatch.setitem(sys.modules, "pydbisam", _build_sync_fake_pydbisam(tables))

        inserted_parents = []
        monkeypatch.setattr(sync_ajustes, "insert_parent_order", lambda p: (inserted_parents.append(p), len(inserted_parents))[1])
        monkeypatch.setattr(sync_ajustes, "insert_child_items", lambda items: True)

        synced_ids = set()
        count = sync_ajustes.sync_purchases(str(tmp_path), synced_ids, {})

        assert count == 2
        assert [p["nota"] for p in inserted_parents] == [
            "[Local Com ID: 608] - [PC: DESKTOP-U9B6562] - Compra #00000157: FERRETERIA ARCI (RIF: J123)",
            "[Local Com ID: 609] - Compra #00000158: PROVEEDOR B",
        ]
