"""Behavior of orphan cleanup in Supabase when some orphans are FK-protected.

A product that still has sales history cannot be deleted (HTTP 409 / 23503).
That must not block deleting the other orphans, nor be swallowed silently.
"""
import io
import json
import urllib.error
import urllib.parse

import pytest

import supabase_rest

VALID = [f"V{i}" for i in range(12)]  # >= _MIN_SAFE_IDS so the safeguard passes


class FakeCloud:
    """Minimal PostgREST double: GET lists ids, DELETE removes unless FK-protected."""

    def __init__(self, ids, fk_protected=()):
        self.ids = set(ids)
        self.fk_protected = set(fk_protected)
        self.deleted = []

    def urlopen(self, req, timeout=None):
        if req.get_method() == "GET":
            return _Resp(json.dumps([{"codigo_interno": i} for i in sorted(self.ids)]))
        query = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        raw = query["codigo_interno"][0]  # in.("A","B")
        targets = [t.strip('"') for t in raw[len("in.("):-1].split(",")]
        if any(t in self.fk_protected for t in targets):
            body = json.dumps({"code": "23503", "message": "violates foreign key"})
            raise urllib.error.HTTPError(req.full_url, 409, "Conflict", {}, io.BytesIO(body.encode()))
        self.ids -= set(targets)
        self.deleted += targets
        return _Resp("")


class _Resp:
    def __init__(self, body):
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def cloud_factory(mocker, monkeypatch):
    monkeypatch.setattr(supabase_rest, "REST_URL", "https://example.supabase.co")
    monkeypatch.setattr(supabase_rest, "ANON_KEY", "anon")

    def make(orphans, fk_protected=()):
        cloud = FakeCloud(VALID + list(orphans), fk_protected)
        mocker.patch("urllib.request.urlopen", side_effect=cloud.urlopen)
        return cloud

    return make


def test_deletes_all_orphans_when_none_is_protected(cloud_factory):
    cloud = cloud_factory(["X1", "X2"])
    assert supabase_rest.delete_orphans_rest(VALID) is True
    assert sorted(cloud.deleted) == ["X1", "X2"]


def test_fk_protected_orphan_does_not_block_the_others(cloud_factory):
    cloud = cloud_factory(["X1", "B", "X2"], fk_protected=["B"])
    supabase_rest.delete_orphans_rest(VALID)
    assert sorted(cloud.deleted) == ["X1", "X2"]
    assert "B" in cloud.ids


def test_fk_protected_orphan_is_reported_not_swallowed(cloud_factory, capsys):
    cloud_factory(["B"], fk_protected=["B"])
    result = supabase_rest.delete_orphans_rest(VALID)
    assert result is True  # known/expected condition, not a failure
    assert "B" in capsys.readouterr().out
