# Plan 009: Agregar tests para `rates_service.py` y la cascada de fallback de tasas

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- rates_service.py sync_ventas.py tests/`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: `plans/001-fix-get-current-rate-key-mismatch.md` (el plan 001 debe estar completo para que los tests de fallback sean útiles)
- **Category**: tests
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

La lógica de conversión a USD es el corazón financiero del sistema: cada venta en Bs. se convierte usando una tasa de cambio. `rates_service.py` obtiene esa tasa scrapeando el BCV y Binance P2P. `sync_ventas.py:116-124` tiene una cascada BCV → Binance → default 489.55 que es crítica para que los datos sean correctos.

Actualmente hay **cero tests** para este camino crítico. Un cambio en la estructura HTML del BCV o en la API de Binance puede romper silenciosamente la conversión, y las ventas se grabarán con la tasa hardcodeada sin que nadie lo sepa.

## Estado actual

- `rates_service.py` — 187 líneas, no existe `tests/test_rates_service.py`
- `sync_ventas.py:116-124` — `get_current_rate()` tiene cascada de fallback (con el bug del plan 001 que debe estar corregido)
- Tests existentes en `tests/test_sync.py` mockean todo, no testean la lógica de tasas
- Patrón de tests existente: `pytest-mock` con `mocker.patch`, ver `tests/test_app.py` como referencia

```python
# rates_service.py:15-46 — lo que necesita tests
class RatesService:
    BCV_URL = "https://www.bcv.org.ve/"
    BINANCE_P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

    def get_bcv_rates(self) -> Dict[str, float]:
        # Scraping con requests.get + BeautifulSoup
        ...

    def get_binance_p2p_rate(self, ...) -> float:
        # requests.post a API Binance
        ...

    def get_all_rates(self) -> Dict[str, float]:
        # Combina ambos y retorna dict con claves bcv_usd, bcv_eur, binance_p2p, timestamp
        ...
```

```python
# sync_ventas.py:116-124 — get_current_rate (después de aplicar plan 001)
def get_current_rate():
    try:
        from rates_service import RatesService
        service = RatesService()
        rates = service.get_all_rates()
        return rates.get("bcv_usd", rates.get("binance_p2p", FACTOR_USD_DEFAULT))
    except:
        return FACTOR_USD_DEFAULT
```

Modelo de tests existente (seguir este patrón de `tests/test_app.py`):
```python
def test_health_endpoint(client, mocker):
    mocker.patch("network_util.check_drive", return_value=True)
    response = client.get("/health")
    assert response.status_code == 200
```

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Tests antes | `python -m pytest tests/ -v` | Todos pasan (baseline) |
| Nuevo archivo | `python -m pytest tests/test_rates_service.py -v` | Todos los nuevos pasan |
| Tests completos | `python -m pytest tests/ -v` | Todos pasan |

## Scope

**En scope**:
- `tests/test_rates_service.py` — crear nuevo archivo

**Fuera de scope**:
- `rates_service.py` — no modificar (solo testear)
- `sync_ventas.py` — no modificar (plan 001 ya lo hizo)

## Git workflow

- Branch: `advisor/009-add-rates-service-tests`
- Commit: `test: agregar cobertura para rates_service y cascada de fallback de tasas`

## Pasos

### Paso 1: Crear `tests/test_rates_service.py`

```python
"""
tests/test_rates_service.py — Tests para rates_service.RatesService y get_current_rate().
"""
import pytest
from unittest.mock import MagicMock, patch


# ─── Tests de get_bcv_rates() ────────────────────────────────────────────────

class TestGetBcvRates:
    def test_parsea_usd_correctamente(self, mocker):
        """Extrae la tasa USD del HTML del BCV."""
        html_mock = """
        <html><body>
          <div id="dolar"><strong>55,50</strong></div>
          <div id="euro"><strong>60,20</strong></div>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html_mock
        mocker.patch("rates_service.requests.get", return_value=mock_resp)

        from rates_service import RatesService
        service = RatesService()
        rates = service.get_bcv_rates()

        assert rates["USD"] == 55.50
        assert rates["EUR"] == 60.20

    def test_retorna_ceros_si_html_cambia(self, mocker):
        """Retorna 0.0 si el HTML no tiene el div esperado."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><p>Mantenimiento</p></body></html>"
        mocker.patch("rates_service.requests.get", return_value=mock_resp)

        from rates_service import RatesService
        rates = RatesService().get_bcv_rates()

        assert rates["USD"] == 0.0
        assert rates["EUR"] == 0.0

    def test_retorna_ceros_en_error_http(self, mocker):
        """Retorna 0.0 si el request falla."""
        mocker.patch("rates_service.requests.get", side_effect=Exception("timeout"))

        from rates_service import RatesService
        rates = RatesService().get_bcv_rates()

        assert rates["USD"] == 0.0

    def test_retorna_ceros_si_status_no_es_200(self, mocker):
        """Retorna 0.0 si HTTP status != 200."""
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mocker.patch("rates_service.requests.get", return_value=mock_resp)

        from rates_service import RatesService
        rates = RatesService().get_bcv_rates()

        assert rates["USD"] == 0.0


