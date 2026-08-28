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

import socket
socket.socket = MagicMock() # Evitar que aborte por lock_socket

import config
from widget import HybridCloudWidget

@pytest.fixture
def root():
    r = tk.Tk()
    yield r
    try:
        r.destroy()
    except: pass

def test_widget_init(root):
    app = HybridCloudWidget(root)
    assert root.title() == f"{config.SAAS_NAME} - {config.BUSINESS_NAME}"
    # Validar que existe el canvas
    assert app.canvas is not None

def test_widget_ui_sync_state(root):
    app = HybridCloudWidget(root)
    
    # Test state: Syncing
    app.is_syncing = True
    app.update_ui()
    # En tcl/tk, cget("text") en canvas itemconfig no funciona igual, se debe usar itemcget
    status_text = app.canvas.itemcget(app.status_label, "text")
    assert status_text == "Sincronizando..."

def test_widget_ui_offline_state(root):
    app = HybridCloudWidget(root)
    
    # Test state: Offline
    app.is_syncing = False
    app.is_online = False
    app.update_ui()
    status_text = app.canvas.itemcget(app.status_label, "text")
    assert status_text == "Sin Conexión"
