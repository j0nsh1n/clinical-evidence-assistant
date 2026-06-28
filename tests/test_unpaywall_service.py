"""Unit tests for the Unpaywall open-access lookup (no network)."""

from app.services import unpaywall_service


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def test_find_open_access_hit(monkeypatch):
    payload = {"is_oa": True, "best_oa_location": {"url_for_pdf": "https://oa/x.pdf", "url": "https://oa/x"}}
    monkeypatch.setattr(unpaywall_service.httpx, "get", lambda *a, **k: _Resp(200, payload))
    result = unpaywall_service.find_open_access("10.1/x")
    assert result["is_open_access"] is True
    assert result["oa_url"] == "https://oa/x.pdf"


def test_find_open_access_miss(monkeypatch):
    monkeypatch.setattr(unpaywall_service.httpx, "get", lambda *a, **k: _Resp(200, {"is_oa": False}))
    result = unpaywall_service.find_open_access("10.1/x")
    assert result["is_open_access"] is False
    assert result["oa_url"] is None


def test_find_open_access_empty_doi():
    assert unpaywall_service.find_open_access("")["is_open_access"] is False


def test_find_open_access_strips_doi_prefix(monkeypatch):
    seen = {}

    def fake_get(url, *a, **k):
        seen["url"] = url
        return _Resp(200, {"is_oa": False})

    monkeypatch.setattr(unpaywall_service.httpx, "get", fake_get)
    unpaywall_service.find_open_access("https://doi.org/10.1/ABC")
    assert seen["url"].endswith("/10.1/abc")


def test_find_open_access_network_error_is_swallowed(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(unpaywall_service.httpx, "get", boom)
    assert unpaywall_service.find_open_access("10.1/x")["is_open_access"] is False
