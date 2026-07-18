# Publishing a Project creates a live Layer projection, not a snapshot

Publishing a survey Project creates a Layer of type `geojson` whose URL points at a dynamic endpoint that builds a FeatureCollection from the database on every request. This deviates from the service's existing flows, where a Layer is the *output of a processing job* (tiling/GeoServer publish) and is frozen until reprocessed.

We chose live projection because survey data is continuously edited — a snapshot Layer would silently go stale and force users into a manual re-publish loop. The Layer is therefore only a projection of the Project: deleting the Layer unpublishes the Project without touching data, and "published" is derived from the Layer's existence rather than stored as a status.

## Consequences

- Every map view hits the database; acceptable at survey scale. If a Project ever grows beyond that (~tens of thousands of features), the escape hatch is the existing tiling pipeline ("bake to tiles" as an additional option), not a change to this default.
- The `layers` table now contains rows whose `tile_url_template` points back at this service's own API rather than at static tile files or an external server.
