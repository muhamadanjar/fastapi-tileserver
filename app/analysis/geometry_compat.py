"""
Geometry type compatibility rules for overlay operations.

Defines which operations are valid for given geometry type pairs.
"""

from typing import Optional

# Geometry compatibility matrix:
# operation -> {input_a_type -> set of compatible input_b_types}
# For single-layer operations (dissolve, buffer), input_b is None.
COMPATIBILITY: dict[str, dict[str, set[Optional[str]]]] = {
    "intersection": {
        "polygon": {"polygon", "line", "point"},
        "line": {"polygon"},
        "point": {"polygon"},
    },
    "union": {
        "polygon": {"polygon"},
        "line": {"line"},
        "point": {"point"},
    },
    "dissolve": {
        "polygon": {None},
        "line": {None},
        "point": {None},
    },
    "clip": {
        "polygon": {"polygon"},
        "line": {"polygon"},
        "point": {"polygon"},
    },
    "difference": {
        "polygon": {"polygon"},
    },
    "buffer": {
        "polygon": {None},
        "line": {None},
        "point": {None},
    },
    "sym_difference": {
        "polygon": {"polygon"},
        "line": {"line"},
        "point": {"point"},
    },
    "simplify": {
        "polygon": {None},
        "line": {None},
        "point": {None},
    },
    "spatial_join": {
        "polygon": {"polygon", "point", "line"},
        "line": {"polygon", "point", "line"},
        "point": {"polygon", "point", "line"},
    },
    "centroid": {
        "polygon": {None},
        "line": {None},
        "point": {None},
    },
}

OPERATIONS_REQUIRING_SECOND_LAYER = {
    "intersection", "union", "clip", "difference", "sym_difference", "spatial_join",
}


def is_compatible(operation: str, geom_a: str, geom_b: Optional[str] = None) -> bool:
    """Check if geometry types are compatible for the given operation."""
    if operation not in COMPATIBILITY:
        return False

    op_compat = COMPATIBILITY[operation]
    if geom_a not in op_compat:
        return False

    if operation in OPERATIONS_REQUIRING_SECOND_LAYER:
        return geom_b in op_compat[geom_a]
    else:
        return geom_b is None or geom_b in op_compat[geom_a]


def get_compatible_operations(geom_a: str, geom_b: Optional[str] = None) -> list[str]:
    """Return list of operations compatible with the given geometry types."""
    compatible = []
    for op, compat in COMPATIBILITY.items():
        if geom_a in compat:
            if geom_b is None or geom_b in compat[geom_a]:
                compatible.append(op)
    return compatible
