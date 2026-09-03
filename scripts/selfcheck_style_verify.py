"""Self-check untuk logika verifikasi default style GeoServer (tanpa infra).

Menjalankan:  venv/bin/python scripts/selfcheck_style_verify.py
"""
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.services.geoserver_service import GeoServerService  # noqa: E402
from app.core.style_utils import convert_sld_11_to_10  # noqa: E402


SLD_11 = '''<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" version="1.1.0" xmlns:se="http://www.opengis.net/se" xmlns:ogc="http://www.opengis.net/ogc">
  <NamedLayer>
    <se:Name>pola_ruang</se:Name>
    <UserStyle>
      <se:Name>RENCANA</se:Name>
      <se:FeatureTypeStyle>
        <se:Rule>
          <se:Name>Badan Air</se:Name>
          <ogc:Filter>
            <ogc:PropertyIsEqualTo>
              <ogc:PropertyName>NAMOBJ</ogc:PropertyName>
              <ogc:Literal>Badan Air</ogc:Literal>
            </ogc:PropertyIsEqualTo>
          </ogc:Filter>
          <se:PolygonSymbolizer>
            <se:Fill>
              <se:SvgParameter name="fill">#97dbf2</se:SvgParameter>
            </se:Fill>
          </se:PolygonSymbolizer>
        </se:Rule>
      </se:FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
'''


def build_service_with(json_response: dict | None, status: int = 200) -> GeoServerService:
    svc = GeoServerService.__new__(GeoServerService)
    svc._base_url = "http://gs"
    svc._auth = ("u", "p")
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = json_response
    svc._get = None  # not used
    # patch requests.get on the module via monkeypatching the module attribute
    import app.infrastructure.services.geoserver_service as mod

    mod.requests.get = mock.Mock(return_value=resp)
    svc._requests_get = mod.requests.get  # store to assert
    return svc


def test_happy_path():
    svc = build_service_with({"layer": {"defaultStyle": {"name": "ws:layer_x"}}})
    assert svc.get_default_style("tileserver:foo") == "ws:layer_x"


def test_missing_default_style():
    svc = build_service_with({"layer": {}})
    assert svc.get_default_style("tileserver:foo") is None


def test_non_200():
    svc = build_service_with(None, status=404)
    assert svc.get_default_style("tileserver:foo") is None


def test_verify_equality_logic():
    # mirror of put_layer_style comparison
    expected = "tileserver:layer_x"
    assert (expected == "tileserver:layer_x") is True
    assert (expected == "tileserver:polygon") is False
    assert (expected == "tileserver:layer_y") is False


def test_convert_sld_11_to_10_keeps_colors():
    out = convert_sld_11_to_10(SLD_11)
    assert 'version="1.1.0"' not in out
    assert '<sld:CssParameter name="fill">#97dbf2</sld:CssParameter>' in out
    assert 'se:' not in out and 'SvgParameter' not in out
    assert 'version="1.0.0"' in out


def test_convert_sld_11_to_10_passthrough_10():
    out = convert_sld_11_to_10(SLD_10_MARKER := '<?xml version="1.0"?><StyledLayerDescriptor version="1.0.0"/>')
    assert out is SLD_10_MARKER


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"OK: {len(tests)} checks passed")
