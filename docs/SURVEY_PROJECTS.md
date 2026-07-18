# Survey Projects

Dynamic-form spatial data capture. A **Project** defines a form and a geometry type; users submit **Features** (spatial records) against that form; **Attachments** are files uploaded through `file`-type form fields. A Project can be **published** to appear on the map as a live Layer, and **exported** to GeoJSON/CSV/Shapefile.

Terminology below matches `CONTEXT.md` exactly — read that file first if a term here is unclear.

Source of truth: `app/api/v1/endpoints/projects.py`, `app/domain/form_validation.py`, `app/domain/geometry_validation.py`, `app/infrastructure/services/project_export_service.py`, `app/domain/models.py`, `app/core/config.py`.

## Concepts

| Term | Meaning |
|---|---|
| **Project** | A survey container. Owns exactly one Form Schema and many Features. Declares one Geometry Type (`point`\|`line`\|`polygon`) at creation — every Feature must match it. Not itself renderable; may be published as a Layer. |
| **Form Schema** | The dynamic attribute form owned by a Project — an ordered list of Fields. Mutable and unversioned: editing it never destroys existing Feature attribute values (see "Schema mutability" below). |
| **Feature** (survey sense) | One spatial record in a Project: a geometry matching the Project's Geometry Type, plus attributes conforming to the Form Schema. Optional client-supplied `created_by` (the service does not authenticate surveyors). |
| **Attachment** | A file uploaded through a `file` Field. Owned by the Project, referenced by id from a Feature's attribute value. Deleting a Feature deletes its referenced Attachments; deleting a Project deletes all of them. Served publicly at `/attachments/...`, like tiles. |
| **Publishing** | Creating a Layer backed by the Project's *live* Feature data (not a snapshot) — see [Publish semantics](#publish-semantics-adr-0003). |

## Field types

`app/domain/form_validation.py:FIELD_TYPES`. A Form Schema is a JSON list of field objects:

```json
[
  {"name": "kondisi", "label": "Kondisi", "type": "select", "required": true, "options": ["baik", "rusak", "sedang"]},
  {"name": "catatan", "label": "Catatan", "type": "textarea", "required": false},
  {"name": "jumlah_lubang", "label": "Jumlah Lubang", "type": "number", "required": false, "min": 0, "max": 100},
  {"name": "tanggal_survei", "label": "Tanggal Survei", "type": "date", "required": true},
  {"name": "aktif", "label": "Aktif", "type": "checkbox", "required": false},
  {"name": "fasilitas", "label": "Fasilitas", "type": "multiselect", "required": false, "options": ["pju", "drainase", "trotoar"]},
  {"name": "foto", "label": "Foto", "type": "file", "required": false, "extensions": ["jpg", "jpeg", "png"]}
]
```

`name` is the attribute key (must match `^[a-zA-Z_][a-zA-Z0-9_]*$`, unique in the schema); `label` is required display text.

| Type | Stored attribute value | Extra schema keys | Validation |
|---|---|---|---|
| `text` | string | — | must be a string |
| `textarea` | string | — | must be a string |
| `number` | int/float | `min`, `max` (optional) | must be numeric (not bool); bounds enforced if set |
| `select` | string | `options` (required, non-empty list) | value must be one of `options` |
| `multiselect` | list of strings | `options` (required, non-empty list) | value must be a list, all items in `options` |
| `date` | ISO string `YYYY-MM-DD` | — | must match the pattern and parse as a valid calendar date |
| `checkbox` | bool | — | must be a bool |
| `file` | string (Attachment id) | `extensions` (optional, overrides the default allow-list for uploads against this field) | must be a string (the id returned by the attachment-upload endpoint) |

A field with `"required": true` must have a non-empty value (`None`, `""`, `[]` all count as empty) on Feature create; on update, only fields present in the merged attribute set are validated (see `validate_attributes(..., enforce_required=True)`).

### Schema mutability

The schema is mutable and unversioned (`PUT /projects/{id}/schema` replaces it wholesale). Existing Feature attribute values are **never destroyed** by a schema edit:
- Removing a Field: existing values for it stay stored on Features but are no longer rendered/validated.
- Adding a required Field: enforced only on subsequent create/edit, not retroactively on existing Features.
- Removing a `select`/`multiselect` option: existing stored values referencing it stay readable, but become invalid on the next edit of that Feature (re-validation will reject them).

## Endpoints

Base path: `/api/v1/projects`. All bodies are JSON except attachment upload (`multipart/form-data`).

### Project CRUD

**`POST /projects`** — create a project. Returns **200** (not 201 — a documented quirk of this feature; all `POST` project/feature endpoints return 200).

```bash
curl -X POST http://localhost:8080/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"Survey Jalan","geometry_type":"point","form_schema":[{"name":"kondisi","label":"Kondisi","type":"select","required":true,"options":["baik","rusak"]}]}'
```
```json
{"id":"3e509276-c5b5-4f4d-ab2e-6a85f8cdabd1","name":"Survey Jalan","description":null,"geometry_type":"point","form_schema":[{"name":"kondisi","label":"Kondisi","type":"select","required":true,"options":["baik","rusak"]}],"layer_id":null,"is_published":false,"feature_count":0,"created_at":"2026-07-18T01:10:40.256894Z","updated_at":"2026-07-18T01:10:40.256925Z"}
```
`422` if `geometry_type` is not one of `point|line|polygon`, or if `form_schema` fails `validate_form_schema` (detail is a list of error strings).

