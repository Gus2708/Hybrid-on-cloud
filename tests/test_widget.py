import pytest
import tkinter as tk
from unittest.mock import MagicMock
import os
import sys

# Mocking libraries that might not be present or cause issues in headless environment
sys.modules['pystray'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['PIL.Image'] = MagicMock()
sys.modules['PIL.ImageTk'] = MagicMock()

from widget import SerruchoPremiumWidget

# Scope de modulo a proposito: crear y destruir una raiz Tk por test hace que
# la segunda tk.Tk() del archivo falle de forma intermitente con
# "Can't find a usable tk.tcl". Con una sola raiz para todo el modulo el
# problema desaparece.
@pytest.fixture(scope="module")
def root():
    r = tk.Tk()
    yield r
    try:
        r.destroy()
    except Exception:
        pass

def test_widget_init(root):
    app = SerruchoPremiumWidget(root)
    assert root.title() == "Serrucho Monitor"
    assert app.width == 310
    assert app.height_full == 335
    assert "bg" in app.colors
    assert hasattr(app, "corpnorte_dot")
    assert hasattr(app, "maxcam_dot")
    assert hasattr(app, "waha_dot")
    assert app.corpnorte_ok is True
    assert app.maxcam_ok is True
    assert app.waha_ok is True

def test_widget_verify_loop_mocked(root, mocker):
    # Mocking the urllib request
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"last_sync": "2026-05-03 12:00", "status": "ok", "is_syncing": false, "entities": {}}'
    mock_resp.__enter__.return_value = mock_resp
    mocker.patch("urllib.request.urlopen", return_value=mock_resp)
    
    app = SerruchoPremiumWidget(root)
    
    mock_thread = mocker.patch("threading.Thread")
    app.verify_loop()
    assert mock_thread.called

def test_widget_health_ui_supplier_dots_and_priorities(root, mocker):
    app = SerruchoPremiumWidget(root)

    # 1. All OK
    h_data_all_ok = {
        "checks": {
            "drive_h": {"ok": True},
            "monitor": {"ok": True},
            "supabase": {"ok": True},
            "waha": {"ok": True, "status": "WORKING"},
            "corpnorte": {"ok": True},
            "maxcam": {"ok": True},
        }
    }
    app._update_health_ui(h_data_all_ok)
    assert app.corpnorte_ok is True
    assert app.maxcam_ok is True
    assert app.canvas.itemcget(app.corpnorte_dot, "fill") == app.colors["green"]
    assert app.canvas.itemcget(app.maxcam_dot, "fill") == app.colors["green"]
    assert app.canvas.itemcget(app.detail_label, "text") == "Monitoreando archivos..."

    # 2. CorpNorte offline
    h_data_norte_down = {
        "checks": {
            "drive_h": {"ok": True},
            "monitor": {"ok": True},
            "supabase": {"ok": True},
            "waha": {"ok": True, "status": "WORKING"},
            "corpnorte": {"ok": False},
            "maxcam": {"ok": True},
        }
    }
    app._update_health_ui(h_data_norte_down)
    assert app.corpnorte_ok is False
    assert app.maxcam_ok is True
    assert app.canvas.itemcget(app.corpnorte_dot, "fill") == app.colors["red"]
    assert app.canvas.itemcget(app.maxcam_dot, "fill") == app.colors["green"]
    assert app.canvas.itemcget(app.detail_label, "text") == "⚠️ API Norte (5002) offline"

    # 3. Maxcam offline
    h_data_maxcam_down = {
        "checks": {
            "drive_h": {"ok": True},
            "monitor": {"ok": True},
            "supabase": {"ok": True},
            "waha": {"ok": True, "status": "WORKING"},
            "corpnorte": {"ok": True},
            "maxcam": {"ok": False},
        }
    }
    app._update_health_ui(h_data_maxcam_down)
    assert app.corpnorte_ok is True
    assert app.maxcam_ok is False
    assert app.canvas.itemcget(app.corpnorte_dot, "fill") == app.colors["green"]
    assert app.canvas.itemcget(app.maxcam_dot, "fill") == app.colors["red"]
    assert app.canvas.itemcget(app.detail_label, "text") == "⚠️ API Maxcam (5001) offline"

    # 4. Both offline
    h_data_both_down = {
        "checks": {
            "drive_h": {"ok": True},
            "monitor": {"ok": True},
            "supabase": {"ok": True},
            "waha": {"ok": True, "status": "WORKING"},
            "corpnorte": {"ok": False},
            "maxcam": {"ok": False},
        }
    }
    app._update_health_ui(h_data_both_down)
    assert app.corpnorte_ok is False
    assert app.maxcam_ok is False
    assert app.canvas.itemcget(app.corpnorte_dot, "fill") == app.colors["red"]
    assert app.canvas.itemcget(app.maxcam_dot, "fill") == app.colors["red"]
    assert app.canvas.itemcget(app.detail_label, "text") == "⚠️ APIs Norte y Maxcam offline"

    # 5. Fallback when keys not in checks (probes check_port_alive)
    mock_port = mocker.patch("widget.check_port_alive", side_effect=lambda port: port == 5001)
    h_data_no_suppliers = {
        "checks": {
            "drive_h": {"ok": True},
            "monitor": {"ok": True},
            "supabase": {"ok": True},
            "waha": {"ok": True, "status": "WORKING"},
        }
    }
    app._update_health_ui(h_data_no_suppliers)
    assert mock_port.called
    assert app.corpnorte_ok is False
    assert app.maxcam_ok is True
    assert app.canvas.itemcget(app.corpnorte_dot, "fill") == app.colors["red"]
    assert app.canvas.itemcget(app.maxcam_dot, "fill") == app.colors["green"]
