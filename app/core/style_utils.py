"""Helpers for the per-layer WMS style editor state stored in file_metadata."""
import re
import xml.etree.ElementTree as ET
from typing import Optional


_UNPREFIXED_TAGS = (
    "Name", "NamedLayer", "UserStyle", "FeatureTypeStyle",
    "Description", "Title", "Abstract",
)


def convert_sld_11_to_10(s: str) -> str:
    """Rewrite an SLD 1.1.0 (se:) document as SLD 1.0.0 before upload.

    GeoServer re-serializes uploaded SLDs itself, and its 1.1.0->1.0.0
    passthrough drops every `se:SvgParameter`, leaving `<sld:Fill/>` empty
    (observed on GeoServer 3.0.0: DB had 21 colors, stored style had 0).
    Instead we translate to 1.0.0 ourselves (SvgParameter->CssParameter) so
    the stored style keeps its colors. Returns the input untouched when it is
    already 1.0.0; raises ValueError on malformed XML.
    """
    if 'version="1.0.0"' in s:
        return s
    ET.fromstring(s)  # reject malformed XML before we touch it
    s = re.sub(
        r'<StyledLayerDescriptor\s[^>]*>',
        '<sld:StyledLayerDescriptor xmlns:sld="http://www.opengis.net/sld" '
        'xmlns:ogc="http://www.opengis.net/ogc" version="1.0.0" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.opengis.net/sld '
        'http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">',
        s, count=1,
    )
    s = s.replace("se:", "sld:")
    s = s.replace("SvgParameter", "CssParameter")
    for tag in _UNPREFIXED_TAGS:
        s = re.sub(rf"<(/?)(?!#){tag}(?=[ >/])", rf"<\1sld:{tag}", s)
    s = re.sub(r"</\s*StyledLayerDescriptor\s*>", "</sld:StyledLayerDescriptor>", s)
    ET.fromstring(s)
    return s


def merge_style_state(
    previous: Optional[dict],
    *,
    mode: str,
    style_name: str,
    sld_body: str,
    style: Optional[dict] = None,
) -> dict:
    """Merge a style save into the stored editor state without discarding
    the other mode's settings.

    `mode` marks which representation is active (installed in GeoServer).
    A `simple` save also stores the generated SLD so both editor tabs stay
    in sync; an `sld` save keeps the last simple settings untouched.
    """
    state = dict(previous or {})
    state["mode"] = mode
    state["style_name"] = style_name
    state["sld_body"] = sld_body
    if mode == "simple":
        state["style"] = style
    return state
