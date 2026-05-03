import pytest
from app import normalize_query, remove_accents

def test_remove_accents():
    assert remove_accents("camión") == "camion"
    assert remove_accents("MARTILLO") == "MARTILLO"
    assert remove_accents("ñandú") == "nandu"

def test_normalize_query():
    # Test case: normalization and stop words
    assert normalize_query("el martillo de madera") == "MARTILLO MADERA"
    # Test case: fractions
    assert normalize_query("disco 4 1/2 pulgadas") == "DISCO 4 1/2 PULGADA"
    # Test case: pluralization (singularization)
    assert normalize_query("tornillos") == "TORNILLO"
    assert normalize_query("as") == "AS" # Too short to singularize
    # Test case: uppercase
    assert normalize_query("Cable") == "CABLE"

def test_health_endpoint(client, mocker):
    # Mocking os.path.exists and getmtime to avoid filesystem dependencies
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.path.getmtime", return_value=1000.0)
    # Mocking open for the last_sync.json file
    mocker.patch("builtins.open", mocker.mock_open(read_data='{"last_sync": "2026-05-03 18:00:00", "timestamp": 1000.0}'))
    
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert "last_sync" in data
    assert "needs_sync" in data

def test_buscar_vacio(client):
    response = client.get("/api/v1/buscar?q=")
    assert response.status_code == 200
    data = response.get_json()
    assert data["count"] == 0
    assert data["results"] == []

def test_buscar_con_datos(client, mocker):
    # Mocking the local cache to avoid loading the real CSV
    mock_items = [
        {
            "codigo_interno": "101",
            "descripcion": "MARTILLO DE GOMA",
            "unidad": "UND",
            "codigo_barras": "12345",
            "costo": 5.0,
            "precio_venta": 10.0,
            "existencia": 20.0,
        },
        {
            "codigo_interno": "102",
            "descripcion": "TORNILLO 1/2",
            "unidad": "PAQ",
            "codigo_barras": "67890",
            "costo": 0.1,
            "precio_venta": 0.2,
            "existencia": 0.0,
        }
    ]
    mocker.patch("app._LOCAL_CACHE", mock_items)
    mocker.patch("app._load_inventory_if_needed", return_value=None)
    
    # Test search
    response = client.get("/api/v1/buscar?q=martillo")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total_encontrados"] == 1
    assert data["results"][0]["codigo_interno"] == "101"
    
    # Test stock filter
    response = client.get("/api/v1/buscar?q=tornillo&stock=1")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total_encontrados"] == 0
    
    # Test fraction search
    response = client.get("/api/v1/buscar?q=1/2")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total_encontrados"] == 1
    assert data["results"][0]["codigo_interno"] == "102"
