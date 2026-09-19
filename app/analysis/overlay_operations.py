"""
Core overlay analysis operations using GeoPandas and Shapely.

Each function takes input GeoDataFrames and returns a result GeoDataFrame.
"""

import geopandas as gpd


def _get_geometry_type(gdf: gpd.GeoDataFrame) -> str:
    """Detect dominant geometry type in a GeoDataFrame."""
    if gdf.empty:
        return "polygon"
    geom_types = [t.lower() for t in gdf.geometry.geom_type.unique() if t]
    # Normalize Multi* types and mixed collections to base types
    if any("polygon" in t for t in geom_types):
        return "polygon"
    if any("line" in t or "linestring" in t for t in geom_types):
        return "line"
    if any("point" in t for t in geom_types):
        return "point"
    return geom_types[0].lower() if geom_types else "polygon"


def intersection(gdf_a: gpd.GeoDataFrame, gdf_b: gpd.GeoDataFrame,
                 selected_attrs: dict | None = None) -> gpd.GeoDataFrame:
    """Compute intersection of two layers.

    Polygon+polygon uses overlay; polygon+point returns points within polygon;
    polygon+line returns the line parts inside the polygon.
    """
    geom_a = _get_geometry_type(gdf_a)
    geom_b = _get_geometry_type(gdf_b)

    if geom_a == "polygon" and geom_b == "point":
        # Spatial join: keep points of B inside A
        joined = gpd.sjoin(gdf_b, gdf_a, predicate="within")
        cols = [c for c in gdf_b.columns if c != "geometry"] + ["geometry"]
        result = joined[cols].reset_index(drop=True)
        return _select_attributes(result, selected_attrs, "b")

    if geom_a == "polygon" and geom_b == "line":
        clipped = gpd.clip(gdf_b, gdf_a)
        return _select_attributes(clipped, selected_attrs, "b")

    if geom_a == "point" and geom_b == "polygon":
        joined = gpd.sjoin(gdf_a, gdf_b, predicate="within")
        cols = [c for c in gdf_a.columns if c != "geometry"] + ["geometry"]
        result = joined[cols].reset_index(drop=True)
        return _select_attributes(result, selected_attrs, "a")

    if geom_a == "line" and geom_b == "polygon":
        clipped = gpd.clip(gdf_a, gdf_b)
        return _select_attributes(clipped, selected_attrs, "a")

    result = gpd.overlay(gdf_a, gdf_b, how="intersection")
    return _select_attributes(result, selected_attrs, "a")


def union(gdf_a: gpd.GeoDataFrame, gdf_b: gpd.GeoDataFrame,
          selected_attrs: dict | None = None) -> gpd.GeoDataFrame:
    """Compute union of two layers."""
    result = gpd.overlay(gdf_a, gdf_b, how="union")
    return _select_attributes(result, selected_attrs, "a")


def dissolve(gdf_a: gpd.GeoDataFrame, group_by: str | None = None) -> gpd.GeoDataFrame:
    """Dissolve all features or group by attribute."""
    if group_by and group_by in gdf_a.columns:
        dissolved = gdf_a.dissolve(by=group_by, aggfunc="first").reset_index()
    else:
        dissolved = gdf_a.dissolve(aggfunc="first").reset_index()
        if "index" in dissolved.columns:
            dissolved = dissolved.drop(columns=["index"])
    return dissolved


def clip(gdf_a: gpd.GeoDataFrame, gdf_b: gpd.GeoDataFrame,
         selected_attrs: dict | None = None) -> gpd.GeoDataFrame:
    """Clip layer A using boundary of layer B."""
    result = gpd.clip(gdf_a, gdf_b)
    return _select_attributes(result, selected_attrs, "a")


