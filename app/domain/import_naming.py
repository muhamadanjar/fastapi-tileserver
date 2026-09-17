"""Import naming helpers — pure identifier/table-name derivation."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional


def sanitize_identifier(value: str, *, fallback: str = "field", max_length: int = 63) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", normalized).strip("_").lower()
    normalized = re.sub(r"_+", "_", normalized)
    if not normalized:
        normalized = fallback
    if normalized[0].isdigit():
        normalized = f"_{normalized}"
    return normalized[:max_length].rstrip("_") or fallback


def build_import_table_name(filename: str, layer_id: str) -> str:
    stem = Path(filename).stem
    suffix = sanitize_identifier(layer_id.replace("-", ""), fallback="layer")[:8]
    base_max = 63 - len(suffix) - 1
    base = sanitize_identifier(stem, fallback="shapefile", max_length=base_max)
    return f"{base}_{suffix}"


def staging_table_name(upload_id: str, dataset_index: Optional[int] = None) -> str:
    compact = sanitize_identifier(upload_id.replace("-", ""), fallback="upload", max_length=44)
    suffix = "" if dataset_index is None else f"_{dataset_index + 1}"
    return f"_import_{compact}{suffix}"