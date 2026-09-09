import pytest
from unittest.mock import MagicMock
from contextlib import contextmanager


class MockWin32CallTracker:
    def __init__(self):
        self.clicks = []
        self.keys = []
        self.mutex_locked = False
        self.aborted = False

    def reset(self):
        self.clicks.clear()
        self.keys.clear()
        self.mutex_locked = False
        self.aborted = False


@pytest.fixture
def mock_hybrid_env(monkeypatch):
    """Fixture que aisla completamente las llamadas Win32 y hardware para pruebas headless."""
    tracker = MockWin32CallTracker()

    # Mock realinput
    try:
        import realinput
        monkeypatch.setattr(realinput, "click", lambda x, y, **kwargs: tracker.clicks.append((x, y)))
        monkeypatch.setattr(realinput, "teclear", lambda s, **kwargs: tracker.keys.append(s))
        monkeypatch.setattr(realinput, "escribir", lambda s, **kwargs: tracker.keys.append(s))
    except (ImportError, Exception):
        pass

    # Mock safety_control
    try:
        import safety_control
        monkeypatch.setattr(safety_control, "BlockInput", lambda b: True)
    except (ImportError, Exception):
        pass

    # Mock listener_base check de H:
    try:
        import listener_base
        monkeypatch.setattr(listener_base, "_h_disponible", lambda: True)
    except (ImportError, Exception):
        pass

    return tracker
