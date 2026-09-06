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