# ─── Tests de get_binance_p2p_rate() ─────────────────────────────────────────

class TestGetBinanceP2pRate:
    def test_calcula_promedio_correctamente(self, mocker):
        """Calcula el promedio de los precios de Binance P2P."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "code": "000000",
            "data": [
                {"adv": {"price": "56.0"}},
                {"adv": {"price": "57.0"}},
                {"adv": {"price": "58.0"}},
            ]
        }
        mocker.patch("rates_service.requests.post", return_value=mock_resp)

        from rates_service import RatesService
        rate = RatesService().get_binance_p2p_rate()

        assert rate == 57.0

    def test_retorna_cero_en_error(self, mocker):
        """Retorna 0.0 si la API de Binance falla."""
        mocker.patch("rates_service.requests.post", side_effect=Exception("network error"))

        from rates_service import RatesService
        rate = RatesService().get_binance_p2p_rate()

        assert rate == 0.0

    def test_retorna_cero_si_data_vacia(self, mocker):
        """Retorna 0.0 si Binance no devuelve data."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": "000000", "data": []}
        mocker.patch("rates_service.requests.post", return_value=mock_resp)

        from rates_service import RatesService
        assert RatesService().get_binance_p2p_rate() == 0.0


# ─── Tests de get_all_rates() — claves del dict ───────────────────────────────

class TestGetAllRates:
    def test_retorna_claves_correctas(self, mocker):
        """get_all_rates() devuelve el dict con las claves que usan los consumidores."""
        mocker.patch.object(
            __import__("rates_service").RatesService,
            "get_bcv_rates",
            return_value={"USD": 55.5, "EUR": 60.0}
        )
        mocker.patch.object(
            __import__("rates_service").RatesService,
            "get_binance_p2p_rate",
            return_value=56.0
        )
        from rates_service import RatesService
        rates = RatesService().get_all_rates()

        assert "bcv_usd" in rates
        assert "bcv_eur" in rates
        assert "binance_p2p" in rates
        assert "timestamp" in rates
        assert rates["bcv_usd"] == 55.5
        assert rates["binance_p2p"] == 56.0


# ─── Tests de get_current_rate() en sync_ventas ───────────────────────────────
# Estos tests asumen que el plan 001 ya fue aplicado (claves bcv_usd, binance_p2p)

class TestGetCurrentRate:
    def test_usa_bcv_usd_cuando_disponible(self, mocker):
        """get_current_rate() devuelve bcv_usd cuando el scraping funciona."""
        mocker.patch(
            "sync_ventas.RatesService.get_all_rates",
            return_value={"bcv_usd": 55.5, "bcv_eur": 60.0, "binance_p2p": 56.0, "timestamp": 0}
        )
        import sync_ventas
        assert sync_ventas.get_current_rate() == 55.5

    def test_usa_binance_si_bcv_falla(self, mocker):
        """Si bcv_usd no está en el dict, cae a binance_p2p."""
        mocker.patch(
            "sync_ventas.RatesService.get_all_rates",
            return_value={"binance_p2p": 56.0, "timestamp": 0}  # sin bcv_usd
        )
        import sync_ventas
        assert sync_ventas.get_current_rate() == 56.0

    def test_retorna_default_si_todo_falla(self, mocker):
        """Si RatesService lanza excepción, retorna FACTOR_USD_DEFAULT."""
        mocker.patch("sync_ventas.RatesService", side_effect=Exception("network down"))
        import sync_ventas
        assert sync_ventas.get_current_rate() == sync_ventas.FACTOR_USD_DEFAULT

    def test_retorna_default_si_dict_vacio(self, mocker):
        """Si get_all_rates retorna dict vacío, retorna FACTOR_USD_DEFAULT."""
        mocker.patch(
            "sync_ventas.RatesService.get_all_rates",
            return_value={}
        )
        import sync_ventas
        assert sync_ventas.get_current_rate() == sync_ventas.FACTOR_USD_DEFAULT
```

**Verificar**: `python -m pytest tests/test_rates_service.py -v` → mínimo 10 tests pasan

### Paso 2: Verificar tests completos

```powershell
python -m pytest tests/ -v
```

Todos deben pasar.

## Criterios de done

- [ ] `tests/test_rates_service.py` existe con mínimo 12 tests
- [ ] Todos los tests de `TestGetCurrentRate` pasan (requiere plan 001 aplicado)
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo `tests/test_rates_service.py` fue creado (ningún archivo de producción modificado)
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- El plan 001 no fue aplicado → `TestGetCurrentRate.test_usa_bcv_usd_cuando_disponible` fallará. Aplicar plan 001 primero.
- `mocker.patch("sync_ventas.RatesService.get_all_rates", ...)` no funciona con la estructura actual → usar `mocker.patch.object` o importar y parchear a nivel de módulo.

## Notas de mantenimiento

- Si el HTML del BCV cambia estructura, los tests de `TestGetBcvRates` ayudarán a identificar el problema
- Los tests deben actualizarse si `get_all_rates()` agrega o renombra claves
