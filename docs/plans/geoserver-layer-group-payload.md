# GeoServer layer-group payload

Status: active

Related Progress: [geoserver-layer-group-payload](../progress/geoserver-layer-group-payload.md)

## Goal

Publish a WMS layer group with GeoServer's nested `layers.layer` and
`styles.style` REST representation, avoiding duplicate `layers` fields.

## Plan

1. Build the GeoServer group request through a dedicated payload helper.
2. Encode all visible layers in one `layers` container and default styles in
   the matching `styles` container.
3. Add a focused regression test for a three-layer group.
4. Run affected tests and restart the worker before retrying a failed batch.
