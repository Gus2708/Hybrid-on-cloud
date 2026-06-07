import pytest
import os
import json
from sync import get_row_hash, _load_csv, sync_incremental

def test_get_row_hash():
    row1 = {
        "descripcion": "TEST",
        "costo": 10.0,
        "precio_venta": 20.0,
        "existencia": 5.0,
        "codigo_barras": "123",
        "referencia": "REF123",
        "unidad": "UND"
    }
    row2 = row1.copy()
    assert get_row_hash(row1) == get_row_hash(row2)
    
    row2["existencia"] = 6.0
    assert get_row_hash(row1) != get_row_hash(row2)

def test_load_csv(tmp_path):
    csv_file = tmp_path / "test.csv"
    content = "CODIGO_INTERNO,DESCRIPCION,UNIDAD,CODIGO_BARRAS,REFERENCIA,COSTO,PRECIO_VENTA,EXISTENCIA\n"
    content += "1,PROD 1,UND,123,REF123,10,20,5\n"
    content += "2,PROD 2,UND,456,REF456,15,30,10\n"
    csv_file.write_text(content, encoding="utf-8-sig")
    
    rows = _load_csv(str(csv_file))
    assert len(rows) == 2
    assert rows[0]["codigo_interno"] == "1"
    assert rows[0]["precio_venta"] == 20.0

def test_sync_incremental_no_changes(mocker):
    # Mocking external calls
    mocker.patch("sync.run_hybrid_exporter", return_value=True)
    mocker.patch("sync._load_csv", return_value=[{"codigo_interno": "1", "descripcion": "P1", "costo": 1, "precio_venta": 2, "existencia": 3, "codigo_barras": "B1", "referencia": "R1", "unidad": "U1"}])
    mocker.patch("os.path.exists", return_value=True)
    
    # Mock cache file content
    h = get_row_hash({"codigo_interno": "1", "descripcion": "P1", "costo": 1, "precio_venta": 2, "existencia": 3, "codigo_barras": "B1", "referencia": "R1", "unidad": "U1"})
    mocker.patch("builtins.open", mocker.mock_open(read_data=json.dumps({"1": h})))
    
    # Mock Supabase calls
    mock_upsert = mocker.patch("sync.upsert_batch_rest", return_value=True)
    mocker.patch("sync.verify_sync")
    
    sync_incremental()
    
    # Should not call upsert because hash matches
    assert mock_upsert.call_count == 0

def test_sync_incremental_with_changes(mocker):
    mocker.patch("sync.run_hybrid_exporter", return_value=True)
    mocker.patch("sync._load_csv", return_value=[{"codigo_interno": "1", "descripcion": "P1", "costo": 1, "precio_venta": 2, "existencia": 3, "codigo_barras": "B1", "referencia": "R1", "unidad": "U1"}])
    
    # Empty cache (no sync_cache.json) but other files/directories exist
    mocker.patch("os.path.exists", side_effect=lambda x: False if "sync_cache.json" in str(x) else True)
    
    # Mock Supabase calls
    mock_upsert = mocker.patch("sync.upsert_batch_rest", return_value=True)
    mocker.patch("sync.verify_sync")
    mocker.patch("builtins.open", mocker.mock_open())
    mocker.patch("json.dump")
    
    sync_incremental()
    
    # Should call upsert
    assert mock_upsert.call_count == 1
