"""Generate SLD 1.0.0 XML from the geometry-keyed simple-style JSON.

Same JSON vocabulary as VectorTiler (tiling_service.py): keys Polygon /
LineString / Point, props fillColor, strokeColor, strokeWidth, opacity,
pointRadius.
"""
from xml.sax.saxutils import escape

ALLOWED_GEOMETRIES = {"Polygon", "LineString", "Point"}

_DEFAULTS = {
    "fillColor": "#3388ff",
    "strokeColor": "#3388ff",
    "strokeWidth": 1,
    "opacity": 1.0,
    "pointRadius": 5,
}


def _prop(style: dict, key: str) -> str:
    return escape(str(style.get(key, _DEFAULTS[key])))


def _polygon_symbolizer(s: dict) -> str:
    return f"""
        <sld:PolygonSymbolizer>
          <sld:Fill>
            <sld:CssParameter name="fill">{_prop(s, "fillColor")}</sld:CssParameter>
            <sld:CssParameter name="fill-opacity">{_prop(s, "opacity")}</sld:CssParameter>
          </sld:Fill>
          <sld:Stroke>
            <sld:CssParameter name="stroke">{_prop(s, "strokeColor")}</sld:CssParameter>
            <sld:CssParameter name="stroke-width">{_prop(s, "strokeWidth")}</sld:CssParameter>
          </sld:Stroke>
        </sld:PolygonSymbolizer>"""


def _line_symbolizer(s: dict) -> str:
    return f"""
        <sld:LineSymbolizer>
          <sld:Stroke>
            <sld:CssParameter name="stroke">{_prop(s, "strokeColor")}</sld:CssParameter>
            <sld:CssParameter name="stroke-width">{_prop(s, "strokeWidth")}</sld:CssParameter>
            <sld:CssParameter name="stroke-opacity">{_prop(s, "opacity")}</sld:CssParameter>
          </sld:Stroke>
        </sld:LineSymbolizer>"""


def _point_symbolizer(s: dict) -> str:
    size = 2 * float(s.get("pointRadius", _DEFAULTS["pointRadius"]))
    size_str = str(int(size)) if size == int(size) else str(size)
    return f"""
        <sld:PointSymbolizer>
          <sld:Graphic>
            <sld:Mark>
              <sld:WellKnownName>circle</sld:WellKnownName>
              <sld:Fill>
                <sld:CssParameter name="fill">{_prop(s, "fillColor")}</sld:CssParameter>
                <sld:CssParameter name="fill-opacity">{_prop(s, "opacity")}</sld:CssParameter>
              </sld:Fill>
              <sld:Stroke>
                <sld:CssParameter name="stroke">{_prop(s, "strokeColor")}</sld:CssParameter>
                <sld:CssParameter name="stroke-width">{_prop(s, "strokeWidth")}</sld:CssParameter>
              </sld:Stroke>
            </sld:Mark>
            <sld:Size>{escape(size_str)}</sld:Size>
          </sld:Graphic>
        </sld:PointSymbolizer>"""


_SYMBOLIZERS = {
    "Polygon": _polygon_symbolizer,
    "LineString": _line_symbolizer,
    "Point": _point_symbolizer,
}


def build_sld(style: dict, style_name: str) -> str:
    """Build an SLD 1.0.0 document from geometry-keyed simple-style JSON.

    Raises ValueError if `style` contains keys outside ALLOWED_GEOMETRIES.
    """
    unknown = set(style) - ALLOWED_GEOMETRIES
    if unknown:
        raise ValueError(f"Unknown geometry keys: {sorted(unknown)}")

    rules = []
    for geom in ("Polygon", "LineString", "Point"):
        if geom in style:
            rules.append(f"""
      <sld:Rule>
        <sld:Name>{escape(geom)}</sld:Name>{_SYMBOLIZERS[geom](style[geom] or {})}
      </sld:Rule>""")

    name = escape(style_name)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sld:StyledLayerDescriptor version="1.0.0"
    xmlns:sld="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <sld:NamedLayer>
    <sld:Name>{name}</sld:Name>
    <sld:UserStyle>
      <sld:Name>{name}</sld:Name>
      <sld:FeatureTypeStyle>{''.join(rules)}
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </sld:NamedLayer>
</sld:StyledLayerDescriptor>"""
