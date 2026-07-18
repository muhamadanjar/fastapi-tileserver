# Survey Projects (Dynamic-Form Spatial Data Capture) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Project entity that owns a dynamic Form Schema and captures spatial Features (point/line/polygon + form attributes), publishable as a live `geojson` Layer, exportable as GeoJSON/CSV/SHP.

**Architecture:** New domain trio `Project` / `Feature` / `Attachment` alongside existing `Layer`/`UploadSession`. Geometry stored as GeoJSON in JSON columns (ADR-0002). Publish creates a Layer whose URL points at a live FeatureCollection endpoint (ADR-0003). Pure validation logic lives in `app/domain/` (TDD), orchestration in `app/usecases/`, HTTP in `app/api/v1/endpoints/projects.py`.

**Tech Stack:** FastAPI, SQLModel, Alembic, shapely 2.x, geopandas 1.x (already installed), pytest.

## Global Constraints

- **NO git write operations** (project rule). No `git add/commit`. At each "Checkpoint" step, stop and tell the user what is ready to commit.
- Domain language must match `CONTEXT.md` (Project, Form Schema, Feature, Attachment, Publishing).
- Geometry: GeoJSON `Point`/`LineString`/`Polygon` only, WGS84, reject `Multi*` (v1).
- Field types v1 exactly: `text`, `textarea`, `number`, `select`, `multiselect`, `date`, `checkbox`, `file`.
- Schema mutable/unversioned; schema edits never destroy stored Feature attribute values.
- Run tests with `python -m pytest` (NOT `rtk pytest` — known sys.path failure).
- All new docs go in `docs/`.

---

### Task 1: Domain models + migration

**Files:**
- Modify: `app/domain/models.py`
- Create: `alembic/versions/0005_add_projects_features_attachments.py`

**Interfaces:**
- Produces: `GeometryType` enum; SQLModel tables `Project`, `Feature`, `Attachment` importable from `app.domain.models`.

- [ ] **Step 1: Add enum + models** to `app/domain/models.py` (append after `Layer`):

```python
class GeometryType(str, enum.Enum):
    point = "point"
    line = "line"
    polygon = "polygon"


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(primary_key=True)
    name: str
    description: Optional[str] = Field(default=None, sa_column=Column(Text()))
    geometry_type: str  # GeometryType value
    form_schema: list = Field(default_factory=list, sa_column=Column(JSON))
    layer_id: Optional[str] = Field(default=None, foreign_key="layers.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class Feature(SQLModel, table=True):
    __tablename__ = "features"

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    geometry: Dict[str, Any] = Field(sa_column=Column(JSON))
    attributes: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_by: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))


class Attachment(SQLModel, table=True):
    __tablename__ = "attachments"

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    feature_id: Optional[str] = Field(default=None, index=True)
    filename: str
    stored_path: str
    content_type: Optional[str] = Field(default=None)
    size_bytes: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True)))
```

Note: `Feature.geometry` uses `Dict[str, Any]` (already imported at top of file). `form_schema` is a JSON list of field dicts.

