# WMS Layer Style Editing (Per-Layer GeoServer SLD) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each GeoServer-published WMS layer be styled individually — simple JSON (backend generates SLD) or raw SLD — via `PUT/GET /api/v1/layers/{layer_id}/style`.

**Architecture:** New pure SLD-builder module converts the existing geometry-keyed style JSON into SLD 1.0.0. `GeoServerService` gains raw-REST style upsert + default-style assignment (same pattern as `_recalculate_bbox`). New endpoints in `layers.py` validate the layer is GeoServer-published, push the SLD, and mirror editor state into `Layer.file_metadata["style"]` with a `mode` discriminator. GeoServer is rendering truth; DB is editor state. Design record: `docs/adr/0001-per-layer-sld-no-shared-styles.md`, glossary: `CONTEXT.md`.

**Tech Stack:** FastAPI, SQLModel, requests (sync, wrapped in `asyncio.to_thread`), defusedxml, pytest.

## Global Constraints

- **NO git write operations** (`git add/commit/push/...`) — forbidden by project CLAUDE.md. Leave changes in the working tree; the user commits at monorepo root.
- Python 3.12; run server with `uvicorn app.main:app --reload`.
- GeoServer config comes from `app/core/config.py` settings: `GEOSERVER_URL`, `GEOSERVER_USER`, `GEOSERVER_PASSWORD`, `GEOSERVER_WORKSPACE`.
- Style name convention: `layer_{layer_id}` inside `settings.GEOSERVER_WORKSPACE`.
- Simple-style JSON schema (identical to local `VectorTiler` style): geometry keys `Polygon` / `LineString` / `Point`, props `fillColor`, `strokeColor`, `strokeWidth`, `opacity`, `pointRadius`.
- No cleanup of GeoServer styles on layer delete (accepted debt per ADR 0001).
- Docs live in `docs/` (project rule).
- Project has no test runner configured; install pytest locally (`pip install pytest`) — do NOT add pytest to `requirements.txt`.

---

### Task 1: SLD builder module

**Files:**
- Modify: `requirements.txt` (add `defusedxml`)
- Create: `app/infrastructure/services/sld_builder.py`
- Test: `tests/test_sld_builder.py` (create `tests/` dir; no `__init__.py` needed)

**Interfaces:**
- Consumes: nothing (pure function).
- Produces: `build_sld(style: dict, style_name: str) -> str` — returns SLD 1.0.0 XML string; raises `ValueError` on unknown geometry keys. Constant `ALLOWED_GEOMETRIES = {"Polygon", "LineString", "Point"}`. Later tasks import both from `app.infrastructure.services.sld_builder`.

- [ ] **Step 1: Add dependency**

Append to `requirements.txt`:

```
defusedxml==0.7.1
```

Run: `pip install defusedxml==0.7.1 pytest`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_sld_builder.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_sld_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.infrastructure.services.sld_builder'`

- [ ] **Step 4: Implement the builder**

Create `app/infrastructure/services/sld_builder.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_sld_builder.py -v`
Expected: 7 PASSED

---

### Task 2: GeoServerService style methods

**Files:**
- Modify: `app/infrastructure/services/geoserver_service.py`
- Test: `tests/test_geoserver_style.py`

**Interfaces:**
- Consumes: existing `GeoServerService.__init__` (`self._base_url`, `self._auth`, `self.workspace`), module-level `requests` import (already present).
- Produces (imported by Task 3):
  - `class GeoServerStyleError(Exception)` with attributes `http_status: int`, `detail: str`.
  - `GeoServerService.upsert_style(style_name: str, sld_body: str) -> None` — create-or-update workspace style; raises `GeoServerStyleError(422, ...)` when GeoServer rejects the SLD (HTTP 400), `GeoServerStyleError(502, ...)` on other failures/unreachable.
  - `GeoServerService.set_default_style(layer_name: str, style_name: str) -> None` — `layer_name` is qualified (`workspace:store`); raises `GeoServerStyleError(502, ...)` on failure.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_geoserver_style.py`:

```python
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
    calls = []
    monkeypatch.setattr(gs_mod.requests, "put",
                        lambda url, **kw: calls.append(("PUT", url)) or FakeResponse(200))
    svc.upsert_style("layer_abc", "<sld/>")
    assert calls == [("PUT", "http://gs:8080/geoserver/rest/workspaces/tileserver/styles/layer_abc")]


