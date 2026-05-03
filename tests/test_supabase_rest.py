import pytest
import responses
import json
from supabase_rest import upsert_batch_rest, get_row_count_rest

@responses.activate
def test_upsert_batch_rest_success():
    # Mocking the REST_URL and ANON_KEY if not set
    import supabase_rest
    supabase_rest.REST_URL = "https://example.supabase.co"
    supabase_rest.ANON_KEY = "test-key"
    
    url = "https://example.supabase.co/rest/v1/productos?on_conflict=codigo_interno"
    responses.add(responses.POST, url, status=201)
    
    rows = [{"codigo_interno": "1", "descripcion": "TEST"}]
    result = upsert_batch_rest(rows)
    
    assert result is True
    assert len(responses.calls) == 1
    # Check payload
    sent_payload = json.loads(responses.calls[0].request.body)
    assert sent_payload[0]["codigo_interno"] == "1"

from unittest.mock import MagicMock

def test_get_row_count_rest(mocker):
    import supabase_rest
    supabase_rest.REST_URL = "https://example.supabase.co"
    supabase_rest.ANON_KEY = "test-key"
    
    mock_resp = MagicMock()
    mock_resp.getheader.return_value = "0-0/100"
    mock_resp.__enter__.return_value = mock_resp
    mocker.patch("urllib.request.urlopen", return_value=mock_resp)
    
    count = get_row_count_rest()
    assert count == 100
