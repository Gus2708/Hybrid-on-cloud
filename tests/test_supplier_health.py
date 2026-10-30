import pytest
from unittest.mock import MagicMock, patch
import urllib.error
import sys
import os

from network_util import check_supplier_api, check_maxcam, check_corpnorte

def test_check_supplier_api_online(mocker):
    mock_resp = MagicMock()
    mock_resp.getcode.return_value = 200
    mock_resp.__enter__.return_value = mock_resp
    mocker.patch("urllib.request.urlopen", return_value=mock_resp)

    res = check_supplier_api(5001, "Maxcam")
    assert res == {"ok": True, "status": "ONLINE", "port": 5001, "service": "Maxcam"}

def test_check_supplier_api_http_error(mocker):
    err = urllib.error.HTTPError("http://127.0.0.1:5001/health", 404, "Not Found", {}, None)
    mocker.patch("urllib.request.urlopen", side_effect=err)

    res = check_supplier_api(5001, "Maxcam")
    assert res == {"ok": True, "status": "ONLINE", "port": 5001, "service": "Maxcam"}

def test_check_supplier_api_offline(mocker):
    mocker.patch("urllib.request.urlopen", side_effect=Exception("Connection refused"))

    res = check_supplier_api(5001, "Maxcam")
    assert res == {"ok": False, "status": "OFFLINE", "port": 5001, "service": "Maxcam"}

def test_check_maxcam(mocker):
    mocker.patch("network_util.check_supplier_api", return_value={"ok": True, "status": "ONLINE", "port": 5001, "service": "Maxcam"})
    res = check_maxcam()
    assert res["service"] == "Maxcam"
    assert res["port"] == 5001

def test_check_corpnorte(mocker):
    mocker.patch("network_util.check_supplier_api", return_value={"ok": True, "status": "ONLINE", "port": 5002, "service": "CorpNorte"})
    res = check_corpnorte()
    assert res["service"] == "CorpNorte"
    assert res["port"] == 5002

def test_maxcam_api_health_endpoint():
    maxcam_dir = os.path.join(os.path.dirname(__file__), "..", "microservicios", "maxcam")
    sys.path.insert(0, os.path.abspath(maxcam_dir))
    try:
        import maxcam_api
        client = maxcam_api.app.test_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok", "service": "maxcam"}
    finally:
        sys.path.pop(0)

def test_corpnorte_api_health_endpoint():
    corpnorte_dir = os.path.join(os.path.dirname(__file__), "..", "microservicios", "corpnorte")
    sys.path.insert(0, os.path.abspath(corpnorte_dir))
    try:
        import corpnorte_api
        client = corpnorte_api.app.test_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok", "service": "corpnorte"}
    finally:
        sys.path.pop(0)
