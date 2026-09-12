"""Multi-dataset map vocabulary and invariants, independent of IO frameworks."""
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, ContextManager, Protocol
import re


class MapError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


class WorkCancelled(Exception):
    pass


def checked_code(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", value):
        raise MapError("Code must start with a letter and contain at most 80 lowercase letters, digits, _ or -")
    return value


@dataclass
class Dataset:
    id: str
    path: str
    name: str
    valid: bool = True
    error: str | None = None
    geometry: str = ""
    feature_count: int = 0
    bbox: list[float] = field(default_factory=list)
    style: dict = field(default_factory=dict)
    selected: bool = False
    layer_id: str = ""
    code: str = ""
    visible: bool = True
    status: str = "detected"
    progress: int = 0


@dataclass
class Batch:
    id: str
    upload_id: str
    filename: str
    status: str = "inspecting"
    source_digest: str = ""
    mode: str = "separate"
    output_format: str = "raster"
    max_zoom: int = 14
    group_id: str | None = None
    task_token: str = ""
    error: str | None = None
    datasets: list[Dataset] = field(default_factory=list)

    @classmethod
    def restore(cls, value: dict) -> "Batch":
        return cls(**{**value, "datasets": [Dataset(**item) for item in value["datasets"]]})


@dataclass
class Member:
    layer_id: str
    visible: bool = True


@dataclass
class Group:
    id: str
    code: str
    name: str
    output_format: str
    members: list[Member] = field(default_factory=list)
    status: str = "draft"
    revision: int = 0
    error: str | None = None

    @classmethod
    def restore(cls, value: dict) -> "Group":
        return cls(**{**value, "members": [Member(**item) for item in value["members"]]})


@dataclass
class LayerData:
    id: str
    code: str
    name: str
    output_format: str
    upload_id: str | None
    bbox: list[float]
    style: dict
    metadata: dict
    url: str


class Catalog(Protocol):
    """Transactional records; callers see committed aggregates, never ORM objects."""
    def batch_list(self, limit: int = ...) -> list[Batch]: ...
    def batch(self, identity: str) -> Batch: ...
    def group(self, identity: str) -> Group: ...
    def layer(self, identity: str) -> LayerData: ...
    def save(self, value: Batch | Group | LayerData) -> None: ...
    def groups(self) -> list[Group]: ...
    def groups_using(self, layer_id: str) -> list[Group]: ...
    def reserve(self, code: str, owner: str) -> None: ...
    def remove_group(self, identity: str) -> None: ...
    def upload(self, identity: str) -> dict: ...


class Store(Protocol):
    def transaction(self) -> ContextManager[Catalog]: ...


class MapRenderer(Protocol):
    """Owns source verification, working files and format-specific publication."""
    def inspect(self, source: dict) -> tuple[str, list[Dataset]]: ...
    def render(self, source: dict, batch: Batch, item: Dataset, progress: Callable[[int], None]) -> LayerData: ...
    def publish(self, group: Group, layers: list[LayerData]) -> None: ...
    def remove(self, group: Group) -> None: ...
    def legend_for_group(self, group: Group, layers: list[LayerData]) -> list[dict]: ...


def state(value: Batch | Group | LayerData) -> dict:
    return asdict(value)
