"""Helpers for the per-layer WMS style editor state stored in file_metadata."""
from typing import Optional


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
