import pytest
import tkinter as tk
from unittest.mock import MagicMock
import os
import sys

# Mocking libraries that might not be present or cause issues in headles environment
sys.modules['pystray'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['PIL.Image'] = MagicMock()
sys.modules['PIL.ImageTk'] = MagicMock()

from widget import SerruchoWidget

@pytest.fixture
def root():
    r = tk.Tk()
    yield r
    try:
        r.destroy()
    except: pass

def test_widget_init(root):
    app = SerruchoWidget(root)
    assert root.title() == "El Serrucho Monitor"
    assert app.status_text.cget("text") == "Desconectado"

def test_widget_update_status_mocked(root, mocker):
    # Mocking the urllib request
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"last_sync": "2026-05-03 12:00", "status": "ok"}'
    mock_resp.__enter__.return_value = mock_resp
    mocker.patch("urllib.request.urlopen", return_value=mock_resp)
    
    app = SerruchoWidget(root)
    
    # We need to wait for the thread to finish or mock the thread
    # For simplicity, we can test the update_status call if we mock the threading
    mock_thread = mocker.patch("threading.Thread")
    app.update_status()
    assert mock_thread.called
