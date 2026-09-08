"""Render local legend PNGs for layer types without a server-side legend.

Pure Pillow/rasterio; no repository dependencies. Legends are cached next to the
tiles (`TILES_DIR/{layer_id}/legend.png`) and served by the existing
`/tiles/...` static mount. A fingerprint sidecar invalidates stale renders.
"""
import hashlib
import json
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

PAD = 16
ROW_H = 40
SWATCH_W = 44
SWATCH_H = 20

_DEFAULTS = {
    "fillColor": "#3388ff",
    "strokeColor": "#3388ff",
    "strokeWidth": 1,
    "opacity": 1.0,
    "pointRadius": 5,
}

# Pattern names shared with sld_builder / dashboard editor.
_STROKE_PATTERNS = {"solid": None, "dashed": (8, 4), "dotted": (1, 4), "dash-dot": (8, 4, 1, 4)}


def _font(size: int = 13):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def normalize_style(style) -> Optional[dict]:
    """Accept raw geometry-keyed JSON or the style-editor state wrapper
    ({mode, simple, sld_body}); return geometry-keyed dict or None."""
    if not isinstance(style, dict):
        return None
    if "simple" in style:
        style = style["simple"]
    if not isinstance(style, dict) or not style:
        return None
    return {k: (v or {}) for k, v in style.items() if isinstance(v, dict)}


def vector_fingerprint(style) -> str:
    return hashlib.sha256(
        json.dumps(normalize_style(style) or {}, sort_keys=True).encode()
    ).hexdigest()[:16]


def raster_fingerprint(source_path: Path) -> str:
    st = source_path.stat()
    return f"{st.st_size}-{int(st.st_mtime)}"


def _sidecar(out_path: Path) -> Path:
    return Path(str(out_path) + ".fp")


def is_stale(out_path: Path, fingerprint: str) -> bool:
    if not out_path.exists():
        return True
    try:
        return _sidecar(out_path).read_text() != fingerprint
    except OSError:
        return True


def _base_canvas(rows: int) -> tuple:
    width = max(220, PAD * 2 + SWATCH_W + 160)
    height = PAD * 2 + rows * ROW_H
    img = Image.new("RGB", (width, height), "white")
    return img, ImageDraw.Draw(img), img.width - PAD


