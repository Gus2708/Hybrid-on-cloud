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

@responses.activate
def test_get_row_count_rest():
    # get_row_count_rest usa requests y lee la cabecera Content-Range.
    # El test anterior mockeaba urllib.request.urlopen y por eso salía a la red.
    import supabase_rest
    supabase_rest.REST_URL = "https://example.supabase.co"
    supabase_rest.ANON_KEY = "test-key"

    responses.add(
        responses.GET,
        "https://example.supabase.co/rest/v1/productos",
        status=206,
        headers={"Content-Range": "0-0/100"},
    )

    assert get_row_count_rest() == 100
    assert len(responses.calls) == 1


@responses.activate
def test_get_row_count_rest_sin_content_range():
    import supabase_rest
    supabase_rest.REST_URL = "https://example.supabase.co"
    supabase_rest.ANON_KEY = "test-key"

    responses.add(
        responses.GET,
        "https://example.supabase.co/rest/v1/productos",
        status=200,
    )

    assert get_row_count_rest() == -1