def test_upsert_style_creates_on_404(svc, monkeypatch):
    calls = []
    monkeypatch.setattr(gs_mod.requests, "put",
                        lambda url, **kw: calls.append(("PUT", url)) or FakeResponse(404))
    monkeypatch.setattr(gs_mod.requests, "post",
                        lambda url, **kw: calls.append(("POST", url)) or FakeResponse(201))
    svc.upsert_style("layer_abc", "<sld/>")
    assert calls[0][0] == "PUT"
    assert calls[1] == ("POST", "http://gs:8080/geoserver/rest/workspaces/tileserver/styles?name=layer_abc")


def test_upsert_style_400_maps_to_422(svc, monkeypatch):
    monkeypatch.setattr(gs_mod.requests, "put",
                        lambda url, **kw: FakeResponse(400, "Invalid SLD"))
    with pytest.raises(GeoServerStyleError) as exc:
        svc.upsert_style("layer_abc", "<bad/>")
    assert exc.value.http_status == 422
    assert "Invalid SLD" in exc.value.detail


def test_upsert_style_connection_error_maps_to_502(svc, monkeypatch):
    def boom(url, **kw):
        raise gs_mod.requests.ConnectionError("refused")
    monkeypatch.setattr(gs_mod.requests, "put", boom)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_geoserver_style.py -v`
Expected: FAIL — `ImportError: cannot import name 'GeoServerStyleError'`

- [ ] **Step 3: Implement the methods**

In `app/infrastructure/services/geoserver_service.py`, add after the imports (below `logger = logging.getLogger(__name__)`):

```python
class GeoServerStyleError(Exception):
    """Style operation failed. http_status is the HTTP status our API should return."""

    def __init__(self, http_status: int, detail: str):
        super().__init__(detail)
        self.http_status = http_status
        self.detail = detail