def render_vector_legend(style, out_path: Path, fingerprint: str = None) -> Path:
    """Render one swatch row per geometry type (Point/LineString/Polygon)."""
    norm = normalize_style(style) or {}
    geoms = [g for g in ("Point", "LineString", "Polygon") if g in norm]
    if not geoms:
        geoms = ["Point", "LineString", "Polygon"]

    img, draw, right = _base_canvas(len(geoms))
    font = _font()
    y = PAD

    for geom in geoms:
        s = norm.get(geom) or {}
        mid = y + ROW_H // 2
        if geom == "Point":
            r = float(s.get("pointRadius", _DEFAULTS["pointRadius"]))
            cy = y + SWATCH_H // 2 + 3
            draw.ellipse(
                [PAD * 2 - r, cy - r, PAD * 2 + r, cy + r],
                fill=_rgb(s.get("fillColor", _DEFAULTS["fillColor"])),
                outline=_rgb(s.get("strokeColor", _DEFAULTS["strokeColor"])),
                width=max(1, int(s.get("strokeWidth", _DEFAULTS["strokeWidth"]))),
            )
        elif geom == "LineString":
            width = max(1, int(s.get("strokeWidth", _DEFAULTS["strokeWidth"])))
            pattern = _STROKE_PATTERNS.get(s.get("strokePattern", "solid"))
            if pattern:
                x, x2 = PAD, PAD + SWATCH_W
                for seg, gap in zip(pattern[::2], pattern[1::2] + (0,)):
                    draw.line([x, mid, min(x + seg, x2), mid], fill=_rgb(s.get("strokeColor", _DEFAULTS["strokeColor"])), width=width)
                    x += seg + gap
            else:
                draw.line([PAD, mid, PAD + SWATCH_W, mid], fill=_rgb(s.get("strokeColor", _DEFAULTS["strokeColor"])), width=width)
        else:  # Polygon
            fill = _rgb(s.get("fillColor", _DEFAULTS["fillColor"]))
            opacity = float(s.get("opacity", _DEFAULTS["opacity"]))
            draw.rectangle(
                [PAD, y + 2, PAD + SWATCH_W, y + SWATCH_H - 2],
                fill=fill + (int(255 * opacity),),
                outline=_rgb(s.get("strokeColor", _DEFAULTS["strokeColor"])),
                width=max(1, int(s.get("strokeWidth", _DEFAULTS["strokeWidth"]))),
            )
        draw.text((PAD * 2 + SWATCH_W + 10, y + (ROW_H - 14) // 2), geom, fill="black", font=font)
        y += ROW_H

    img.save(out_path)
    _sidecar(out_path).write_text(fingerprint or vector_fingerprint(style))
    return out_path


def render_raster_legend(source_path: Path, out_path: Path, fingerprint: str = None) -> Path:
    """Render discrete colormap swatches, or a min→max gradient bar."""
    import numpy as np
    import rasterio

    with rasterio.open(source_path) as src:
        try:
            cmap = src.colormap(1)
        except (ValueError, KeyError):  # "NULL color table" / no such band colormap
            cmap = None
        if cmap:
            rows = sorted(cmap.items())
            img, draw, right = _base_canvas(len(rows))
            font = _font()
            y = PAD
            for value, rgba in rows:
                draw.rectangle(
                    [PAD, y + 2, PAD + SWATCH_W, y + SWATCH_H - 2],
                    fill=tuple(rgba[:3]),
                )
                draw.text((PAD * 2 + SWATCH_W + 10, y + (ROW_H - 14) // 2), str(value), fill="black", font=font)
                y += ROW_H
            fp = fingerprint or f"cmap-{hashlib.sha256(json.dumps([[k, list(v)] for k, v in rows], sort_keys=True).encode()).hexdigest()[:16]}"
        else:
            # Downsampled read: cheap approx stats for the gradient labels.
            band = src.read(
                1,
                out_shape=(256, 256),
                window=((0, src.height), (0, src.width)),
            )
            valid = band[~band.mask] if hasattr(band, "mask") else band
            if valid.size == 0 or not np.any(np.isfinite(valid)):
                raise ValueError("Raster has no valid data to render a legend")
            lo, hi = float(np.nanmin(valid)), float(np.nanmax(valid))
            if lo == hi:
                hi = lo + 1
            img, draw, right = _base_canvas(2)
            bar_w = 200
            font = _font()
            grad = Image.new("RGB", (bar_w, 14))
            for i in range(bar_w):
                v = lo + (hi - lo) * i / (bar_w - 1)
                t = (v - lo) / (hi - lo)
                # viridis-like ramp: dark purple -> teal -> yellow
                for yy in range(14):
                    grad.putpixel((i, yy), _viridis(t))
            img.paste(grad, (PAD, PAD))
            draw.text((PAD, PAD + 18), _fmt(lo), fill="black", font=font)
            draw.text((PAD + bar_w - 60, PAD + 18), _fmt(hi), fill="black", font=font)
            draw.text((PAD, PAD + 38), "Value (low → high)", fill="black", font=font)
            fp = fingerprint or f"grad-{lo:.4g}-{hi:.4g}"
    img.save(out_path)
    _sidecar(out_path).write_text(fp)
    return out_path


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def _viridis(t: float) -> tuple:
    # 5-stop approximation of the viridis ramp.
    stops = [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)]
    x = t * (len(stops) - 1)
    i = min(int(x), len(stops) - 2)
    f = x - i
    a, b = stops[i], stops[i + 1]
    return tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3))