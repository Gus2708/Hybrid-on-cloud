import os
import pytest

def test_config_loading(mocker):
    # Set env vars
    mocker.patch.dict(os.environ, {"TASA_BS": "123.45"})
    
    # Reload config (using importlib to force reload since it's already imported)
    import importlib
    import config
    importlib.reload(config)
    
    assert config.TASA_BS_DEFAULT == 123.45
    assert "YOUR-PROJECT-REF" in config.SUPABASE_URL
