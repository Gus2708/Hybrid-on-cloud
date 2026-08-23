import importlib
import os


def test_config_lee_del_entorno(mocker):
    """config.py debe tomar sus valores del entorno, no de constantes.

    Se afirma sobre el mecanismo (el entorno gana) y no sobre las credenciales
    concretas de un despliegue: un test que fija la URL real de un proyecto
    solo pasa en la máquina de ese proyecto.
    """
    mocker.patch.dict(os.environ, {
        "TASA_BS": "123.45",
        "SUPABASE_URL": "https://proyecto-de-prueba.supabase.co",
        "SUPABASE_ANON_KEY": "clave-de-prueba",
    })

    import config
    importlib.reload(config)

    assert config.TASA_BS_DEFAULT == 123.45
    assert config.SUPABASE_URL == "https://proyecto-de-prueba.supabase.co"
    assert config.SUPABASE_ANON_KEY == "clave-de-prueba"


def test_config_sin_credenciales_no_revienta(mocker):
    """Sin credenciales en el entorno, config carga con cadenas vacías en vez
    de caer a un valor embebido: es lo que permite publicar el repositorio."""
    mocker.patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_ANON_KEY": ""})
    mocker.patch("pathlib.Path.exists", return_value=False)  # ignorar .env local

    import config
    importlib.reload(config)

    assert config.SUPABASE_URL == ""
    assert config.SUPABASE_ANON_KEY == ""