- [ ] **Step 2: Write migration** `alembic/versions/0005_add_projects_features_attachments.py` (copy header style from `0004_add_mbtiles_to_layers.py`; `down_revision = '0004_add_mbtiles_to_layers'` — open 0004 and copy its exact `revision` string as this file's `down_revision`):

```python
from alembic import op
import sqlalchemy as sa

revision = '0005_add_projects_features_attachments'
down_revision = '<exact revision id from 0004>'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'projects',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('geometry_type', sa.String(), nullable=False),
        sa.Column('form_schema', sa.JSON(), nullable=False),
        sa.Column('layer_id', sa.String(), sa.ForeignKey('layers.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'features',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id'), nullable=False, index=True),
        sa.Column('geometry', sa.JSON(), nullable=False),
        sa.Column('attributes', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'attachments',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id'), nullable=False, index=True),
        sa.Column('feature_id', sa.String(), nullable=True, index=True),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('stored_path', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('attachments')
    op.drop_table('features')
    op.drop_table('projects')
```

- [ ] **Step 3: Verify migration applies**

Run: `alembic upgrade head && alembic current`
Expected: current = `0005_add_projects_features_attachments`. Then `python -c "from app.domain.models import Project, Feature, Attachment, GeometryType; print('ok')"` → `ok`.

- [ ] **Step 4: Checkpoint** — tell user Task 1 ready (models + migration).

---

### Task 2: Form Schema validation (pure domain, TDD)

**Files:**
- Create: `app/domain/form_validation.py`
- Test: `tests/test_form_validation.py`

**Interfaces:**
- Produces:
  - `FIELD_TYPES: frozenset[str]`
  - `class FormValidationError(ValueError)` — has `.errors: list[str]`
  - `validate_form_schema(schema: list) -> None` (raises `FormValidationError`)
  - `validate_attributes(schema: list, attributes: dict, *, enforce_required: bool = True) -> None` (raises `FormValidationError`)

Schema field shape (documented in module docstring):

```json
{"name": "kondisi", "label": "Kondisi Jalan", "type": "select", "required": true,
 "options": ["baik", "rusak"], "min": null, "max": null, "extensions": ["jpg", "png", "pdf"]}
```

`name` is the attribute key (snake_case identifier), `label` is display text. `options` required for `select`/`multiselect`; `min`/`max` optional for `number`; `extensions` optional for `file`.

- [ ] **Step 1: Write failing tests** `tests/test_form_validation.py`:

```python
import pytest
from app.domain.form_validation import (
    FormValidationError,
    validate_attributes,
    validate_form_schema,
)

SCHEMA = [
    {"name": "nama", "label": "Nama", "type": "text", "required": True},
    {"name": "catatan", "label": "Catatan", "type": "textarea", "required": False},
    {"name": "panjang", "label": "Panjang (m)", "type": "number", "required": False, "min": 0, "max": 1000},
    {"name": "kondisi", "label": "Kondisi", "type": "select", "required": True, "options": ["baik", "rusak"]},
    {"name": "fasilitas", "label": "Fasilitas", "type": "multiselect", "required": False, "options": ["pju", "drainase"]},
    {"name": "tanggal", "label": "Tanggal", "type": "date", "required": False},
    {"name": "aktif", "label": "Aktif", "type": "checkbox", "required": False},
    {"name": "foto", "label": "Foto", "type": "file", "required": False, "extensions": ["jpg", "png"]},
]


class TestValidateFormSchema:
    def test_valid_schema_passes(self):
        validate_form_schema(SCHEMA)

    def test_unknown_field_type_rejected(self):
        with pytest.raises(FormValidationError):
            validate_form_schema([{"name": "x", "label": "X", "type": "slider"}])

    def test_duplicate_names_rejected(self):
        with pytest.raises(FormValidationError):
            validate_form_schema([
                {"name": "x", "label": "A", "type": "text"},
                {"name": "x", "label": "B", "type": "text"},
            ])

    def test_select_without_options_rejected(self):
        with pytest.raises(FormValidationError):
            validate_form_schema([{"name": "x", "label": "X", "type": "select"}])

    def test_invalid_name_identifier_rejected(self):
        with pytest.raises(FormValidationError):
            validate_form_schema([{"name": "1 bad name!", "label": "X", "type": "text"}])


class TestValidateAttributes:
    def test_valid_attributes_pass(self):
        validate_attributes(SCHEMA, {
            "nama": "Jl. Sudirman", "panjang": 250.5, "kondisi": "baik",
            "fasilitas": ["pju"], "tanggal": "2026-07-18", "aktif": True,
        })

    def test_missing_required_rejected(self):
        with pytest.raises(FormValidationError) as e:
            validate_attributes(SCHEMA, {"nama": "Jl. X"})
        assert any("kondisi" in msg for msg in e.value.errors)

    def test_required_not_enforced_when_disabled(self):
        validate_attributes(SCHEMA, {}, enforce_required=False)

    def test_select_value_not_in_options_rejected(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "hancur"})

    def test_number_out_of_range_rejected(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "panjang": -5})

    def test_number_wrong_type_rejected(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "panjang": "abc"})

    def test_multiselect_must_be_list_of_options(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "fasilitas": ["wifi"]})

    def test_bad_date_rejected(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "tanggal": "18-07-2026"})

    def test_checkbox_must_be_bool(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "aktif": "yes"})

    def test_unknown_attribute_keys_are_kept_silently(self):
        # Schema edits never destroy old values: stale keys are tolerated.
        validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "field_lama": "nilai"})
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_form_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: app.domain.form_validation`.

- [ ] **Step 3: Implement** `app/domain/form_validation.py`:

```python
"""Form Schema validation for survey Projects.

A Form Schema is an ordered list of field dicts:
    {"name": "kondisi", "label": "Kondisi", "type": "select", "required": true,
     "options": ["baik", "rusak"], "min": null, "max": null, "extensions": ["jpg"]}

`name` is the attribute key (identifier), `label` display text.
Unknown attribute keys on stored Features are tolerated (mutable, unversioned
schema — see CONTEXT.md "Form Schema").
"""
import re
from datetime import date

FIELD_TYPES = frozenset(
    {"text", "textarea", "number", "select", "multiselect", "date", "checkbox", "file"}
)
_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_OPTION_TYPES = {"select", "multiselect"}


class FormValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_form_schema(schema: list) -> None:
    errors: list[str] = []
    if not isinstance(schema, list):
        raise FormValidationError(["form_schema must be a list"])
    seen: set[str] = set()
    for i, field in enumerate(schema):
        if not isinstance(field, dict):
            errors.append(f"field #{i} must be an object")
            continue
        name = field.get("name")
        ftype = field.get("type")
        if not name or not isinstance(name, str) or not _NAME_RE.match(name):
            errors.append(f"field #{i}: invalid name {name!r}")
        elif name in seen:
            errors.append(f"duplicate field name {name!r}")
        else:
            seen.add(name)
        if not field.get("label"):
            errors.append(f"field {name!r}: label is required")
        if ftype not in FIELD_TYPES:
            errors.append(f"field {name!r}: unknown type {ftype!r}")
            continue
        if ftype in _OPTION_TYPES:
            options = field.get("options")
            if not isinstance(options, list) or not options:
                errors.append(f"field {name!r}: {ftype} requires non-empty options")
        if ftype == "number":
            for bound in ("min", "max"):
                v = field.get(bound)
                if v is not None and not isinstance(v, (int, float)):
                    errors.append(f"field {name!r}: {bound} must be a number")
    if errors:
        raise FormValidationError(errors)


def _check_value(field: dict, value, errors: list[str]) -> None:
    name, ftype = field["name"], field["type"]
    if ftype in ("text", "textarea"):
        if not isinstance(value, str):
            errors.append(f"{name}: must be a string")
    elif ftype == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{name}: must be a number")
            return
        lo, hi = field.get("min"), field.get("max")
        if lo is not None and value < lo:
            errors.append(f"{name}: below minimum {lo}")
        if hi is not None and value > hi:
            errors.append(f"{name}: above maximum {hi}")
    elif ftype == "select":
        if value not in field.get("options", []):
            errors.append(f"{name}: {value!r} not in options")
    elif ftype == "multiselect":
        options = field.get("options", [])
        if not isinstance(value, list) or any(v not in options for v in value):
            errors.append(f"{name}: must be a list of allowed options")
    elif ftype == "date":
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            errors.append(f"{name}: must be an ISO date (YYYY-MM-DD)")
    elif ftype == "checkbox":
        if not isinstance(value, bool):
            errors.append(f"{name}: must be a boolean")
    elif ftype == "file":
        if not isinstance(value, str):
            errors.append(f"{name}: must be an attachment reference string")


def validate_attributes(schema: list, attributes: dict, *, enforce_required: bool = True) -> None:
    if not isinstance(attributes, dict):
        raise FormValidationError(["attributes must be an object"])
    errors: list[str] = []
    for field in schema:
        name = field["name"]
        value = attributes.get(name)
        if value is None or value == "" or value == []:
            if enforce_required and field.get("required"):
                errors.append(f"{name}: required")
            continue
        _check_value(field, value, errors)
    if errors:
        raise FormValidationError(errors)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_form_validation.py -v`
Expected: all PASS.

- [ ] **Step 5: Checkpoint** — Task 2 ready.

---

### Task 3: Geometry validation (pure domain, TDD)

**Files:**
- Create: `app/domain/geometry_validation.py`
- Test: `tests/test_geometry_validation.py`

**Interfaces:**
- Produces:
  - `class GeometryValidationError(ValueError)`
  - `validate_geometry(geometry: dict, geometry_type: str) -> None` — `geometry_type` is a `GeometryType` value (`point`|`line`|`polygon`).
  - `GEOJSON_TYPE_FOR: dict[str, str]` = `{"point": "Point", "line": "LineString", "polygon": "Polygon"}`

- [ ] **Step 1: Write failing tests** `tests/test_geometry_validation.py`:

```python
import pytest
from app.domain.geometry_validation import GeometryValidationError, validate_geometry

POINT = {"type": "Point", "coordinates": [106.8, -6.2]}
LINE = {"type": "LineString", "coordinates": [[106.8, -6.2], [106.9, -6.25]]}
POLYGON = {"type": "Polygon", "coordinates": [[[106.8, -6.2], [106.9, -6.2], [106.9, -6.3], [106.8, -6.2]]]}


def test_valid_point():
    validate_geometry(POINT, "point")

def test_valid_line():
    validate_geometry(LINE, "line")

def test_valid_polygon():
    validate_geometry(POLYGON, "polygon")

def test_type_mismatch_rejected():
    with pytest.raises(GeometryValidationError):
        validate_geometry(POINT, "polygon")

def test_multi_geometry_rejected():
    multi = {"type": "MultiPoint", "coordinates": [[106.8, -6.2]]}
    with pytest.raises(GeometryValidationError):
        validate_geometry(multi, "point")

def test_out_of_range_coordinates_rejected():
    bad = {"type": "Point", "coordinates": [206.8, -96.2]}
    with pytest.raises(GeometryValidationError):
        validate_geometry(bad, "point")

def test_self_intersecting_polygon_rejected():
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]}
    with pytest.raises(GeometryValidationError):
        validate_geometry(bowtie, "polygon")

def test_garbage_geojson_rejected():
    with pytest.raises(GeometryValidationError):
        validate_geometry({"type": "Point"}, "point")
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_geometry_validation.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** `app/domain/geometry_validation.py`:

```python
"""GeoJSON geometry validation for survey Features (WGS84, simple geometries only)."""
from shapely.errors import GEOSException
from shapely.geometry import shape

GEOJSON_TYPE_FOR = {"point": "Point", "line": "LineString", "polygon": "Polygon"}


class GeometryValidationError(ValueError):
    pass


def _iter_positions(coords):
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        yield coords
    elif isinstance(coords, (list, tuple)):
        for c in coords:
            yield from _iter_positions(c)


def validate_geometry(geometry: dict, geometry_type: str) -> None:
    expected = GEOJSON_TYPE_FOR.get(geometry_type)
    if expected is None:
        raise GeometryValidationError(f"unknown project geometry_type {geometry_type!r}")
    if not isinstance(geometry, dict) or geometry.get("type") != expected:
        raise GeometryValidationError(
            f"geometry type must be {expected!r} for this project, got {geometry.get('type')!r}"
        )
    coords = geometry.get("coordinates")
    if coords is None:
        raise GeometryValidationError("geometry has no coordinates")
    for pos in _iter_positions(coords):
        if len(pos) < 2 or not (-180 <= pos[0] <= 180) or not (-90 <= pos[1] <= 90):
            raise GeometryValidationError(f"coordinate out of WGS84 range: {pos}")
    try:
        geom = shape(geometry)
    except (GEOSException, ValueError, TypeError) as exc:
        raise GeometryValidationError(f"invalid geometry: {exc}") from exc
    if geom.is_empty or not geom.is_valid:
        raise GeometryValidationError("geometry is empty or invalid (self-intersection?)")
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_geometry_validation.py -v`
Expected: all PASS. Also run full suite: `python -m pytest` → 13 old + new tests green.

- [ ] **Step 5: Checkpoint** — Task 3 ready.

---

### Task 4: Repositories + Pydantic schemas

**Files:**
- Modify: `app/infrastructure/db/repository.py` (append)
- Modify: `app/domain/schemas.py` (append)

**Interfaces:**
- Produces:
  - `ProjectRepository(session: AsyncSession)`: `create(Project)`, `get_by_id(str) -> Optional[Project]`, `list_all() -> list[Project]`, `update(project: Project) -> Project`, `delete(str) -> bool`
  - `FeatureRepository(session: AsyncSession)`: `create(Feature)`, `get_by_id(str) -> Optional[Feature]`, `list_by_project(project_id: str) -> list[Feature]`, `update(feature: Feature) -> Feature`, `delete(str) -> bool`, `delete_by_project(project_id: str) -> int`
  - `AttachmentRepository(session: AsyncSession)`: `create(Attachment)`, `get_by_id(str) -> Optional[Attachment]`, `list_by_project(project_id: str) -> list[Attachment]`, `delete(str) -> bool`
  - Pydantic: `ProjectCreate`, `ProjectUpdate`, `ProjectResponse`, `FormSchemaUpdate`, `FeatureCreate`, `FeatureUpdate`, `FeatureResponse`, `AttachmentResponse`, `PublishResponse`

- [ ] **Step 1: Append repositories** to `app/infrastructure/db/repository.py`, following the exact style of `UploadSessionRepository`/`LayerRepository` in the same file (async, `select()`, `session.commit()` + `refresh`). Import `Project, Feature, Attachment` in the existing models import line. Implementation pattern:

```python
class ProjectRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def get_by_id(self, project_id: str) -> Optional[Project]:
        result = await self.session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Project]:
        result = await self.session.execute(select(Project).order_by(Project.created_at.desc()))
        return list(result.scalars().all())

    async def update(self, project: Project) -> Project:
        project.updated_at = datetime.now(timezone.utc)
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def delete(self, project_id: str) -> bool:
        project = await self.get_by_id(project_id)
        if project is None:
            return False
        await self.session.delete(project)
        await self.session.commit()
        return True
