# GeoServer layer-group payload

Related Plan: [GeoServer layer-group payload](../plans/geoserver-layer-group-payload.md)
Progress Archive: [geoserver-layer-group-payload](../progress/geoserver-layer-group-payload.md)

WMS layer groups are submitted to GeoServer as XML rather than the ambiguous
list-shaped JSON representation. The payload contains one `layers` element with
one `layer` child per visible member, and a matching `styles` element containing
empty `style` children so GeoServer retains each member's default style.

This avoids GeoServer's `Duplicate field layers` error when a batch contains
multiple Shapefiles.