```

Add these methods to `GeoServerService` (after `publish_shp`):

```python
    def upsert_style(self, style_name: str, sld_body: str) -> None:
        """Create or update a workspace SLD style (rendering truth lives in GeoServer)."""
        headers = {"Content-Type": "application/vnd.ogc.sld+xml"}
        style_url = f"{self._base_url}/rest/workspaces/{self.workspace}/styles/{style_name}"
        try:
            resp = requests.put(
                style_url, data=sld_body.encode("utf-8"),
                headers=headers, auth=self._auth, timeout=30,
            )
            if resp.status_code == 404:
                resp = requests.post(
                    f"{self._base_url}/rest/workspaces/{self.workspace}/styles?name={style_name}",
                    data=sld_body.encode("utf-8"),
                    headers=headers, auth=self._auth, timeout=30,
                )
            if resp.status_code in (200, 201):
                return
            if resp.status_code == 400:
                raise GeoServerStyleError(422, f"GeoServer rejected SLD: {resp.text[:500]}")
            raise GeoServerStyleError(
                502, f"GeoServer style upload failed ({resp.status_code}): {resp.text[:300]}"
            )
        except requests.RequestException as exc:
            raise GeoServerStyleError(502, f"GeoServer unreachable: {exc}")

    def set_default_style(self, layer_name: str, style_name: str) -> None:
        """Set a workspace style as the layer's default. layer_name is 'workspace:store'."""
        url = f"{self._base_url}/rest/layers/{layer_name}.json"
        payload = {"layer": {"defaultStyle": {"name": f"{self.workspace}:{style_name}"}}}
        try:
            resp = requests.put(url, json=payload, auth=self._auth, timeout=30)
            if resp.status_code not in (200, 201):
                raise GeoServerStyleError(
                    502, f"Failed to set default style ({resp.status_code}): {resp.text[:300]}"
                )
        except requests.RequestException as exc:
            raise GeoServerStyleError(502, f"GeoServer unreachable: {exc}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_geoserver_style.py tests/test_sld_builder.py -v`
Expected: 13 PASSED

---

### Task 3: Schemas + PUT/GET style endpoints

**Files:**
- Modify: `app/domain/schemas.py` (after `PatchLayerRequest`, around line 94)
- Modify: `app/api/v1/endpoints/layers.py` (imports at top; new routes after `patch_layer`, i.e. after line 227)

**Interfaces:**
- Consumes: `build_sld`, `ALLOWED_GEOMETRIES` (Task 1); `GeoServerService.upsert_style` / `.set_default_style`, `GeoServerStyleError` (Task 2); existing `LayerRepository.update` (merges `file_metadata` top-level keys, so passing `{"style": ...}` preserves `geoserver` key), existing `LayerResponse`, `settings`.
- Produces: `PUT /api/v1/layers/{layer_id}/style` → `LayerResponse`; `GET /api/v1/layers/{layer_id}/style` → `LayerStyleResponse`. Stored editor state: `file_metadata["style"] = {"mode": "simple", "style": {...}}` or `{"mode": "sld", "sld_body": "..."}`.

- [ ] **Step 1: Add schemas**

In `app/domain/schemas.py`, add `Literal` to the existing `typing` import, then after `PatchLayerRequest`:

```python
class LayerStyleRequest(BaseModel):
    mode: Literal["simple", "sld"]
    style: Optional[dict] = None      # required when mode=simple; geometry-keyed JSON
    sld_body: Optional[str] = None    # required when mode=sld; raw SLD XML


class LayerStyleResponse(BaseModel):
    layer_id: str
    style_name: str
    style: Optional[dict] = None      # stored editor state incl. mode, None if never styled
```

- [ ] **Step 2: Add endpoints**

In `app/api/v1/endpoints/layers.py`, extend imports:

```python
from defusedxml.ElementTree import fromstring as safe_fromstring, ParseError as SafeParseError
from app.domain.schemas import LayerStyleRequest, LayerStyleResponse  # add to existing schemas import
from app.infrastructure.services.geoserver_service import GeoServerService, GeoServerStyleError
from app.infrastructure.services.sld_builder import build_sld, ALLOWED_GEOMETRIES
```

(`settings` and `asyncio` are already imported in this file — verify; if `settings` is missing add `from app.core.config import settings`.)

Add after `patch_layer` (line ~227):

```python
def _require_geoserver_layer(layer) -> dict:
    """Return geoserver metadata or raise 422 for non-published layers."""
    gs_meta = (layer.file_metadata or {}).get("geoserver")
    if layer.layer_type != "wms" or not gs_meta:
        raise HTTPException(
            status_code=422,
            detail="Style editing is only available for WMS layers published to GeoServer",
        )
    return gs_meta


@router.get("/{layer_id}/style", response_model=LayerStyleResponse)
async def get_layer_style(
    layer_id: str,
    repo: LayerRepository = Depends(_get_layer_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    _require_geoserver_layer(layer)
    return LayerStyleResponse(
        layer_id=layer_id,
        style_name=f"layer_{layer_id}",
        style=(layer.file_metadata or {}).get("style"),
    )


@router.put("/{layer_id}/style", response_model=LayerResponse)
async def put_layer_style(
    layer_id: str,
    req: LayerStyleRequest,
    repo: LayerRepository = Depends(_get_layer_repo),
    session_repo: UploadSessionRepository = Depends(_get_session_repo),
):
    layer = await repo.get_by_id(layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' not found.")
    gs_meta = _require_geoserver_layer(layer)

    style_name = f"layer_{layer_id}"

    if req.mode == "simple":
        if not req.style:
            raise HTTPException(status_code=422, detail="'style' is required when mode=simple")
        unknown = set(req.style) - ALLOWED_GEOMETRIES
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown geometry keys: {sorted(unknown)}. Allowed: {sorted(ALLOWED_GEOMETRIES)}",
            )
        sld_body = build_sld(req.style, style_name)
        stored_style = {"mode": "simple", "style": req.style}
    else:  # mode == "sld"
        if not req.sld_body:
            raise HTTPException(status_code=422, detail="'sld_body' is required when mode=sld")
        try:
            safe_fromstring(req.sld_body.encode("utf-8"))
        except (SafeParseError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid SLD XML: {exc}")
        sld_body = req.sld_body
        stored_style = {"mode": "sld", "sld_body": req.sld_body}

    svc = GeoServerService(
        url=settings.GEOSERVER_URL,
        username=settings.GEOSERVER_USER,
        password=settings.GEOSERVER_PASSWORD,
        workspace=settings.GEOSERVER_WORKSPACE,
    )
    try:
        await asyncio.to_thread(svc.upsert_style, style_name, sld_body)
        await asyncio.to_thread(svc.set_default_style, gs_meta["layer_name"], style_name)
    except GeoServerStyleError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.detail)

    updated = await repo.update(layer_id, file_metadata={"style": stored_style})

    status = "done"
    if updated.upload_session_id:
        upload_session = await session_repo.get_by_id(updated.upload_session_id)
        if upload_session:
            status = upload_session.status

    return LayerResponse(
        id=updated.id,
        upload_session_id=updated.upload_session_id,
        code=updated.code,
        layer_type=updated.layer_type,
        filename=updated.filename,
        file_type=updated.file_type,
        tile_url_template=updated.tile_url_template,
        status=status,
        created_at=updated.created_at,
        bbox=[updated.bbox_west, updated.bbox_south, updated.bbox_east, updated.bbox_north]
        if all([updated.bbox_west, updated.bbox_south, updated.bbox_east, updated.bbox_north])
        else None,
        file_metadata=updated.file_metadata,
        abstract=updated.abstract,
        topic_category=updated.topic_category,
        language=updated.language,
    )
```

Route-ordering note: FastAPI matches `/{layer_id}/style` before generic `/{layer_id}` only for the GET because paths differ; no conflict — `GET /{layer_id}/style` and `GET /{layer_id}` are distinct paths. Placement after `patch_layer` is fine.

- [ ] **Step 3: Verify app imports cleanly and routes registered**

Run: `python -c "from app.main import app; print([r.path for r in app.routes if 'style' in r.path])"`
Expected: `['/api/v1/layers/{layer_id}/style', '/api/v1/layers/{layer_id}/style']`

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: all PASS

---

### Task 4: End-to-end verification + docs

**Files:**
- Create: `docs/STYLE_EDITING.md`
- Modify: `docs/API.md` (append endpoint entries to the layers section)

**Interfaces:**
- Consumes: everything above; running GeoServer + FastAPI dev server.

- [ ] **Step 1: Manual end-to-end check (requires GeoServer running & a published layer)**

```bash
uvicorn app.main:app --reload &
# pick a layer published to GeoServer (layer_type=wms, file_metadata.geoserver present)
LAYER_ID=<published-layer-id>

# 1. GET before styling → style: null
curl -s http://localhost:8000/api/v1/layers/$LAYER_ID/style

# 2. PUT simple style
curl -s -X PUT http://localhost:8000/api/v1/layers/$LAYER_ID/style \
  -H 'Content-Type: application/json' \
  -d '{"mode":"simple","style":{"Polygon":{"fillColor":"#ff0000","strokeColor":"#000000","strokeWidth":2,"opacity":0.6}}}'

# 3. Verify in GeoServer: style exists & is default
curl -s -u admin:geoserver \
  "http://localhost:8080/geoserver/rest/workspaces/tileserver/styles/layer_$LAYER_ID.sld"
curl -s -u admin:geoserver \
  "http://localhost:8080/geoserver/rest/layers/tileserver:<store_name>.json" | grep defaultStyle -A3

# 4. GetMap renders red polygons (open in browser using layer's wms_url)

# 5. PUT invalid raw SLD → expect 422
curl -s -X PUT http://localhost:8000/api/v1/layers/$LAYER_ID/style \
  -H 'Content-Type: application/json' -d '{"mode":"sld","sld_body":"<not-closed"}'

# 6. PUT style on an external WMS layer → expect 422
# 7. Stop GeoServer, PUT again → expect 502
```

Expected: steps as annotated; `file_metadata.style` round-trips via GET.

- [ ] **Step 2: Write docs**

Create `docs/STYLE_EDITING.md` documenting: scope (GeoServer-published WMS only), the two modes with example request bodies (copy the curl bodies from Step 1), style naming `layer_{layer_id}`, editor-state vs rendering-truth rule, error codes (404/422/502), and pointer to `docs/adr/0001-per-layer-sld-no-shared-styles.md`. Append both endpoints to `docs/API.md` with one-line descriptions and example bodies.

- [ ] **Step 3: Final full check**

Run: `python -m pytest tests/ -v && python -c "from app.main import app"`
Expected: all tests PASS, import clean.

**Do not commit** — leave working tree for the user (project git rules).