**`GET /projects`** — list all projects (each with computed `feature_count`, `is_published` = `layer_id is not None`).

**`GET /projects/{project_id}`** — get one project. `404` if missing.

**`PATCH /projects/{project_id}`** — update `name`/`description` only (both optional, partial). `404` if missing.

**`PUT /projects/{project_id}/schema`** — replace `form_schema` wholesale. `404` if missing, `422` on schema validation failure.

**`DELETE /projects/{project_id}`** — **204**. Cascades: deletes all Features, all Attachments (rows + files, plus `rmtree`s `data/attachments/{project_id}/`), and if published, clears `layer_id` (FK-safe) then deletes the Layer row. `404` if missing.

### Feature CRUD

**`POST /projects/{project_id}/features`** — create a feature. Returns **200**.

```bash
curl -X POST http://localhost:8080/api/v1/projects/$PID/features \
  -H "Content-Type: application/json" \
  -d '{"geometry":{"type":"Point","coordinates":[106.8,-6.2]},"attributes":{"kondisi":"baik"},"created_by":"anjar"}'
```
```json
{"id":"7786db2f-c115-4f8b-8827-8543fbac0844","project_id":"3e509276-c5b5-4f4d-ab2e-6a85f8cdabd1","geometry":{"type":"Point","coordinates":[106.8,-6.2]},"attributes":{"kondisi":"baik"},"created_by":"anjar","created_at":"2026-07-18T01:10:40.519352Z","updated_at":"2026-07-18T01:10:40.519379Z"}
```
`422` on geometry/attribute validation failure, e.g.:
- Wrong geometry type: `{"detail":"geometry type must be 'Point' for this project, got 'LineString'"}`
- Missing required attribute: `{"detail":["kondisi: required"]}`

**`GET /projects/{project_id}/features`** / **`GET /projects/{project_id}/features/{feature_id}`** — list/get. No pagination (deliberate YAGNI deferral — fine at survey scale). `404` on missing project/feature (feature lookup is scoped: a feature id from a different project also 404s).

**`PATCH /projects/{project_id}/features/{feature_id}`** — partial update. `geometry` (if given) is fully replaced and re-validated; `attributes` (if given) is **merged** into existing attributes (`{**feature.attributes, **body.attributes}`) then the merged result is re-validated. `404`/`422` as above.

**`DELETE /projects/{project_id}/features/{feature_id}`** — **204**. Cascades: deletes only the Attachments referenced by this feature's `file`-type attribute values (not the whole project's attachments). `404` if missing.

### Attachments

