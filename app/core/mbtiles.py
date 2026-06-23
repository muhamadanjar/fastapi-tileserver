"""Standalone MBTiles writer/reader utility.

MBTiles is the SQLite-based container for map tiles
(https://github.com/mapbox/mbtiles-spec). Zero third-party dependencies
(stdlib sqlite3/pathlib/json) so it can be imported or copied into any app.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple, Union

PathLike = Union[str, Path]
BBox = Tuple[float, float, float, float]  # (west, south, east, north) WGS84

_FORMAT_BY_EXT = {
    "png": "png", "jpg": "jpg", "jpeg": "jpg",
    "webp": "webp", "pbf": "pbf", "mvt": "pbf",
}


def normalize_format(value: str) -> str:
    key = value.lower().lstrip(".")
    if key not in _FORMAT_BY_EXT:
        raise ValueError(f"Unsupported tile format '{value}'. "
                         f"Supported: {sorted(set(_FORMAT_BY_EXT.values()))}")
    return _FORMAT_BY_EXT[key]


def xyz_to_tms_row(y: int, zoom: int) -> int:
    """XYZ row (top-left origin) -> TMS row (bottom-left, MBTiles storage)."""
    return (1 << zoom) - 1 - y


tms_to_xyz_row = xyz_to_tms_row  # involution per zoom


class MBTilesWriter:
    """Incrementally build an MBTiles file. Use as a context manager."""

    def __init__(self, path: PathLike, tile_format: str, overwrite: bool = True):
        self.path = Path(path)
        self.tile_format = normalize_format(tile_format)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite and self.path.exists():
            self.path.unlink()
        self._conn: Optional[sqlite3.Connection] = None
        self._tile_count = 0
        self._zooms: set[int] = set()

    def __enter__(self) -> "MBTilesWriter":
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute("PRAGMA journal_mode = MEMORY")
        self._conn.execute("PRAGMA synchronous = OFF")
        self._create_schema()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._conn is None:
            return
        try:
            if exc_type is None:
                self._finalize()
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
            self._conn = None

    def _create_schema(self) -> None:
        c = self._conn
        c.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        c.execute("CREATE TABLE tiles ("
                  " zoom_level INTEGER, tile_column INTEGER,"
                  " tile_row INTEGER, tile_data BLOB)")
        c.execute("CREATE UNIQUE INDEX tile_index "
                  "ON tiles (zoom_level, tile_column, tile_row)")

    def set_metadata(self, name: str, bounds: Optional[BBox] = None,
                     minzoom: Optional[int] = None, maxzoom: Optional[int] = None,
                     description: Optional[str] = None, attribution: Optional[str] = None,
                     layer_type: str = "overlay", extra: Optional[Dict[str, str]] = None,
                     vector_layers: Optional[list] = None) -> None:
        meta: Dict[str, str] = {
            "name": name, "format": self.tile_format,
            "type": layer_type, "version": "1.0.0",
        }
        if description is not None:
            meta["description"] = description
        if attribution is not None:
            meta["attribution"] = attribution
        if bounds is not None:
            meta["bounds"] = ",".join(str(v) for v in bounds)
            cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
            meta["center"] = f"{cx},{cy},{minzoom if minzoom is not None else 0}"
        if minzoom is not None:
            meta["minzoom"] = str(minzoom)
        if maxzoom is not None:
            meta["maxzoom"] = str(maxzoom)
        if self.tile_format == "pbf" and vector_layers is not None:
            meta["json"] = json.dumps({"vector_layers": vector_layers})
        if extra:
            meta.update({k: str(v) for k, v in extra.items()})
        self._conn.executemany(
            "INSERT INTO metadata (name, value) VALUES (?, ?)", list(meta.items()))

    def add_tile(self, z: int, x: int, y: int, data: bytes, *, scheme: str = "xyz") -> None:
        row = xyz_to_tms_row(y, z) if scheme == "xyz" else y
        self._conn.execute(
            "INSERT OR REPLACE INTO tiles "
            "(zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
            (z, x, row, sqlite3.Binary(data)))
        self._tile_count += 1
        self._zooms.add(z)

    def _finalize(self) -> None:
        if not self._zooms:
            return
        have = {r[0] for r in self._conn.execute(
            "SELECT name FROM metadata WHERE name IN ('minzoom','maxzoom')")}
        if "minzoom" not in have:
            self._conn.execute("INSERT INTO metadata (name, value) VALUES ('minzoom', ?)",
                               (str(min(self._zooms)),))
        if "maxzoom" not in have:
            self._conn.execute("INSERT INTO metadata (name, value) VALUES ('maxzoom', ?)",
                               (str(max(self._zooms)),))

    @property
    def tile_count(self) -> int:
        return self._tile_count

    @property
    def zoom_levels(self) -> Tuple[Optional[int], Optional[int]]:
        return (min(self._zooms), max(self._zooms)) if self._zooms else (None, None)


class MBTilesReader:
    def __init__(self, path: PathLike):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"MBTiles not found: {self.path}")
        self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MBTilesReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def metadata(self) -> Dict[str, str]:
        return dict(self._conn.execute("SELECT name, value FROM metadata"))

    def get_tile(self, z: int, x: int, y: int, *, scheme: str = "xyz") -> Optional[bytes]:
        row = xyz_to_tms_row(y, z) if scheme == "xyz" else y
        hit = self._conn.execute(
            "SELECT tile_data FROM tiles "
            "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, x, row)).fetchone()
        return bytes(hit[0]) if hit else None

    def tile_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]


def iter_pyramid_tiles(tiles_dir: PathLike, ext: str) -> Iterator[Tuple[int, int, int, bytes]]:
    """Yield (z, x, y_xyz, data) for every {z}/{x}/{y}.{ext} on disk."""
    base = Path(tiles_dir)
    ext = ext.lstrip(".")
    for z_dir in sorted(base.iterdir(), key=lambda p: p.name):
        if not (z_dir.is_dir() and z_dir.name.isdigit()):
            continue
        z = int(z_dir.name)
        for x_dir in sorted(z_dir.iterdir(), key=lambda p: p.name):
            if not (x_dir.is_dir() and x_dir.name.isdigit()):
                continue
            x = int(x_dir.name)
            for tile_file in x_dir.glob(f"*.{ext}"):
                if tile_file.stem.isdigit():
                    yield z, x, int(tile_file.stem), tile_file.read_bytes()


def pack_tile_pyramid(tiles_dir: PathLike, output_path: PathLike, tile_format: str, *,
                      name: str, bounds: Optional[BBox] = None,
                      description: Optional[str] = None, attribution: Optional[str] = None,
                      vector_layers: Optional[list] = None,
                      progress_callback=None, progress_every: int = 200) -> Dict[str, object]:
    """Aggregate an on-disk XYZ pyramid into one .mbtiles. Returns a summary dict."""
    ext = normalize_format(tile_format)  # "png"/"jpg"/"webp"/"pbf"
    src = Path(tiles_dir)
    if not src.exists():
        raise FileNotFoundError(f"Tile directory not found: {src}")

    total = sum(1 for _ in iter_pyramid_tiles(src, ext))
    if total == 0:
        raise ValueError(f"No '.{ext}' tiles found under {src}")

    done = 0
    with MBTilesWriter(output_path, tile_format=tile_format) as writer:
        for z, x, y, data in iter_pyramid_tiles(src, ext):
            writer.add_tile(z, x, y, data, scheme="xyz")
            done += 1
            if progress_callback and done % progress_every == 0:
                progress_callback({"percent": min(99, round(done * 100 / total)),
                                   "tiles_done": done, "tiles_total": total})
        minz, maxz = writer.zoom_levels
        writer.set_metadata(name=name, bounds=bounds, minzoom=minz, maxzoom=maxz,
                            description=description, attribution=attribution,
                            vector_layers=vector_layers)
        tile_count = writer.tile_count

    if progress_callback:
        progress_callback({"percent": 100, "tiles_done": done, "tiles_total": total})

    out = Path(output_path)
    return {"path": str(out), "tile_count": tile_count, "min_zoom": minz,
            "max_zoom": maxz, "format": ext, "size_bytes": out.stat().st_size}