```

`FeatureRepository` identical shape plus:

```python
    async def list_by_project(self, project_id: str) -> list[Feature]:
        result = await self.session.execute(
            select(Feature).where(Feature.project_id == project_id).order_by(Feature.created_at)
        )
        return list(result.scalars().all())

    async def delete_by_project(self, project_id: str) -> int:
        features = await self.list_by_project(project_id)
        for f in features:
            await self.session.delete(f)
        await self.session.commit()
        return len(features)
```

`AttachmentRepository` same shape (`create`, `get_by_id`, `list_by_project`, `delete`). Match existing import of `datetime`/`timezone` at top of file (add if missing).

- [ ] **Step 2: Append Pydantic schemas** to `app/domain/schemas.py` (match existing style in that file — check whether it uses `BaseModel`/`ConfigDict`):

```python
class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    geometry_type: str  # point | line | polygon
    form_schema: list = []


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class FormSchemaUpdate(BaseModel):
    form_schema: list


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    geometry_type: str
    form_schema: list
    layer_id: Optional[str] = None
    is_published: bool
    feature_count: int
    created_at: datetime
    updated_at: datetime


class FeatureCreate(BaseModel):
    geometry: dict
    attributes: dict = {}
    created_by: Optional[str] = None


class FeatureUpdate(BaseModel):
    geometry: Optional[dict] = None
    attributes: Optional[dict] = None