**`POST /projects/{project_id}/attachments`** — `multipart/form-data`: `file` (required), `field_name` (optional — selects the field's `extensions` allow-list; falls back to `DEFAULT_ATTACHMENT_EXTENSIONS = {jpg, jpeg, png, gif, webp, pdf}` when omitted or the field has no `extensions`). Returns **200**.

```bash
curl -X POST http://localhost:8080/api/v1/projects/$PID/attachments \
  -F "file=@photo.jpg" -F "field_name=foto"
```
```json
{"id":"...","project_id":"...","filename":"photo.jpg","url":"/attachments/{project_id}/{attachment_id}_photo.jpg","content_type":"image/jpeg","size_bytes":12345}
```

Stored at `data/attachments/{project_id}/{attachment_id}_{original_filename}`, served statically at the returned `url`. The client is responsible for writing the returned `id` into the Feature's `file`-type attribute (upload and feature-create/update are two separate calls — there is no atomic combined endpoint).

Errors: `422` if the extension isn't in the allowed set (`{"detail":"extension .sh not allowed"}`); `413` if `file.size > ATTACHMENT_MAX_SIZE` (default 10 MB, `app/core/config.py: ATTACHMENT_MAX_SIZE`, env override); `404` if project missing.

### Live GeoJSON and export

**`GET /projects/{project_id}/features.geojson`** — builds a `FeatureCollection` from the database on every request (not cached, not a snapshot). This is the endpoint published Layers point at. `404` if missing.

**`GET /projects/{project_id}/export?format=geojson|csv|shp`** — downloadable export, always freshly flattened from current Features. `format` defaults to `geojson`. `422` if `format` is not one of the three; `422` for `shp` specifically **when there are zero features** (geopandas can't infer a schema from an empty feature list — documented quirk, not a bug). `404` if project missing.

```bash
curl -O -J "http://localhost:8080/api/v1/projects/$PID/export?format=csv"
curl -O -J "http://localhost:8080/api/v1/projects/$PID/export?format=shp"
```

#### Flattening rules (`project_export_service.flatten_attributes`)

Applied identically by `features.geojson`, and all three export formats:
- `multiselect` values (a list) are joined with `;` (e.g. `["pju","drainase"]` → `"pju;drainase"`).
- `file` values are rewritten to a full URL (`{base_url}/attachments/{attachment_id}`) when a `base_url` is supplied (features.geojson and CSV/SHP export pass one where relevant); otherwise the raw Attachment id passes through.
- All other types pass through unchanged.
- Missing attributes flatten to `null`.

**GeoJSON** (`build_feature_collection`) additionally injects `_id`, `_created_by`, `_created_at` (ISO string) into `properties`.

**CSV** (`export_csv`) columns: `id`, one column per Form Schema field (in schema order), `created_by`, `created_at`, `wkt` (WKT geometry), plus `longitude`/`latitude` **only when `geometry_type == "point"`**.

**SHP** (`export_shp_zip`) — zipped ESRI Shapefile (`.shp`/`.shx`/`.dbf`/`.prj`/`.cpg`), CRS `EPSG:4326`. DBF column names are limited to 10 chars: `shp_safe_columns` truncates each field name to 10 chars and de-duplicates collisions by appending `_1`, `_2`, ... (shortening the base further to fit). A `created_by` column is always included alongside the schema fields.

### Publish / Unpublish

**`POST /projects/{project_id}/publish`** — **200**, creates a Layer of type `geojson` whose `tile_url_template` is the project's own `features.geojson` URL, with `is_active=True`, `is_visible=True`, `file_metadata = {"project_id": ..., "style": DEFAULT_STYLE}` (a preset blue simple style). `bbox_*` columns are computed from current Feature geometries via shapely `.bounds` (unset if there are zero features). `409` if already published (`project.layer_id is not None`).

```bash
curl -X POST http://localhost:8080/api/v1/projects/$PID/publish
```
```json
{"project_id":"...","layer_id":"...","geojson_url":"/api/v1/projects/.../features.geojson"}
```

**`DELETE /projects/{project_id}/publish`** — **204**. Clears `project.layer_id` first, then deletes the Layer row (FK-safe order — the reverse order would violate `projects_layer_id_fkey`). `409` if not currently published. Resilient to the Layer row already being gone (e.g. deleted independently): `LayerRepository.delete()` is a no-op-safe call that returns `False` rather than raising on a missing row, so unpublish still succeeds and clears the FK.

#### Publish semantics (ADR-0003)

See `docs/adr/0003-project-publish-is-live-projection-not-snapshot.md`. Key points:
- Publishing does **not** snapshot data — the created Layer is a *live projection*: every map render hits the database via `features.geojson`.
- "Published" is not a stored status column; it is derived from `project.layer_id is not None`.
- Unpublishing (or deleting the Layer directly) removes only the Layer — Features and Attachments are untouched.
- Deleting the Project removes everything: Features, Attachments, and (if published) the Layer.
- Escape hatch if a Project ever needs the existing tiling pipeline instead of live projection ("bake to tiles"): out of scope for this feature, deliberately deferred (YAGNI).

### Geometry storage (ADR-0002)

Feature geometry is stored as a GeoJSON object in a plain JSON column (`features.geometry`), not PostGIS — see `docs/adr/0002-survey-geometry-geojson-json-column-not-postgis.md`. This keeps the feature working across all three configured DB backends (PostgreSQL/MySQL/SQLite) and matches the codebase's existing JSON-column conventions (`bbox` as four float columns, `file_metadata` as JSON). No server-side spatial querying is provided; all spatial reads happen in Python (`shapely`/`geopandas`) after loading rows.

`app/domain/geometry_validation.py:validate_geometry` enforces: GeoJSON `type` must match the Project's `geometry_type` (`point`→`Point`, `line`→`LineString`, `polygon`→`Polygon`; no Multi* types), all coordinates must be in WGS84 range (`-180..180` lon, `-90..90` lat), and the geometry must parse via shapely and be non-empty/valid (rejects self-intersecting polygons, etc).

## Known quirks (documented, not bugs)

- `POST /projects`, `POST /projects/{id}/features`, `POST /projects/{id}/attachments` all return **200**, not 201 — consistent with the rest of this codebase's endpoints (`tiles.py`/`upload.py` also return 200 on create), not a REST purity violation to "fix".
- `POST /projects/{id}/publish` returns **409** if already published; `DELETE .../publish` returns **409** if not published. Both are conflicts-with-current-state, not 404s — the project exists, its publish state just doesn't match the request.
- `DELETE /projects/{id}/publish` is resilient to the Layer row being independently deleted already (no 500, no orphan check) — see [Publish semantics](#publish-semantics-adr-0003).
- `GET /projects/{id}/export?format=shp` returns **422** when the project has zero features (geopandas cannot construct a `GeoDataFrame`/infer a schema without at least one geometry). `geojson`/`csv` export handle the empty case fine (empty `FeatureCollection` / header-only CSV).
- No pagination on `GET /projects/{id}/features` — acceptable at survey scale (hundreds–thousands of features per Project), deliberately deferred.
- No authentication/authorization anywhere in this feature — `created_by` is a free-text client-supplied string, not a verified identity.
