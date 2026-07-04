"""
tests/test_rates_service.py — Tests para RatesService y get_current_rate().
"""
import pytest
from unittest.mock import MagicMock


# ─── Tests de get_bcv_rates() ─────────────────────────────────────────────────

class TestGetBcvRates:
    def test_parsea_usd_y_eur_correctamente(self, mocker):
        """Extrae tasas USD y EUR del HTML del BCV."""
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
        rates = RatesService().get_bcv_rates()

        assert rates["USD"] == 55.50
        assert rates["EUR"] == 60.20

    def test_retorna_ceros_si_html_cambia_estructura(self, mocker):
        """Retorna 0.0 si el HTML no tiene el div esperado."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><p>Mantenimiento</p></body></html>"
        mocker.patch("rates_service.requests.get", return_value=mock_resp)

        from rates_service import RatesService
        rates = RatesService().get_bcv_rates()

        assert rates["USD"] == 0.0
        assert rates["EUR"] == 0.0

    def test_retorna_ceros_en_excepcion_de_red(self, mocker):
        """Retorna 0.0 si el request falla con excepción."""
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


# ─── Tests de get_binance_p2p_rate() ──────────────────────────────────────────

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

    def test_retorna_cero_en_error_de_red(self, mocker):
        """Retorna 0.0 si la API de Binance falla."""
        mocker.patch("rates_service.requests.post", side_effect=Exception("network error"))

        from rates_service import RatesService
        assert RatesService().get_binance_p2p_rate() == 0.0

    def test_retorna_cero_si_data_vacia(self, mocker):
        """Retorna 0.0 si Binance devuelve lista de data vacía."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": "000000", "data": []}
        mocker.patch("rates_service.requests.post", return_value=mock_resp)

        from rates_service import RatesService
        assert RatesService().get_binance_p2p_rate() == 0.0


# ─── Tests de get_all_rates() ─────────────────────────────────────────────────

class TestGetAllRates:
    def test_devuelve_claves_correctas(self, mocker):
        """get_all_rates() devuelve las claves que usan los consumidores."""
        mocker.patch("rates_service.RatesService.get_bcv_rates",
                     return_value={"USD": 55.5, "EUR": 60.0})
        mocker.patch("rates_service.RatesService.get_binance_p2p_rate",
                     return_value=56.0)

        from rates_service import RatesService
        rates = RatesService().get_all_rates()

        assert "bcv_usd" in rates
        assert "bcv_eur" in rates
        assert "binance_p2p" in rates
        assert "timestamp" in rates
        assert rates["bcv_usd"] == 55.5
        assert rates["binance_p2p"] == 56.0


# ─── Tests de get_current_rate() en sync_ventas ───────────────────────────────

class TestGetCurrentRate:
    def test_usa_bcv_usd_cuando_disponible(self, mocker):
        """get_current_rate() devuelve bcv_usd cuando el scraping funciona."""
        mocker.patch("rates_service.RatesService.get_all_rates",
                     return_value={"bcv_usd": 55.5, "bcv_eur": 60.0,
                                   "binance_p2p": 56.0, "timestamp": 0})
        import sync_ventas
        assert sync_ventas.get_current_rate() == 55.5

    def test_usa_binance_si_no_hay_bcv_usd(self, mocker):
        """Si bcv_usd no está en el dict, cae a binance_p2p."""
        mocker.patch("rates_service.RatesService.get_all_rates",
                     return_value={"binance_p2p": 56.0, "timestamp": 0})
        import sync_ventas
        assert sync_ventas.get_current_rate() == 56.0

    def test_retorna_default_si_todo_falla(self, mocker):
        """Si RatesService lanza excepción, retorna FACTOR_USD_DEFAULT."""
        mocker.patch("rates_service.RatesService.__init__",
                     side_effect=Exception("network down"))
        import sync_ventas
        assert sync_ventas.get_current_rate() == sync_ventas.FACTOR_USD_DEFAULT

    def test_retorna_default_si_dict_vacio(self, mocker):
        """Si get_all_rates retorna dict vacío, retorna FACTOR_USD_DEFAULT."""
        mocker.patch("rates_service.RatesService.get_all_rates", return_value={})
        import sync_ventas
        assert sync_ventas.get_current_rate() == sync_ventas.FACTOR_USD_DEFAULT

    def test_ssl_no_desactivado_en_scraper(self):
        """El scraper BCV no debe usar verify=False."""
        import inspect
        from rates_service import RatesService
        source = inspect.getsource(RatesService.get_bcv_rates)
        assert "verify=False" not in source
