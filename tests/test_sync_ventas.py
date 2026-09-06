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
        monkeypatch.setattr(sync_ventas, "RatesService", lambda: (_ for _ in ()).throw(Exception("down")), raising=False)
        rate = sync_ventas.get_current_rate()
        assert rate > 0
