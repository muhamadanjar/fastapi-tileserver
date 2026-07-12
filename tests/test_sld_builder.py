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


def test_dashed_stroke_emits_dasharray():
    xml = build_sld({"LineString": {"strokePattern": "dashed"}}, "layer_abc")
    assert '<sld:CssParameter name="stroke-dasharray">8 4</sld:CssParameter>' in xml
    _parse(xml)


def test_dash_dot_stroke_on_polygon_outline():
    xml = build_sld({"Polygon": {"strokePattern": "dash-dot"}}, "layer_abc")
    assert '"stroke-dasharray">8 4 1 4<' in xml
    _parse(xml)


def test_solid_stroke_emits_no_dasharray():
    xml = build_sld({"LineString": {"strokePattern": "solid"}, "Polygon": {}}, "layer_abc")
    assert "stroke-dasharray" not in xml


def test_hatched_fill_uses_graphic_fill_slash_mark():
    xml = build_sld({"Polygon": {"fillPattern": "hatched", "fillColor": "#ff0000"}}, "layer_abc")
    root = _parse(xml)
    assert root.findall(".//{http://www.opengis.net/sld}GraphicFill")
    assert "shape://slash" in xml
    assert "#ff0000" in xml  # fillColor drives the mark stroke


def test_cross_hatched_and_dotted_fill_marks():
    assert "shape://times" in build_sld({"Polygon": {"fillPattern": "cross-hatched"}}, "l")
    assert "shape://dot" in build_sld({"Polygon": {"fillPattern": "dotted"}}, "l")


def test_solid_fill_has_no_graphic_fill():
    xml = build_sld({"Polygon": {"fillPattern": "solid"}}, "layer_abc")
    assert "GraphicFill" not in xml
    assert '<sld:CssParameter name="fill">' in xml


def test_unknown_stroke_pattern_raises():
    with pytest.raises(ValueError, match="strokePattern"):
        build_sld({"LineString": {"strokePattern": "zigzag"}}, "layer_abc")


def test_unknown_fill_pattern_raises():
    with pytest.raises(ValueError, match="fillPattern"):
        build_sld({"Polygon": {"fillPattern": "stars"}}, "layer_abc")
