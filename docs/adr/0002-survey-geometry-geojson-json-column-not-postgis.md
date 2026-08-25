# Survey Feature geometry is stored as GeoJSON in a JSON column, not PostGIS

The survey/Project feature stores each Feature's geometry as a GeoJSON object in a plain JSON column on the `features` table. We deliberately do not use PostGIS (GeoAlchemy2, `geometry` columns), even though this is a geospatial service.

Reasons: the service must keep working on all three configured DB backends (PostgreSQL, MySQL, SQLite); the rest of the codebase already follows this pattern (bbox as four float columns, JSON metadata columns); and no server-side spatial querying (intersects/within/bbox filters) is required for the survey use case — rendering, export, and tiling all consume a GeoJSON FeatureCollection built in Python (geopandas/shapely), which reads the JSON column directly.

## Consequences

- Spatial filtering, if ever needed, happens in Python after loading features — acceptable at survey scale (hundreds to thousands of features per Project).
- If large-scale server-side spatial queries become a requirement, migrating to PostGIS is a data migration plus a PostgreSQL lock-in decision, and deserves its own ADR superseding this one.
