import pytest
from defusedxml.ElementTree import fromstring

from app.infrastructure.services.sld_builder import build_sld, ALLOWED_GEOMETRIES

NS = {
    "sld": "http://www.opengis.net/sld",
    "se": "http://www.opengis.net/sld",
}


def _parse(xml: str):
    return fromstring(xml.encode())


def test_polygon_style_produces_polygon_symbolizer():
    xml = build_sld({"Polygon": {"fillColor": "#ff0000", "strokeColor": "#000000",
                                 "strokeWidth": 2, "opacity": 0.5}}, "layer_abc")
    root = _parse(xml)
    polys = root.findall(".//{http://www.opengis.net/sld}PolygonSymbolizer")
    assert len(polys) == 1
    assert "#ff0000" in xml
    assert "#000000" in xml
    assert ">0.5<" in xml  # fill-opacity
    assert ">2<" in xml    # stroke-width


def test_only_present_geometry_keys_emit_symbolizers():
    xml = build_sld({"LineString": {"strokeColor": "#e33333", "strokeWidth": 3}}, "layer_abc")
    root = _parse(xml)
    assert root.findall(".//{http://www.opengis.net/sld}LineSymbolizer")
    assert not root.findall(".//{http://www.opengis.net/sld}PolygonSymbolizer")
    assert not root.findall(".//{http://www.opengis.net/sld}PointSymbolizer")


def test_point_style_uses_circle_mark_and_size():
    xml = build_sld({"Point": {"fillColor": "#00ff00", "pointRadius": 6}}, "layer_abc")
    root = _parse(xml)
    assert root.findall(".//{http://www.opengis.net/sld}PointSymbolizer")
    assert "circle" in xml
    assert ">12<" in xml  # size = 2 * pointRadius


def test_defaults_applied_when_props_missing():
    xml = build_sld({"Polygon": {}}, "layer_abc")
    assert "#3388ff" in xml  # default fill


def test_style_name_embedded_and_values_escaped():
    xml = build_sld({"Polygon": {"fillColor": "#111<>&"}}, "layer_x")
    assert "<sld:Name>layer_x</sld:Name>" in xml
    assert "<>&" not in xml.split("layer_x")[-1]  # escaped in property values


def test_unknown_geometry_key_raises():
    with pytest.raises(ValueError):
        build_sld({"Circle": {}}, "layer_abc")


def test_valid_xml_output():
    xml = build_sld({"Polygon": {}, "LineString": {}, "Point": {}}, "layer_abc")
    _parse(xml)  # must not raise
    assert "1.0.0" in xml
