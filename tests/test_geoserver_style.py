import pytest

import app.infrastructure.services.geoserver_service as gs_mod
from app.infrastructure.services.geoserver_service import GeoServerService, GeoServerStyleError


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def svc(monkeypatch):
    # Avoid real Geoserver() network setup side effects: patch nothing —
    # geo.Geoserver.__init__ does no network I/O, safe to construct.
    return GeoServerService("http://gs:8080/geoserver", "admin", "pw", "tileserver")


def test_upsert_style_put_success(svc, monkeypatch):
    # Style already exists (GET .json -> 200) -> update via PUT.
    calls = []
    monkeypatch.setattr(gs_mod.requests, "get",
                        lambda url, **kw: calls.append(("GET", url)) or FakeResponse(200))
    monkeypatch.setattr(gs_mod.requests, "put",
                        lambda url, **kw: calls.append(("PUT", url)) or FakeResponse(200))
    svc.upsert_style("layer_abc", "<sld/>")
    assert calls == [
        ("GET", "http://gs:8080/geoserver/rest/workspaces/tileserver/styles/layer_abc.json"),
        ("PUT", "http://gs:8080/geoserver/rest/workspaces/tileserver/styles/layer_abc"),
    ]


def test_upsert_style_creates_on_404(svc, monkeypatch):
    # Style does not exist (GET .json -> 404) -> create via POST.
    calls = []
    monkeypatch.setattr(gs_mod.requests, "get",
                        lambda url, **kw: calls.append(("GET", url)) or FakeResponse(404))
    monkeypatch.setattr(gs_mod.requests, "post",
                        lambda url, **kw: calls.append(("POST", url)) or FakeResponse(201))
    svc.upsert_style("layer_abc", "<sld/>")
    assert calls[0][0] == "GET"
    assert calls[1] == ("POST", "http://gs:8080/geoserver/rest/workspaces/tileserver/styles?name=layer_abc")


def test_upsert_style_400_maps_to_422(svc, monkeypatch):
    monkeypatch.setattr(gs_mod.requests, "get",
                        lambda url, **kw: FakeResponse(200))
    monkeypatch.setattr(gs_mod.requests, "put",
                        lambda url, **kw: FakeResponse(400, "Invalid SLD"))
    with pytest.raises(GeoServerStyleError) as exc:
        svc.upsert_style("layer_abc", "<bad/>")
    assert exc.value.http_status == 422
    assert "Invalid SLD" in exc.value.detail


def test_upsert_style_connection_error_maps_to_502(svc, monkeypatch):
    def boom(url, **kw):
        raise gs_mod.requests.ConnectionError("refused")
    monkeypatch.setattr(gs_mod.requests, "get", boom)
    with pytest.raises(GeoServerStyleError) as exc:
        svc.upsert_style("layer_abc", "<sld/>")
    assert exc.value.http_status == 502


def test_set_default_style_success(svc, monkeypatch):
    captured = {}
    def fake_put(url, **kw):
        captured["url"] = url
        captured["json"] = kw.get("json")
        return FakeResponse(200)
    monkeypatch.setattr(gs_mod.requests, "put", fake_put)
    svc.set_default_style("tileserver:roads", "layer_abc")
    assert captured["url"] == "http://gs:8080/geoserver/rest/layers/tileserver:roads.json"
    assert captured["json"] == {"layer": {"defaultStyle": {"name": "tileserver:layer_abc"}}}


def test_set_default_style_failure_maps_to_502(svc, monkeypatch):
    monkeypatch.setattr(gs_mod.requests, "put", lambda url, **kw: FakeResponse(500, "boom"))
    with pytest.raises(GeoServerStyleError) as exc:
        svc.set_default_style("tileserver:roads", "layer_abc")
    assert exc.value.http_status == 502
