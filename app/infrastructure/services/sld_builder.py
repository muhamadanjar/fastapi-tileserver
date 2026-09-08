"""Generate SLD 1.0.0 XML from the geometry-keyed simple-style JSON.

Same JSON vocabulary as VectorTiler (tiling_service.py) and the dashboard
style editor: keys Polygon / LineString / Point, props fillColor,
strokeColor, strokeWidth, opacity, pointRadius, strokePattern, fillPattern.

Built with xml.etree.ElementTree so escaping and indentation are handled by
the stdlib instead of hand-assembled f-strings.
"""
import xml.etree.ElementTree as ET

ALLOWED_GEOMETRIES = {"Polygon", "LineString", "Point"}

_DEFAULTS = {
    "fillColor": "#3388ff",
    "strokeColor": "#3388ff",
    "strokeWidth": 1,
    "opacity": 1.0,
    "pointRadius": 5,
}

# Pattern names are shared verbatim with the dashboard editor (types.ts).
STROKE_PATTERNS = {
    "solid": None,
    "dashed": "8 4",
    "dotted": "1 4",
    "dash-dot": "8 4 1 4",
}

# GeoServer well-known fill marks; shape:// marks render with stroke params only.
FILL_PATTERNS = {
    "solid": None,
    "hatched": "shape://slash",
    "cross-hatched": "shape://times",
    "dotted": "shape://dot",
}

_SLD = "http://www.opengis.net/sld"
_OGC = "http://www.opengis.net/ogc"
_XLINK = "http://www.w3.org/1999/xlink"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def _q(tag: str) -> str:
    return f"{{{_SLD}}}{tag}"


def _prop(style: dict, key: str) -> str:
    return str(style.get(key, _DEFAULTS[key]))


def _css(parent: ET.Element, name: str, value: str) -> None:
    el = ET.SubElement(parent, _q("CssParameter"))
    el.set("name", name)
    el.text = value


def _dasharray_param(stroke: ET.Element, s: dict) -> None:
    pattern = s.get("strokePattern", "solid")
    if pattern not in STROKE_PATTERNS:
        raise ValueError(
            f"Unknown strokePattern: {pattern!r}. Allowed: {sorted(STROKE_PATTERNS)}"
        )
    dasharray = STROKE_PATTERNS[pattern]
    if dasharray is not None:
        _css(stroke, "stroke-dasharray", dasharray)


def _polygon_fill(parent: ET.Element, s: dict) -> None:
    fill = ET.SubElement(parent, _q("Fill"))
    pattern = s.get("fillPattern", "solid")
    if pattern not in FILL_PATTERNS:
        raise ValueError(
            f"Unknown fillPattern: {pattern!r}. Allowed: {sorted(FILL_PATTERNS)}"
        )
    mark = FILL_PATTERNS[pattern]
    if mark is None:
        _css(fill, "fill", _prop(s, "fillColor"))
        _css(fill, "fill-opacity", _prop(s, "opacity"))
        return
    graphic_fill = ET.SubElement(fill, _q("GraphicFill"))
    graphic = ET.SubElement(graphic_fill, _q("Graphic"))
    mark_el = ET.SubElement(graphic, _q("Mark"))
    ET.SubElement(mark_el, _q("WellKnownName")).text = mark
    mark_stroke = ET.SubElement(mark_el, _q("Stroke"))
    _css(mark_stroke, "stroke", _prop(s, "fillColor"))
    _css(mark_stroke, "stroke-width", "1")
    _css(mark_stroke, "stroke-opacity", _prop(s, "opacity"))
    ET.SubElement(graphic, _q("Size")).text = "8"


def _polygon_symbolizer(parent: ET.Element, s: dict) -> None:
    sym = ET.SubElement(parent, _q("PolygonSymbolizer"))
    _polygon_fill(sym, s)
    stroke = ET.SubElement(sym, _q("Stroke"))
    _css(stroke, "stroke", _prop(s, "strokeColor"))
    _css(stroke, "stroke-width", _prop(s, "strokeWidth"))
    _dasharray_param(stroke, s)


def _line_symbolizer(parent: ET.Element, s: dict) -> None:
    sym = ET.SubElement(parent, _q("LineSymbolizer"))
    stroke = ET.SubElement(sym, _q("Stroke"))
    _css(stroke, "stroke", _prop(s, "strokeColor"))
    _css(stroke, "stroke-width", _prop(s, "strokeWidth"))
    _css(stroke, "stroke-opacity", _prop(s, "opacity"))
    _dasharray_param(stroke, s)


def _point_symbolizer(parent: ET.Element, s: dict) -> None:
    sym = ET.SubElement(parent, _q("PointSymbolizer"))
    graphic = ET.SubElement(sym, _q("Graphic"))
    mark = ET.SubElement(graphic, _q("Mark"))
    ET.SubElement(mark, _q("WellKnownName")).text = "circle"
    fill = ET.SubElement(mark, _q("Fill"))
    _css(fill, "fill", _prop(s, "fillColor"))
    _css(fill, "fill-opacity", _prop(s, "opacity"))
    stroke = ET.SubElement(mark, _q("Stroke"))
    _css(stroke, "stroke", _prop(s, "strokeColor"))
    _css(stroke, "stroke-width", _prop(s, "strokeWidth"))
    size = 2 * float(s.get("pointRadius", _DEFAULTS["pointRadius"]))
    size_str = str(int(size)) if size == int(size) else str(size)
    ET.SubElement(graphic, _q("Size")).text = size_str


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

    ET.register_namespace("sld", _SLD)
    ET.register_namespace("ogc", _OGC)
    ET.register_namespace("xlink", _XLINK)
    ET.register_namespace("xsi", _XSI)

    root = ET.Element(_q("StyledLayerDescriptor"), version="1.0.0")
    root.set(
        f"{{{_XSI}}}schemaLocation",
        f"{_SLD} http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd",
    )

    named_layer = ET.SubElement(root, _q("NamedLayer"))
    ET.SubElement(named_layer, _q("Name")).text = style_name
    user_style = ET.SubElement(named_layer, _q("UserStyle"))
    ET.SubElement(user_style, _q("Name")).text = style_name
    fts = ET.SubElement(user_style, _q("FeatureTypeStyle"))

    for geom in ("Polygon", "LineString", "Point"):
        if geom in style:
            rule = ET.SubElement(fts, _q("Rule"))
            ET.SubElement(rule, _q("Name")).text = geom
            _SYMBOLIZERS[geom](rule, style[geom] or {})

    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml