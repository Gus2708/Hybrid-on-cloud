import json
import pytest
import sync_ajustes


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
