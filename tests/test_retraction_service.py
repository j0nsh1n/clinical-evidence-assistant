"""Unit tests for the retraction check (no network)."""

from app.services import retraction_service


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def test_pub_type_retracted_publication_flags():
    assert retraction_service.retracted_in_pub_types(["Journal Article", "Retracted Publication"]) is True


def test_pub_type_retraction_notice_does_not_flag():
    # "Retraction of Publication" tags the retraction NOTICE, not a retracted article.
    assert retraction_service.retracted_in_pub_types(["Retraction of Publication"]) is False
    assert retraction_service.retracted_in_pub_types([]) is False
    assert retraction_service.retracted_in_pub_types(None) is False


def test_check_retraction_prefers_pub_types_no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network must not be touched when pub types already flag it")

    monkeypatch.setattr(retraction_service.httpx, "get", boom)
    result = retraction_service.check_retraction("10.1/x", ["Retracted Publication"])
    assert result["is_retracted"] is True
    assert result["retraction_source"] == "publication-type tag"


def test_check_retraction_openalex_hit(monkeypatch):
    seen = {}

    def fake_get(url, *a, **k):
        seen["url"] = url
        return _Resp(200, {"is_retracted": True})

    monkeypatch.setattr(retraction_service.httpx, "get", fake_get)
    result = retraction_service.check_retraction("https://doi.org/10.1/ABC", [])
    assert result["is_retracted"] is True
    assert "Retraction Watch" in result["retraction_source"]
    assert seen["url"].endswith("/doi:10.1/abc")


def test_check_retraction_openalex_miss(monkeypatch):
    monkeypatch.setattr(retraction_service.httpx, "get", lambda *a, **k: _Resp(200, {"is_retracted": False}))
    result = retraction_service.check_retraction("10.1/x", [])
    assert result == {"is_retracted": False, "retraction_source": None}


def test_check_retraction_404_and_errors_swallowed(monkeypatch):
    monkeypatch.setattr(retraction_service.httpx, "get", lambda *a, **k: _Resp(404, {}))
    assert retraction_service.check_retraction("10.1/x")["is_retracted"] is False

    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(retraction_service.httpx, "get", boom)
    assert retraction_service.check_retraction("10.1/x")["is_retracted"] is False


def test_check_retraction_empty_doi_no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no network for empty DOI")

    monkeypatch.setattr(retraction_service.httpx, "get", boom)
    assert retraction_service.check_retraction("")["is_retracted"] is False
    assert retraction_service.check_retraction(None)["is_retracted"] is False