class FeatureResponse(BaseModel):
    id: str
    project_id: str
    geometry: dict
    attributes: dict
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AttachmentResponse(BaseModel):
    id: str
    project_id: str
    filename: str
    url: str
    content_type: Optional[str] = None
    size_bytes: int


class PublishResponse(BaseModel):
    project_id: str
    layer_id: str
    geojson_url: str
```

- [ ] **Step 3: Smoke check**

Run: `python -c "from app.infrastructure.db.repository import ProjectRepository, FeatureRepository, AttachmentRepository; from app.domain.schemas import ProjectCreate, FeatureResponse; print('ok')"`
Expected: `ok`. Then `python -m pytest` → all green.

- [ ] **Step 4: Checkpoint** — Task 4 ready.

---

### Task 5: Project + Feature CRUD endpoints

**Files:**
- Create: `app/api/v1/endpoints/projects.py`
- Modify: `app/api/v1/api.py`

**Interfaces:**
- Consumes: Tasks 2–4 (`validate_form_schema`, `validate_attributes`, `validate_geometry`, repositories, schemas).
- Produces: router `projects.router`; endpoints listed below. Later tasks (6–8) append to this same file.

Endpoints:
- `POST /api/v1/projects` → ProjectResponse (validates geometry_type + form_schema)
- `GET /api/v1/projects` → list[ProjectResponse]
- `GET /api/v1/projects/{project_id}` → ProjectResponse
- `PATCH /api/v1/projects/{project_id}` → ProjectResponse (name/description)
- `PUT /api/v1/projects/{project_id}/schema` → ProjectResponse (replaces form_schema; validate only the schema, never touch existing features)
- `DELETE /api/v1/projects/{project_id}` → 204 (cascade features + attachments + files + layer; full cascade wiring finished in Tasks 6 & 8 — here delete features + project + layer row if `layer_id` set)
- `POST /api/v1/projects/{project_id}/features` → FeatureResponse (validate geometry + attributes, `enforce_required=True`)
- `GET /api/v1/projects/{project_id}/features` → list[FeatureResponse]
- `GET /api/v1/projects/{project_id}/features/{feature_id}` → FeatureResponse
- `PATCH /api/v1/projects/{project_id}/features/{feature_id}` → FeatureResponse (merge attributes: `{**old, **new}`; re-validate merged with `enforce_required=True`; geometry re-validated if sent)
- `DELETE /api/v1/projects/{project_id}/features/{feature_id}` → 204

- [ ] **Step 1: Implement** `app/api/v1/endpoints/projects.py`:

```python
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.domain.form_validation import FormValidationError, validate_attributes, validate_form_schema
from app.domain.geometry_validation import GeometryValidationError, validate_geometry
from app.domain.models import Feature, GeometryType, Project
from app.domain.schemas import (
    FeatureCreate, FeatureResponse, FeatureUpdate, FormSchemaUpdate,
    ProjectCreate, ProjectResponse, ProjectUpdate,
)
from app.infrastructure.db.connection import get_async_session
from app.infrastructure.db.repository import FeatureRepository, ProjectRepository

router = APIRouter(prefix="/projects", tags=["projects"])


def get_project_repo(session=Depends(get_async_session)) -> ProjectRepository:
    return ProjectRepository(session)


def get_feature_repo(session=Depends(get_async_session)) -> FeatureRepository:
    return FeatureRepository(session)


async def _get_project_or_404(project_id: str, repo: ProjectRepository) -> Project:
    project = await repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _project_response(project: Project, feature_count: int) -> ProjectResponse:
    return ProjectResponse(
        id=project.id, name=project.name, description=project.description,
        geometry_type=project.geometry_type, form_schema=project.form_schema,
        layer_id=project.layer_id, is_published=project.layer_id is not None,
        feature_count=feature_count,
        created_at=project.created_at, updated_at=project.updated_at,
    )


@router.post("", response_model=ProjectResponse)
async def create_project(body: ProjectCreate, repo: ProjectRepository = Depends(get_project_repo)):
    if body.geometry_type not in {g.value for g in GeometryType}:
        raise HTTPException(status_code=422, detail=f"geometry_type must be one of: point, line, polygon")
    try:
        validate_form_schema(body.form_schema)
    except FormValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)
    project = Project(
        id=str(uuid.uuid4()), name=body.name, description=body.description,
        geometry_type=body.geometry_type, form_schema=body.form_schema,
    )
    await repo.create(project)
    return _project_response(project, 0)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    projects = await repo.list_all()
    out = []
    for p in projects:
        count = len(await feature_repo.list_by_project(p.id))
        out.append(_project_response(p, count))
    return out


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    count = len(await feature_repo.list_by_project(project_id))
    return _project_response(project, count)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str, body: ProjectUpdate,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    await repo.update(project)
    count = len(await feature_repo.list_by_project(project_id))
    return _project_response(project, count)


@router.put("/{project_id}/schema", response_model=ProjectResponse)
async def replace_schema(
    project_id: str, body: FormSchemaUpdate,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    try:
        validate_form_schema(body.form_schema)
    except FormValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)
    project.form_schema = body.form_schema
    await repo.update(project)
    count = len(await feature_repo.list_by_project(project_id))
    return _project_response(project, count)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    await feature_repo.delete_by_project(project_id)
    # NOTE: attachment file/row cleanup added in Task 6; layer cleanup in Task 8.
    await repo.delete(project_id)


def _feature_response(f: Feature) -> FeatureResponse:
    return FeatureResponse(
        id=f.id, project_id=f.project_id, geometry=f.geometry, attributes=f.attributes,
        created_by=f.created_by, created_at=f.created_at, updated_at=f.updated_at,
    )


