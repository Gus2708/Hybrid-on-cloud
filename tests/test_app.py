import pytest
from app import app, _enrich

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_health_endpoint(client, mocker):
    mocker.patch("os.path.exists", side_effect=lambda x: True if "last_monitor.json" in str(x) else False)
    mocker.patch("os.path.getmtime", return_value=1000.0)
    
    # Mock last_monitor.json file
    import time
    timestamp = time.time() - 10
    mocker.patch("builtins.open", mocker.mock_open(read_data=f'{{"last_check": "2026-05-21 12:00:00", "timestamp": {timestamp}}}'))
    
    # Mock check_drive, check_supabase, get_local_ip from network_util
    mocker.patch("network_util.check_drive", return_value=True)
    mocker.patch("network_util.check_supabase", return_value={"ok": True})
    mocker.patch("network_util.check_waha", return_value={"ok": True, "status": "WORKING"})
    mocker.patch("network_util.get_local_ip", return_value="127.0.0.1")
    
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["app"] == "El Serrucho Backend"

def test_productos_vacio(client, mocker):
    # Mocking cache to return empty
    mocker.patch("app._LOCAL_CACHE", [])
    mocker.patch("app._load_inventory_if_needed", return_value=None)
    
    response = client.get("/api/v1/productos")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 0
    assert data["results"] == []

def test_productos_con_datos(client, mocker):
    mock_items = [
        {
            "CODIGO_INTERNO": "101",
            "DESCRIPCION": "MARTILLO DE GOMA",
            "UNIDAD": "UND",
            "CODIGO_BARRAS": "12345",
            "REFERENCIA": "REF-GOMA",
            "COSTO": "5.0",
            "PRECIO_VENTA": "10.0",
            "EXISTENCIA": "20.0"
        },
        {
            "CODIGO_INTERNO": "102",
            "DESCRIPCION": "TORNILLO 1/2",
            "UNIDAD": "PAQ",
            "CODIGO_BARRAS": "67890",
            "REFERENCIA": "REF-TORN",
            "COSTO": "0.1",
            "PRECIO_VENTA": "0.2",
            "EXISTENCIA": "0.0"
        }
    ]
    mocker.patch("app._LOCAL_CACHE", mock_items)
    mocker.patch("app._load_inventory_if_needed", return_value=None)
    
    # 1. Test search by description
    response = client.get("/api/v1/productos?q=martillo")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    assert data["results"][0]["codigo_interno"] == "101"
    assert data["results"][0]["referencia"] == "REF-GOMA"
    
    # 2. Test search by referencia
    response = client.get("/api/v1/productos?q=REF-TORN")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 1
    assert data["results"][0]["codigo_interno"] == "102"
    
    # 3. Test empty query (should return all products)
    response = client.get("/api/v1/productos?q=")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 2
