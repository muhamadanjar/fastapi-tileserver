"""Fast dependency-direction checks for Clean Architecture layers."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1] / "app"
INNER_LAYERS = ("domain", "application", "usecases", "analysis")
FORBIDDEN = ("app.infrastructure", "app.presentation", "app.workers")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.append(node.module)
    return values


@pytest.mark.parametrize("path", [path for layer in INNER_LAYERS for path in (ROOT / layer).rglob("*.py")])
def test_inner_layers_do_not_depend_on_outer_adapters(path: Path):
    violations = [
        imported
        for imported in _imports(path)
        if imported == FORBIDDEN or imported.startswith(tuple(f"{prefix}." for prefix in FORBIDDEN))
    ]
    assert not violations, f"{path.relative_to(ROOT.parent)} imports outer adapter(s): {violations}"
