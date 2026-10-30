import os
import sys
from datetime import date, datetime
import pytest

import extraer_ventas


class TestDecodeDbisamTime:
    def test_valid_time(self):
        assert extraer_ventas.decode_dbisam_time(0) == "00:00:00"
        assert extraer_ventas.decode_dbisam_time(3661000) == "01:01:01"
        assert extraer_ventas.decode_dbisam_time(86399000) == "23:59:59"
        assert extraer_ventas.decode_dbisam_time(50400000) == "14:00:00"

    def test_zero(self):
        assert extraer_ventas.decode_dbisam_time(0) == "00:00:00"

    def test_none(self):
        assert extraer_ventas.decode_dbisam_time(None) == "00:00:00"

    def test_invalid_types(self):
        assert extraer_ventas.decode_dbisam_time("invalid") == "00:00:00"
        assert extraer_ventas.decode_dbisam_time([1000]) == "00:00:00"
        assert extraer_ventas.decode_dbisam_time({"ms": 1000}) == "00:00:00"
        # In Python, bool is a subclass of int, but True/False must not be treated as time
        assert extraer_ventas.decode_dbisam_time(True) == "00:00:00"
        assert extraer_ventas.decode_dbisam_time(False) == "00:00:00"

    def test_negative_and_out_of_bounds(self):
        assert extraer_ventas.decode_dbisam_time(-1000) == "00:00:00"
        # Greater than 24 hours (86,400,000 ms) should wrap or clamp safely
        res = extraer_ventas.decode_dbisam_time(86400000 + 3661000)
        assert res == "01:01:01"

    def test_float_input(self):
        assert extraer_ventas.decode_dbisam_time(3661000.0) == "01:01:01"


class TestRowSanitization:
    def test_safe_str_various_types(self):
        assert extraer_ventas.safe_str(None) == ""
        assert extraer_ventas.safe_str("Fail") == ""
        assert extraer_ventas.safe_str(date(2026, 10, 26)) == "2026-10-26"
        assert extraer_ventas.safe_str(datetime(2026, 10, 26, 12, 0, 0)) == "2026-10-26"
        assert extraer_ventas.safe_str(12345) == "12345"
        assert extraer_ventas.safe_str(99.95) == "99.95"
        assert extraer_ventas.safe_str("  spaced  ") == "spaced"

    def test_sanitize_row_heterogeneous(self):
        raw_row = [1001, "DOC-001", date(2026, 10, 26), 150.75, None, "Fail", 500, 11]
        sanitized = extraer_ventas.sanitize_row(raw_row)
        
        # Verify all elements are strings
        assert all(isinstance(v, str) for v in sanitized)
        assert sanitized == ["1001", "DOC-001", "2026-10-26", "150.75", "", "", "500", "11"]
        
        # Verify .strip() can be safely called on any item
        for item in sanitized:
            assert isinstance(item.strip(), str)


class TestIncrementalDataPruning:
    def test_prune_orphaned_details_mixed_keys_and_values(self):
        # existing_data contains mixed keys (int vs str) and rows with mixed types (int vs str parent auto)
        existing_data = {
            101: [101, "DOC1", "PROD1", 1, 10.0, "", 500, 11],
            "102": ["102", "DOC2", "PROD2", 2, 20.0, "", "501", "11"],
            103: [103, "DOC3", "PROD3", 1, 15.0, "", 999, 11],     # orphan: 999 not in valid_sales_ids
            "104": ["104", "DOC4", "PROD4", 3, 30.0, "", None, 11],   # orphan: None parent
            105: [105, "DOC5", "PROD5", 1, 5.0, "", " 500 ", 11],  # valid with whitespace
        }
        # valid_sales_ids has mixed int and string IDs
        valid_sales_ids = {500, "501"}
        idx_parent_auto = 6

        cleaned, pruned_count = extraer_ventas.prune_orphaned_details(
            existing_data, valid_sales_ids, idx_parent_auto
        )

        assert pruned_count == 2
        assert 101 in cleaned
        assert "102" in cleaned
        assert 105 in cleaned
        assert 103 not in cleaned
        assert "104" not in cleaned

    def test_prune_orphaned_details_empty(self):
        cleaned, pruned_count = extraer_ventas.prune_orphaned_details({}, {"500"}, 6)
        assert cleaned == {}
        assert pruned_count == 0

    def test_prune_orphaned_details_short_rows(self):
        existing_data = {
            "1": ["too", "short"],
        }
        cleaned, pruned_count = extraer_ventas.prune_orphaned_details(existing_data, {"500"}, 6)
        assert cleaned == {}
        assert pruned_count == 1


class TestExtractionFailureReporting:
    def test_run_extraction_returns_none_when_drive_missing(self, monkeypatch):
        # Point base to a nonexistent path
        monkeypatch.setattr(extraer_ventas, "base", r"Z:\NonExistentPath\DB")
        result = extraer_ventas.run_extraction()
        assert result is None

    def test_run_extraction_returns_none_on_exception(self, monkeypatch):
        # Simulate drive exists but DB reading raises an unhandled error
        monkeypatch.setattr(os.path, "exists", lambda p: True)
        monkeypatch.setattr(extraer_ventas, "_safe_read_db", lambda *args, **kwargs: (_ for _ in ()).throw(IOError("Simulated DB error")))
        monkeypatch.setattr(extraer_ventas, "should_extract", lambda *args, **kwargs: True)

        result = extraer_ventas.run_extraction()
        assert result is None

    def test_main_exits_nonzero_on_failure(self, monkeypatch):
        monkeypatch.setattr(extraer_ventas, "run_extraction", lambda force=False: None)
        with pytest.raises(SystemExit) as excinfo:
            extraer_ventas.main(["extraer_ventas.py"])
        assert excinfo.value.code != 0

    def test_main_exits_zero_on_success(self, monkeypatch):
        # When run_extraction returns True (extracted new data)
        monkeypatch.setattr(extraer_ventas, "run_extraction", lambda force=False: True)
        assert extraer_ventas.main(["extraer_ventas.py"]) == 0

        # When run_extraction returns False (already up-to-date)
        monkeypatch.setattr(extraer_ventas, "run_extraction", lambda force=False: False)
        assert extraer_ventas.main(["extraer_ventas.py"]) == 0
