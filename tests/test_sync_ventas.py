import pytest
import sync_ventas


class TestSyncVentas:
    def test_get_hash_deterministic(self):
        d1 = {"a": "1", "b": "2", "c": "3"}
        d2 = {"a": "1", "b": "2", "c": "3"}
        d3 = {"a": "1", "b": "2", "c": "4"}
        assert sync_ventas.get_hash(d1) == sync_ventas.get_hash(d2)
        assert sync_ventas.get_hash(d1) != sync_ventas.get_hash(d3)

    def test_to_int_conversion(self):
        assert sync_ventas.to_int("123") == 123
        assert sync_ventas.to_int("123.45") == 123
        assert sync_ventas.to_int("") == 0
        assert sync_ventas.to_int(None) == 0
        assert sync_ventas.to_int("invalid") == 0

    def test_upsert_batch_empty(self):
        assert sync_ventas.upsert_batch("ventas_cabecera", "documento", []) is True

    def test_upsert_batch_recursive_split_on_failure(self, monkeypatch):
        """Si un lote de 2 elementos falla, debe dividirlo recursivamente para aislar el error."""
        calls = []

        def mock_send(table, on_conflict, payload):
            calls.append([p["id"] for p in payload])
            # Falla si contiene el id 2
            return not any(p["id"] == 2 for p in payload)

        monkeypatch.setattr(sync_ventas, "_send_batch_request", mock_send)

        payload = [{"id": 1}, {"id": 2}]
        # Debe intentar [1, 2] -> falla -> intenta [1] (ok) -> intenta [2] (falla)
        result = sync_ventas.upsert_batch("ventas_detalle", "id", payload)
        assert result is False
        assert [1, 2] in calls
        assert [1] in calls
        assert [2] in calls

    def test_get_current_rate_fallback(self, monkeypatch):
        import rates_service
        monkeypatch.setattr(rates_service, "RatesService", lambda: (_ for _ in ()).throw(Exception("down")))
        rate = sync_ventas.get_current_rate()
        assert rate == sync_ventas.FACTOR_USD_DEFAULT

    def test_delete_orphans_generic_string_pk(self, monkeypatch):
        """Verifica que delete_orphans_generic maneje claves string sin reventar por int()."""
        deleted_urls = []

        def mock_retry(url, method="GET", data=None, timeout=30, headers=None):
            class MockResp:
                def read(self):
                    if method == "GET":
                        import json
                        return json.dumps([{"cod": "C-1"}, {"cod": "C-2"}, {"cod": "C-ORPHAN"}]).encode()
                    return b""
            if method == "DELETE":
                deleted_urls.append(url)
            return MockResp()

        monkeypatch.setattr(sync_ventas, "_retry_http", mock_retry)
        valid_ids = ["C-1", "C-2"]
        res = sync_ventas.delete_orphans_generic("clientes", "cod", valid_ids, is_numeric=False)
        assert res is True
        assert len(deleted_urls) == 1
        assert "C-ORPHAN" in deleted_urls[0]


