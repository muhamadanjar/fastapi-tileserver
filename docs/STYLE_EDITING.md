# Style Editing (per-layer GeoServer SLD)

## Scope

Style editing applies **only to WMS layers published to GeoServer by this service** (the SHP → GeoServer publish flow, `POST /uploads/{upload_id}/geoserver`). A layer qualifies when both are true:

- `layer_type == "wms"`
- `file_metadata.geoserver` is populated (set by the publish flow)

External/remote WMS layers (registered by URL, pointing at a server we don't control) and any non-WMS layer type (local tile/mvt, esri_*, wmts, wfs, ...) are **not** in scope — both endpoints reject them with `422`. See `docs/adr/0001-per-layer-sld-no-shared-styles.md` for why styling is per-layer only, with no shared/general GeoServer styles.

Local vector tiling (the `Point`/`LineString`/`Polygon` style JSON used by `VectorTiler`) is a separate, unrelated styling path — it renders our own PNG tiles, not GeoServer. This document covers GeoServer-published WMS styling only.

## Endpoints

```
GET  /api/v1/layers/{layer_id}/style
PUT  /api/v1/layers/{layer_id}/style
```

## Style naming

Every GeoServer-published layer owns exactly one workspace SLD style, named:

```
layer_{layer_id}
```

`PUT` creates this style in GeoServer if it doesn't exist yet, or updates its content in place if it does, and always (re)sets it as the layer's **default style** — so existing WMS `GetMap`/`GetLegendGraphic` URLs keep working unchanged, no client-side style parameter required.

## Two modes

The request body is discriminated by `mode`.

### `simple` — geometry-keyed JSON

Same vocabulary used by local vector tiling (`Polygon` / `LineString` / `Point` keys, each with `fillColor`, `strokeColor`, `strokeWidth`, `opacity`, and `pointRadius` for points). The backend builds SLD 1.0.0 XML from this JSON (`app/infrastructure/services/sld_builder.py::build_sld`).

```bash
curl -X PUT http://localhost:8000/api/v1/layers/$LAYER_ID/style \
  -H 'Content-Type: application/json' \
  -d '{"mode":"simple","style":{"Polygon":{"fillColor":"#ff0000","strokeColor":"#000000","strokeWidth":2,"opacity":0.6}}}'
```

Unknown geometry keys (anything outside `Polygon`/`LineString`/`Point`) → `422`.

### `sld` — raw Custom SLD

For advanced users supplying hand-authored SLD XML directly. The body is parsed with a safe XML parser before being sent to GeoServer.

```bash
curl -X PUT http://localhost:8000/api/v1/layers/$LAYER_ID/style \
  -H 'Content-Type: application/json' \
  -d '{"mode":"sld","sld_body":"<sld:StyledLayerDescriptor xmlns:sld=\"http://www.opengis.net/sld\" version=\"1.0.0\"><sld:NamedLayer>...</sld:NamedLayer></sld:StyledLayerDescriptor>"}'
```

Malformed XML (e.g. unclosed tags) is rejected locally with `422` before ever reaching GeoServer.

The two modes are mutually exclusive per layer at any moment — switching from `sld` back to `simple` (or vice versa) discards whatever the other mode held; there is no merge.

## Editor-state vs rendering-truth rule

**GeoServer is the rendering truth.** The SLD actually installed as the layer's default style — the thing `GetMap` uses — lives in GeoServer, at `workspaces/{workspace}/styles/layer_{layer_id}.sld`.

**The database (`layers.file_metadata.style`) is editor state only** — what the style editor UI should pre-fill the next time it opens for that layer. It mirrors the last successful `PUT`; it never overrides or feeds back into GeoServer on its own. `GET /layers/{layer_id}/style` returns this editor state (`style: null` if the layer has never been styled through this API, even if a default GeoServer style already exists on the layer from the publish step).

Because of this: if GeoServer's style is changed out-of-band (directly via the GeoServer admin UI/REST API, bypassing this service), the DB's editor state will silently drift from what actually renders until the next `PUT` through this API.

## Error codes

| Status | When |
|---|---|
| `404 Not Found` | Layer does not exist |
| `422 Unprocessable Entity` | Layer is not a GeoServer-published WMS layer (external WMS or other type); `style`/`sld_body` missing for the given `mode`; unknown geometry key in `simple` mode; malformed SLD XML in `sld` mode; or GeoServer itself rejects the SLD content as invalid |
| `502 Bad Gateway` | GeoServer is unreachable, or returns an unexpected/non-2xx, non-400 error while creating/updating the style or setting it as default |

## Verification notes (Task 4)

End-to-end verified against a live GeoServer 2.27.4 instance and a real SHP layer published through this service:

- `GET` before styling returns `style: null`.
- `PUT` with `mode=simple` creates the `layer_{layer_id}` style in GeoServer, sets it as the layer's default style, and `GetMap` renders the requested fill/stroke.
- `GET` after `PUT` round-trips the exact editor-state JSON that was submitted.
- A second `PUT` (update path, style already exists) correctly overwrites the existing style content.
- `PUT` with malformed `sld_body` (`"<not-closed"`) returns `422` before contacting GeoServer.
- `GET`/`PUT` against a non-GeoServer-published layer (e.g. `esri_mapserver`) return `422`.
- `GET` against a nonexistent layer id returns `404`.
- Unreachable-GeoServer path returns `502` (verified at the `GeoServerService.upsert_style` level against an unreachable host, to avoid disrupting the shared GeoServer instance used by other services).

During this verification a bug was found and fixed in `GeoServerService.upsert_style` (`app/infrastructure/services/geoserver_service.py`): the original create-vs-update logic assumed GeoServer returns `404` on `PUT` to a style that doesn't exist yet, then falls back to `POST` to create it. On GeoServer 2.27.4 this assumption is false — `PUT` to a missing style returns `400 Invalid style:null` instead, which was being (mis)treated as "GeoServer rejected the SLD" (`422`), permanently blocking the first `PUT` for any layer. The fix checks existence explicitly via `GET {style}.json` first, then issues `PUT` (update) or `POST` (create) accordingly. Corresponding unit tests in `tests/test_geoserver_style.py` were updated to mock the new `GET` existence check.

See also: `docs/adr/0001-per-layer-sld-no-shared-styles.md` for the design rationale, and `CONTEXT.md` for glossary terms (Layer Style, Simple Style, Custom SLD, Rendering Truth vs Editor State).