@router.post("/{project_id}/features", response_model=FeatureResponse)
async def create_feature(
    project_id: str, body: FeatureCreate,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    try:
        validate_geometry(body.geometry, project.geometry_type)
        validate_attributes(project.form_schema, body.attributes)
    except (GeometryValidationError, FormValidationError) as exc:
        detail = getattr(exc, "errors", str(exc))
        raise HTTPException(status_code=422, detail=detail)
    feature = Feature(
        id=str(uuid.uuid4()), project_id=project_id,
        geometry=body.geometry, attributes=body.attributes, created_by=body.created_by,
    )
    await feature_repo.create(feature)
    return _feature_response(feature)


@router.get("/{project_id}/features", response_model=list[FeatureResponse])
async def list_features(
    project_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    await _get_project_or_404(project_id, repo)
    return [_feature_response(f) for f in await feature_repo.list_by_project(project_id)]


@router.get("/{project_id}/features/{feature_id}", response_model=FeatureResponse)
async def get_feature(
    project_id: str, feature_id: str,
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    feature = await feature_repo.get_by_id(feature_id)
    if feature is None or feature.project_id != project_id:
        raise HTTPException(status_code=404, detail="Feature not found")
    return _feature_response(feature)


@router.patch("/{project_id}/features/{feature_id}", response_model=FeatureResponse)
async def update_feature(
    project_id: str, feature_id: str, body: FeatureUpdate,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    feature = await feature_repo.get_by_id(feature_id)
    if feature is None or feature.project_id != project_id:
        raise HTTPException(status_code=404, detail="Feature not found")
    try:
        if body.geometry is not None:
            validate_geometry(body.geometry, project.geometry_type)
            feature.geometry = body.geometry
        if body.attributes is not None:
            merged = {**feature.attributes, **body.attributes}
            validate_attributes(project.form_schema, merged)
            feature.attributes = merged
    except (GeometryValidationError, FormValidationError) as exc:
        detail = getattr(exc, "errors", str(exc))
        raise HTTPException(status_code=422, detail=detail)
    await feature_repo.update(feature)
    return _feature_response(feature)


@router.delete("/{project_id}/features/{feature_id}", status_code=204)
async def delete_feature(
    project_id: str, feature_id: str,
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    feature = await feature_repo.get_by_id(feature_id)
    if feature is None or feature.project_id != project_id:
        raise HTTPException(status_code=404, detail="Feature not found")
    # NOTE: attachment cleanup for this feature added in Task 6.
    await feature_repo.delete(feature_id)
```

- [ ] **Step 2: Register router** in `app/api/v1/api.py`:

```python
from app.api.v1.endpoints import tiles, upload, layers, csw, esri, projects
...
api_router.include_router(projects.router)
```

- [ ] **Step 3: Verify E2E manually** (server auto-migrates on startup):

```bash
uvicorn app.main:app --port 8010 &   # or reuse running dev server
curl -s -X POST localhost:8010/api/v1/projects -H 'content-type: application/json' \
  -d '{"name":"Survey Jalan","geometry_type":"point","form_schema":[{"name":"kondisi","label":"Kondisi","type":"select","required":true,"options":["baik","rusak"]}]}'
# → 200, save id as PID
curl -s -X POST localhost:8010/api/v1/projects/$PID/features -H 'content-type: application/json' \
  -d '{"geometry":{"type":"Point","coordinates":[106.8,-6.2]},"attributes":{"kondisi":"baik"},"created_by":"anjar"}'
# → 200
curl -s -X POST localhost:8010/api/v1/projects/$PID/features -H 'content-type: application/json' \
  -d '{"geometry":{"type":"LineString","coordinates":[[1,1],[2,2]]},"attributes":{"kondisi":"baik"}}'
# → 422 (geometry type mismatch)
curl -s -X POST localhost:8010/api/v1/projects/$PID/features -H 'content-type: application/json' \
  -d '{"geometry":{"type":"Point","coordinates":[106.8,-6.2]},"attributes":{}}'
# → 422 (kondisi required)
```

Kill the temporary server afterwards. Run `python -m pytest` → green.

- [ ] **Step 4: Checkpoint** — Task 5 ready.

---

### Task 6: Attachments

**Files:**
- Modify: `app/core/config.py` (add `ATTACHMENTS_DIR`, `ATTACHMENT_MAX_SIZE`)
- Modify: `app/main.py` (static mount)
- Modify: `app/api/v1/endpoints/projects.py` (upload endpoint + cascade cleanup)

**Interfaces:**
- Consumes: `AttachmentRepository` (Task 4), `AttachmentResponse` schema.
- Produces: `POST /api/v1/projects/{project_id}/attachments` (multipart `file`, optional form field `field_name`) → `AttachmentResponse`; static serving at `/attachments/{project_id}/{stored_filename}`; helper `_delete_feature_attachments(feature, project, session)` used by feature/project delete.

- [ ] **Step 1: Config** — add to `Settings` in `app/core/config.py` next to the other DIR fields:

```python
ATTACHMENTS_DIR: Path = BASE_DIR / "data" / "attachments"
ATTACHMENT_MAX_SIZE: int = Field(default=10 * 1024 * 1024, env="ATTACHMENT_MAX_SIZE")
```

If `main.py`/startup creates data dirs (check how TILES_DIR handled), add `settings.ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)` in the same place.

- [ ] **Step 2: Static mount** in `app/main.py` next to the `/tiles` mount:

```python
app.mount("/attachments", StaticFiles(directory=settings.ATTACHMENTS_DIR), name="attachments")
```

(Directory must exist before mount — create in step 1's startup path or right before mount.)

- [ ] **Step 3: Upload endpoint** — append to `projects.py`:

```python
import shutil
from pathlib import Path

from fastapi import File, Form, UploadFile

from app.core.config import settings
from app.domain.models import Attachment
from app.domain.schemas import AttachmentResponse
from app.infrastructure.db.repository import AttachmentRepository

DEFAULT_ATTACHMENT_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf"}


def get_attachment_repo(session=Depends(get_async_session)) -> AttachmentRepository:
    return AttachmentRepository(session)


def _allowed_extensions(project: Project, field_name: Optional[str]) -> set[str]:
    if field_name:
        for field in project.form_schema:
            if field.get("name") == field_name and field.get("extensions"):
                return {e.lower().lstrip(".") for e in field["extensions"]}
    return DEFAULT_ATTACHMENT_EXTENSIONS


@router.post("/{project_id}/attachments", response_model=AttachmentResponse)
async def upload_attachment(
    project_id: str,
    file: UploadFile = File(...),
    field_name: Optional[str] = Form(None),
    repo: ProjectRepository = Depends(get_project_repo),
    attachment_repo: AttachmentRepository = Depends(get_attachment_repo),
):
    project = await _get_project_or_404(project_id, repo)
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if ext not in _allowed_extensions(project, field_name):
        raise HTTPException(status_code=422, detail=f"extension .{ext} not allowed")
    if file.size and file.size > settings.ATTACHMENT_MAX_SIZE:
        raise HTTPException(status_code=413, detail=f"attachment exceeds {settings.ATTACHMENT_MAX_SIZE} bytes")
    attachment_id = str(uuid.uuid4())
    stored_name = f"{attachment_id}_{Path(file.filename).name}"
    dest_dir = settings.ATTACHMENTS_DIR / project_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / stored_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    attachment = Attachment(
        id=attachment_id, project_id=project_id, filename=file.filename or stored_name,
        stored_path=str(dest), content_type=file.content_type, size_bytes=dest.stat().st_size,
    )
    await attachment_repo.create(attachment)
    return AttachmentResponse(
        id=attachment.id, project_id=project_id, filename=attachment.filename,
        url=f"/attachments/{project_id}/{stored_name}",
        content_type=attachment.content_type, size_bytes=attachment.size_bytes,
    )
```

Convention: the client stores the returned `id` in the feature's `file` attribute value.

- [ ] **Step 4: Cascade cleanup** — in `projects.py` add helper and wire into `delete_feature` and `delete_project`:

```python
async def _delete_attachments_for(
    project: Project,
    attachment_repo: AttachmentRepository,
    referenced_ids: Optional[set[str]] = None,
) -> None:
    """Delete attachment rows+files for a project; if referenced_ids given, only those."""
    for a in await attachment_repo.list_by_project(project.id):
        if referenced_ids is not None and a.id not in referenced_ids:
            continue
        Path(a.stored_path).unlink(missing_ok=True)
        await attachment_repo.delete(a.id)


def _attachment_ids_in(feature: Feature, schema: list) -> set[str]:
    file_fields = {f["name"] for f in schema if f.get("type") == "file"}
    return {v for k, v in feature.attributes.items() if k in file_fields and isinstance(v, str)}
```

In `delete_feature`: add `repo` + `attachment_repo` dependencies, load project, compute `_attachment_ids_in(feature, project.form_schema)`, call `_delete_attachments_for(project, attachment_repo, ids)` before deleting the feature.
In `delete_project`: call `_delete_attachments_for(project, attachment_repo)` (all), then `shutil.rmtree(settings.ATTACHMENTS_DIR / project_id, ignore_errors=True)`.

- [ ] **Step 5: Verify manually**

```bash
curl -s -F "file=@/some/test.png" -F "field_name=foto" localhost:8010/api/v1/projects/$PID/attachments
# → 200 with url; curl that url → 200 image
curl -s -F "file=@/some/script.sh" localhost:8010/api/v1/projects/$PID/attachments  # → 422
```

Delete the feature referencing it → file gone from `data/attachments/{PID}/`. `python -m pytest` → green.

- [ ] **Step 6: Checkpoint** — Task 6 ready.

---

### Task 7: Live FeatureCollection endpoint + export (TDD on flattening)

**Files:**
- Create: `app/infrastructure/services/project_export_service.py`
- Test: `tests/test_project_export_service.py`
- Modify: `app/api/v1/endpoints/projects.py` (append endpoints)

**Interfaces:**
- Consumes: `Feature`, `Project` models; repositories.
- Produces:
  - `build_feature_collection(project: Project, features: list[Feature], base_url: str = "") -> dict` — GeoJSON FeatureCollection; each feature's properties = flattened attributes + `_id`, `_created_by`, `_created_at` (ISO).
  - `flatten_attributes(schema: list, attributes: dict, base_url: str = "") -> dict` — multiselect → `";".join`, checkbox → bool, file → `f"{base_url}/attachments/..."` URL if resolvable else raw id, other values passthrough.
  - `shp_safe_columns(names: list[str]) -> dict[str, str]` — ≤10 chars, deduped (`kondisi_ja`, clash → `kondisi_1`, `kondisi_2`, …).
  - `export_csv(project, features) -> str` (CSV text; columns: `id`, schema field names in order, `created_by`, `created_at`, `wkt`, plus `longitude`/`latitude` when `geometry_type == "point"`).
  - `export_shp_zip(project, features, dest_dir: Path) -> Path` — writes zipped shapefile via geopandas, returns zip path.
  - Endpoints: `GET /api/v1/projects/{project_id}/features.geojson`, `GET /api/v1/projects/{project_id}/export?format=geojson|csv|shp`.

- [ ] **Step 1: Write failing tests** `tests/test_project_export_service.py`:

```python
from app.domain.models import Feature, Project
from app.infrastructure.services.project_export_service import (
    build_feature_collection, export_csv, flatten_attributes, shp_safe_columns,
)

SCHEMA = [
    {"name": "nama", "label": "Nama", "type": "text"},
    {"name": "fasilitas", "label": "Fasilitas", "type": "multiselect", "options": ["pju", "drainase"]},
    {"name": "aktif", "label": "Aktif", "type": "checkbox"},
]


def _project(**kw):
    defaults = dict(id="p1", name="Survey", geometry_type="point", form_schema=SCHEMA)
    defaults.update(kw)
    return Project(**defaults)


def _feature(**kw):
    defaults = dict(
        id="f1", project_id="p1",
        geometry={"type": "Point", "coordinates": [106.8, -6.2]},
        attributes={"nama": "Titik A", "fasilitas": ["pju", "drainase"], "aktif": True},
        created_by="anjar",
    )
    defaults.update(kw)
    return Feature(**defaults)


def test_flatten_multiselect_joined():
    flat = flatten_attributes(SCHEMA, _feature().attributes)
    assert flat["fasilitas"] == "pju;drainase"
    assert flat["aktif"] is True
    assert flat["nama"] == "Titik A"


def test_feature_collection_shape():
    fc = build_feature_collection(_project(), [_feature()])
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    f = fc["features"][0]
    assert f["geometry"]["type"] == "Point"
    assert f["properties"]["_id"] == "f1"
    assert f["properties"]["nama"] == "Titik A"


def test_shp_safe_columns_truncate_and_dedup():
    cols = shp_safe_columns(["kondisi_jalan_utama", "kondisi_jalan_kedua", "nama"])
    assert all(len(v) <= 10 for v in cols.values())
    assert len(set(cols.values())) == 3
    assert cols["nama"] == "nama"


def test_export_csv_point_has_lon_lat_and_wkt():
    csv_text = export_csv(_project(), [_feature()])
    header = csv_text.splitlines()[0].split(",")
    assert "wkt" in header and "longitude" in header and "latitude" in header
    row = csv_text.splitlines()[1]
    assert "POINT" in row and "Titik A" in row


def test_export_csv_line_has_no_lon_lat():
    p = _project(geometry_type="line")
    f = _feature(geometry={"type": "LineString", "coordinates": [[1, 1], [2, 2]]})
    header = export_csv(p, [f]).splitlines()[0].split(",")
    assert "longitude" not in header and "wkt" in header
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_project_export_service.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** `app/infrastructure/services/project_export_service.py`:

```python
"""Build FeatureCollections and flat exports (CSV/SHP) from survey Features."""
import csv
import io
import zipfile
from pathlib import Path

from shapely.geometry import shape

from app.domain.models import Feature, Project


def flatten_attributes(schema: list, attributes: dict, base_url: str = "") -> dict:
    by_name = {f["name"]: f for f in schema}
    flat = {}
    for field in schema:
        name = field["name"]
        value = attributes.get(name)
        if value is None:
            flat[name] = None
        elif field.get("type") == "multiselect" and isinstance(value, list):
            flat[name] = ";".join(str(v) for v in value)
        elif field.get("type") == "file" and isinstance(value, str) and base_url:
            flat[name] = f"{base_url}/attachments/{value}"
        else:
            flat[name] = value
    return flat


def build_feature_collection(project: Project, features: list[Feature], base_url: str = "") -> dict:
    out = []
    for f in features:
        props = flatten_attributes(project.form_schema, f.attributes, base_url)
        props["_id"] = f.id
        props["_created_by"] = f.created_by
        props["_created_at"] = f.created_at.isoformat() if f.created_at else None
        out.append({"type": "Feature", "id": f.id, "geometry": f.geometry, "properties": props})
    return {"type": "FeatureCollection", "features": out}


def shp_safe_columns(names: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for name in names:
        candidate = name[:10]
        i = 1
        while candidate in used:
            suffix = f"_{i}"
            candidate = name[: 10 - len(suffix)] + suffix
            i += 1
        mapping[name] = candidate
        used.add(candidate)
    return mapping


def export_csv(project: Project, features: list[Feature]) -> str:
    field_names = [f["name"] for f in project.form_schema]
    header = ["id"] + field_names + ["created_by", "created_at", "wkt"]
    is_point = project.geometry_type == "point"
    if is_point:
        header += ["longitude", "latitude"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for f in features:
        flat = flatten_attributes(project.form_schema, f.attributes)
        geom = shape(f.geometry)
        row = [f.id] + [flat.get(n) for n in field_names] + [
            f.created_by, f.created_at.isoformat() if f.created_at else None, geom.wkt,
        ]
        if is_point:
            row += [geom.x, geom.y]
        writer.writerow(row)
    return buf.getvalue()


def export_shp_zip(project: Project, features: list[Feature], dest_dir: Path) -> Path:
    import geopandas as gpd

    field_names = [f["name"] for f in project.form_schema]
    colmap = shp_safe_columns(field_names + ["created_by"])
    records, geoms = [], []
    for f in features:
        flat = flatten_attributes(project.form_schema, f.attributes)
        rec = {colmap[n]: flat.get(n) for n in field_names}
        rec[colmap["created_by"]] = f.created_by
        records.append(rec)
        geoms.append(shape(f.geometry))
    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs="EPSG:4326")
    shp_dir = dest_dir / "shp"
    shp_dir.mkdir(parents=True, exist_ok=True)
    shp_path = shp_dir / f"{project.id}.shp"
    gdf.to_file(shp_path, driver="ESRI Shapefile")
    zip_path = dest_dir / f"{project.name.replace(' ', '_')}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for part in shp_dir.iterdir():
            zf.write(part, part.name)
    return zip_path
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_project_export_service.py -v` → PASS. Full suite green.

- [ ] **Step 5: Endpoints** — append to `projects.py`:

```python
import tempfile

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.background import BackgroundTask

from app.infrastructure.services.project_export_service import (
    build_feature_collection, export_csv, export_shp_zip,
)


@router.get("/{project_id}/features.geojson")
async def project_geojson(
    project_id: str, request: Request,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    features = await feature_repo.list_by_project(project_id)
    base_url = str(request.base_url).rstrip("/")
    return JSONResponse(build_feature_collection(project, features, base_url))


@router.get("/{project_id}/export")
async def export_project(
    project_id: str, format: str = "geojson",
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
):
    project = await _get_project_or_404(project_id, repo)
    features = await feature_repo.list_by_project(project_id)
    safe_name = project.name.replace(" ", "_")
    if format == "geojson":
        return JSONResponse(
            build_feature_collection(project, features),
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.geojson"'},
        )
    if format == "csv":
        return PlainTextResponse(
            export_csv(project, features), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
        )
    if format == "shp":
        if not features:
            raise HTTPException(status_code=422, detail="no features to export")
        tmp = tempfile.mkdtemp(prefix="shp_export_")
        zip_path = export_shp_zip(project, features, Path(tmp))
        return FileResponse(
            zip_path, media_type="application/zip", filename=f"{safe_name}.zip",
            background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
        )
    raise HTTPException(status_code=422, detail="format must be geojson|csv|shp")
```

Route order note: FastAPI matches `/{project_id}/features.geojson` before `/{project_id}/features/{feature_id}`? No — paths are distinct literals, no conflict; but `features.geojson` must not be swallowed by `/{project_id}/features/{feature_id}` — it isn't (different segment count). No action needed.

- [ ] **Step 6: Verify manually**

```bash
curl -s localhost:8010/api/v1/projects/$PID/features.geojson | python -m json.tool | head
curl -s "localhost:8010/api/v1/projects/$PID/export?format=csv"
curl -s -o /tmp/claude-1000/.../scratchpad/test.zip "localhost:8010/api/v1/projects/$PID/export?format=shp" && unzip -l .../test.zip
```

Expected: FeatureCollection JSON; CSV with wkt/longitude/latitude; zip containing `.shp/.shx/.dbf/.prj`.

- [ ] **Step 7: Checkpoint** — Task 7 ready.

---

### Task 8: Publish / unpublish as Layer

**Files:**
- Modify: `app/api/v1/endpoints/projects.py` (append)

**Interfaces:**
- Consumes: `LayerRepository` (existing async repo in `app/infrastructure/db/repository.py` — check its exact method names, ~line 200; it has `create`-equivalent via session add or use `SyncLayerRepository.create` pattern), `build_feature_collection`, `PublishResponse`.
- Produces: `POST /api/v1/projects/{project_id}/publish` → `PublishResponse`; `DELETE /api/v1/projects/{project_id}/publish` → 204.

Default Simple Style (matches CONTEXT.md vocabulary, stored in `file_metadata.style`):

```python
DEFAULT_STYLE = {
    "mode": "simple",
    "simple": {
        "Point": {"fillColor": "#2E7DD1", "strokeColor": "#1A4E86", "strokeWidth": 1, "opacity": 1.0, "pointRadius": 6},
        "LineString": {"strokeColor": "#2E7DD1", "strokeWidth": 2, "opacity": 1.0, "strokePattern": "solid"},
        "Polygon": {"fillColor": "#2E7DD1", "strokeColor": "#1A4E86", "strokeWidth": 1, "opacity": 0.6, "fillPattern": "solid"},
    },
}
```

- [ ] **Step 1: Implement publish** — append to `projects.py` (adjust `LayerRepository` usage to the actual methods found in `repository.py`; if the async `LayerRepository` lacks `create`/`delete`, add them there following `ProjectRepository`'s pattern):

```python
from app.domain.models import Layer, LayerType
from app.domain.schemas import PublishResponse
from app.infrastructure.db.repository import LayerRepository
from shapely.geometry import shape as _shape


def get_layer_repo(session=Depends(get_async_session)) -> LayerRepository:
    return LayerRepository(session)


def _compute_bbox(features: list[Feature]) -> Optional[tuple[float, float, float, float]]:
    bounds = [_shape(f.geometry).bounds for f in features]
    if not bounds:
        return None
    return (
        min(b[0] for b in bounds), min(b[1] for b in bounds),
        max(b[2] for b in bounds), max(b[3] for b in bounds),
    )


@router.post("/{project_id}/publish", response_model=PublishResponse)
async def publish_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    feature_repo: FeatureRepository = Depends(get_feature_repo),
    layer_repo: LayerRepository = Depends(get_layer_repo),
):
    project = await _get_project_or_404(project_id, repo)
    if project.layer_id is not None:
        raise HTTPException(status_code=409, detail="Project already published")
    features = await feature_repo.list_by_project(project_id)
    geojson_url = f"{settings.API_V1_STR}/projects/{project_id}/features.geojson"
    layer = Layer(
        id=str(uuid.uuid4()),
        layer_type=LayerType.geojson,
        filename=project.name,
        file_type="geojson",
        tile_url_template=geojson_url,
        is_active=True,
        is_visible=True,
        file_metadata={"project_id": project_id, "style": DEFAULT_STYLE},
    )
    bbox = _compute_bbox(features)
    if bbox:
        layer.bbox_west, layer.bbox_south, layer.bbox_east, layer.bbox_north = bbox
    await layer_repo.create(layer)
    project.layer_id = layer.id
    await repo.update(project)
    return PublishResponse(project_id=project_id, layer_id=layer.id, geojson_url=geojson_url)


@router.delete("/{project_id}/publish", status_code=204)
async def unpublish_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_project_repo),
    layer_repo: LayerRepository = Depends(get_layer_repo),
):
    project = await _get_project_or_404(project_id, repo)
    if project.layer_id is None:
        raise HTTPException(status_code=409, detail="Project is not published")
    await layer_repo.delete(project.layer_id)
    project.layer_id = None
    await repo.update(project)
```

Resilience rule (ADR-0003): if the Layer row was already deleted directly via the layers endpoint, `layer_repo.delete` returning False/None must not fail — clear `project.layer_id` regardless. Also update `delete_project` (Task 5) to delete the linked layer: if `project.layer_id`, call `layer_repo.delete(project.layer_id)` first, and clear `layer_id` FK before deleting project row (FK constraint: set `project.layer_id = None` + update, then delete layer, then delete project).

- [ ] **Step 2: Check async `LayerRepository`** for `create`/`delete` methods (`app/infrastructure/db/repository.py:200`). If missing, add following `ProjectRepository` pattern.

- [ ] **Step 3: Verify manually**

```bash
curl -s -X POST localhost:8010/api/v1/projects/$PID/publish     # → 200 layer_id + geojson_url
curl -s localhost:8010/api/v1/layers | python -m json.tool | grep -A2 geojson   # layer listed
curl -s -X POST localhost:8010/api/v1/projects/$PID/publish     # → 409
curl -s -X DELETE localhost:8010/api/v1/projects/$PID/publish   # → 204; layer gone, features intact
```

`python -m pytest` → green.

- [ ] **Step 4: Checkpoint** — Task 8 ready.

---

### Task 9: Documentation

**Files:**
- Create: `docs/SURVEY_PROJECTS.md`
- Modify: `CLAUDE.md` (architecture section: new endpoints file, new tables, data dir `attachments/`)
- Modify: `docs/API.md` (append project endpoints table)

**Interfaces:** none (docs only).

- [ ] **Step 1: Write `docs/SURVEY_PROJECTS.md`** covering: concept mapping to CONTEXT.md terms; field type reference table with schema JSON examples; full endpoint list with sample request/response bodies (copy the curl examples from Tasks 5–8); publish semantics (live projection, ADR-0003); export formats + flattening rules; attachment lifecycle.

- [ ] **Step 2: Update `CLAUDE.md`:** add `projects.py` under endpoints list; add `projects`/`features`/`attachments` tables under Current schema; add `attachments/` to data directory layout; add survey flow summary under Geoportal Layers Types.

- [ ] **Step 3: Update `docs/API.md`** with the new endpoint table (method, path, purpose, status codes).

- [ ] **Step 4: Final verification** — `python -m pytest` all green; start uvicorn, open `/docs`, confirm `projects` tag renders with all endpoints; run the full manual E2E from Task 5+7+8 once end-to-end. Report results to user.

- [ ] **Step 5: Checkpoint** — feature complete; hand entire tree to user for commit.

---

## Self-Review Notes

- Spec coverage: dynamic form (T2, T5), geometry point/line/polygon (T1, T3), project table (T1), file upload field (T6), publish-as-spatial-output (T8), export (T7), docs (T9). Q1–Q13 decisions all mapped.
- Type consistency: `FormValidationError.errors` used in endpoints via `getattr(exc, "errors", str(exc))`; `GeometryType` values are lowercase strings matching `ProjectCreate.geometry_type`; `flatten_attributes(schema, attributes, base_url)` signature consistent across T7 tests/impl/endpoints.
- Known deliberate deferrals (YAGNI): pagination on features list, categorized symbology, Multi* geometries, snapshot/bake-to-tiles, auth.