def difference(gdf_a: gpd.GeoDataFrame, gdf_b: gpd.GeoDataFrame,
               selected_attrs: dict | None = None) -> gpd.GeoDataFrame:
    """Compute difference: parts of A that do not overlap with B."""
    clipped = gpd.clip(gdf_a, gdf_b)
    if clipped.empty:
        return gdf_a.copy()

    result_parts = []
    for idx_a, row_a in gdf_a.iterrows():
        geom_a = row_a.geometry
        if geom_a is None or geom_a.is_empty:
            continue
        diff_geom = geom_a
        for idx_b, row_b in clipped.iterrows():
            geom_b = row_b.geometry
            if geom_b is not None and not geom_b.is_empty:
                try:
                    diff_geom = diff_geom.difference(geom_b)
                except Exception:
                    pass
        if diff_geom is not None and not diff_geom.is_empty:
            new_row = row_a.copy()
            new_row.geometry = diff_geom
            result_parts.append(new_row)

    if not result_parts:
        return gpd.GeoDataFrame(columns=gdf_a.columns, geometry="geometry", crs=gdf_a.crs)

    result = gpd.GeoDataFrame(result_parts, geometry="geometry", crs=gdf_a.crs)
    return _select_attributes(result, selected_attrs, "a")


def buffer(gdf_a: gpd.GeoDataFrame, distance: float,
           unit: str = "meters") -> gpd.GeoDataFrame:
    """Buffer all features by given distance."""
    dist_meters = _convert_to_meters(distance, unit)

    if gdf_a.crs and gdf_a.crs.is_geographic:
        # Project to UTM for accurate buffering
        utm_crs = _estimate_utm_crs(gdf_a)
        gdf_proj = gdf_a.to_crs(utm_crs)
        gdf_proj["geometry"] = gdf_proj.geometry.buffer(dist_meters)
        result = gdf_proj.to_crs(gdf_a.crs)
    else:
        result = gdf_a.copy()
        result["geometry"] = result.geometry.buffer(dist_meters)

    return result


def sym_difference(gdf_a: gpd.GeoDataFrame, gdf_b: gpd.GeoDataFrame,
                   selected_attrs: dict | None = None) -> gpd.GeoDataFrame:
    """Compute symmetric difference: parts of either layer that do not overlap."""
    result = gpd.overlay(gdf_a, gdf_b, how="symmetric_difference")
    return _select_attributes(result, selected_attrs, "a")


def simplify(gdf_a: gpd.GeoDataFrame, tolerance: float) -> gpd.GeoDataFrame:
    """Reduce vertex count within tolerance (in geometry units)."""
    result = gdf_a.copy()
    result["geometry"] = result.geometry.simplify(tolerance, preserve_topology=True)
    return result


def spatial_join(gdf_a: gpd.GeoDataFrame, gdf_b: gpd.GeoDataFrame,
                 predicate: str = "intersects",
                 selected_attrs: dict | None = None) -> gpd.GeoDataFrame:
    """Join attributes from layer B onto layer A by spatial predicate."""
    joined = gpd.sjoin(gdf_a, gdf_b, how="left", predicate=predicate)
    # Drop duplicate geometry columns; keep A's geometry
    geom_cols = [c for c in joined.columns if c.startswith("geometry")]
    if len(geom_cols) > 1:
        joined = joined.drop(columns=geom_cols[1:])
    return _select_attributes(joined, selected_attrs, "a")


def centroid(gdf_a: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Extract centroid of each feature."""
    result = gdf_a.copy()
    result["geometry"] = result.geometry.centroid
    return result


def _select_attributes(gdf: gpd.GeoDataFrame, selected_attrs: dict | None,
                       layer: str) -> gpd.GeoDataFrame:
    """Select specific attributes from result GeoDataFrame."""
    if not selected_attrs or layer not in selected_attrs:
        return gdf

    attrs = selected_attrs[layer]
    if not attrs:
        return gdf

    # Keep geometry + selected attributes
    keep_cols = ["geometry"] + [c for c in attrs if c in gdf.columns and c != "geometry"]
    return gdf[keep_cols]


def _convert_to_meters(distance: float, unit: str) -> float:
    """Convert distance to meters."""
    conversions = {
        "meters": 1.0,
        "kilometers": 1000.0,
        "feet": 0.3048,
        "miles": 1609.344,
    }
    return distance * conversions.get(unit, 1.0)


def _estimate_utm_crs(gdf: gpd.GeoDataFrame) -> str:
    """Estimate appropriate UTM CRS for the GeoDataFrame's extent."""
    bounds = gdf.total_bounds
    lon = (bounds[0] + bounds[2]) / 2
    lat = (bounds[1] + bounds[3]) / 2

    zone = int((lon + 180) / 6) + 1
    hemisphere = "north" if lat >= 0 else "south"
    epsg = 32600 + zone if hemisphere == "north" else 32700 + zone
    return f"EPSG:{epsg}"