class TestValidateSalesDetailCoherence:
    def _create_cabecera(self, path, rows):
        import csv
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["THT_AUTOINCREMENT", "THT_DOCUMENTO", "THT_FECHAEMISION", "THT_TOTALNETO"])
            for r in rows:
                writer.writerow(r)

    def _create_detalle(self, path, rows):
        import csv
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["TBT_AUTOINCREMENT", "TBT_DOCUMENTO", "TBT_OPERACION_AUTOINCREMENT", "TBT_CODIGO", "TBT_CANTIDAD", "TBT_PRECIODEVENTA"])
            for r in rows:
                writer.writerow(r)

    def test_coherence_valid_matching(self, tmp_path):
        cab_path = tmp_path / "VENTAS_CABECERA.csv"
        det_path = tmp_path / "VENTAS_DETALLE.csv"

        self._create_cabecera(cab_path, [
            ["1001", "DOC001", "2026-10-26", "100.00"],
            ["1002", "DOC002", "2026-10-26", "200.00"],
            ["1003", "DOC003", "2026-10-26", "300.00"],
        ])
        self._create_detalle(det_path, [
            ["1", "DOC001", "1001", "P1", "1", "100.00"],
            ["2", "DOC002", "1002", "P2", "2", "100.00"],
            ["3", "DOC003", "1003", "P3", "3", "100.00"],
        ])

        assert sync_ventas.validate_sales_detail_coherence(str(cab_path), str(det_path)) is True

    def test_coherence_missing_details_for_newest_sales(self, tmp_path):
        cab_path = tmp_path / "VENTAS_CABECERA.csv"
        det_path = tmp_path / "VENTAS_DETALLE.csv"

        self._create_cabecera(cab_path, [
            ["1001", "DOC001", "2026-10-26", "100.00"],
            ["1002", "DOC002", "2026-10-26", "200.00"],
            ["1003", "DOC003", "2026-10-26", "300.00"],
        ])
        # Detalle only has details for 1001; 1002 and 1003 are missing
        self._create_detalle(det_path, [
            ["1", "DOC001", "1001", "P1", "1", "100.00"],
        ])

        assert sync_ventas.validate_sales_detail_coherence(str(cab_path), str(det_path)) is False

    def test_coherence_empty_cabecera(self, tmp_path):
        cab_path = tmp_path / "VENTAS_CABECERA.csv"
        det_path = tmp_path / "VENTAS_DETALLE.csv"

        self._create_cabecera(cab_path, [])
        self._create_detalle(det_path, [])

        assert sync_ventas.validate_sales_detail_coherence(str(cab_path), str(det_path)) is True

    def test_coherence_cabecera_has_sales_but_detalle_empty(self, tmp_path):
        cab_path = tmp_path / "VENTAS_CABECERA.csv"
        det_path = tmp_path / "VENTAS_DETALLE.csv"

        self._create_cabecera(cab_path, [
            ["1001", "DOC001", "2026-10-26", "100.00"],
        ])
        self._create_detalle(det_path, [])

        assert sync_ventas.validate_sales_detail_coherence(str(cab_path), str(det_path)) is False

    def test_coherence_detalle_file_missing(self, tmp_path):
        cab_path = tmp_path / "VENTAS_CABECERA.csv"
        det_path = tmp_path / "NON_EXISTENT_DETALLE.csv"

        self._create_cabecera(cab_path, [
            ["1001", "DOC001", "2026-10-26", "100.00"],
        ])

        assert sync_ventas.validate_sales_detail_coherence(str(cab_path), str(det_path)) is False

    def test_coherence_cabecera_file_missing(self, tmp_path):
        cab_path = tmp_path / "NON_EXISTENT_CABECERA.csv"
        det_path = tmp_path / "VENTAS_DETALLE.csv"
        self._create_detalle(det_path, [["1", "DOC001", "1001", "P1", "1", "100.00"]])

        assert sync_ventas.validate_sales_detail_coherence(str(cab_path), str(det_path)) is False

    def test_coherence_latest_date_missing_details(self, tmp_path):
        cab_path = tmp_path / "VENTAS_CABECERA.csv"
        det_path = tmp_path / "VENTAS_DETALLE.csv"

        self._create_cabecera(cab_path, [
            ["1001", "DOC001", "2026-10-25", "100.00"],
            ["1002", "DOC002", "2026-10-26", "200.00"],
        ])
        # Detalle only has yesterday's sale 1001, missing today's sale 1002
        self._create_detalle(det_path, [
            ["1", "DOC001", "1001", "P1", "1", "100.00"],
        ])

        assert sync_ventas.validate_sales_detail_coherence(str(cab_path), str(det_path)) is False

    def test_coherence_whitespace_handling(self, tmp_path):
        cab_path = tmp_path / "VENTAS_CABECERA.csv"
        det_path = tmp_path / "VENTAS_DETALLE.csv"

        self._create_cabecera(cab_path, [
            ["  1001  ", "DOC001", "2026-10-26", "100.00"],
        ])
        self._create_detalle(det_path, [
            ["1", "DOC001", "1001", "P1", "1", "100.00"],
        ])

        assert sync_ventas.validate_sales_detail_coherence(str(cab_path), str(det_path)) is True

    def test_sync_incremental_aborts_when_incoherent(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sync_ventas, "SUPABASE_REST_URL", "https://example.supabase.co")
        monkeypatch.setattr(sync_ventas, "SUPABASE_ANON_KEY", "dummy-key")
        monkeypatch.setattr(sync_ventas, "run_exporter", lambda force=False: True)
        monkeypatch.setattr("network_util.check_drive", lambda *args, **kwargs: True, raising=False)
        monkeypatch.setattr(sync_ventas, "validate_sales_detail_coherence", lambda cab, det: False)
        monkeypatch.setattr(sync_ventas, "BASE_DIR", str(tmp_path))

        # Create dummy cabecera so exists check passes
        cab_file = tmp_path / "VENTAS_CABECERA.csv"
        cab_file.write_text("header\n", encoding="utf-8")

        res = sync_ventas.sync_incremental()
        assert res is False
