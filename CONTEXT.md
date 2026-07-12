# Ubiquitous Language — tileserver_api

## Layer

A renderable map entry tracked in the `layers` table. May originate from a local upload (tiled by us) or reference an external/remote service.

## GeoServer-published Layer

A Layer whose data was pushed by this service to GeoServer (SHP publish flow). Recognisable by populated GeoServer metadata. It is the only kind of WMS Layer whose style we can edit; External WMS Layers are read-only foreign services.

## External WMS Layer

A Layer of type `wms` pointing at a server we do not control. Style editing is not applicable and must be rejected.

## Layer Style

The visual symbology of a Layer as last configured through the editor. Stored per Layer; there is deliberately **no shared/general style** — every GeoServer-published Layer owns exactly one style of its own.

## Simple Style

A Layer Style expressed as geometry-keyed JSON (`Polygon` / `LineString` / `Point`, each with `fillColor`, `strokeColor`, `strokeWidth`, `opacity`, `pointRadius`, `strokePattern`, `fillPattern`). The same vocabulary drives both local vector tiling and WMS styling — pattern names are shared verbatim with the dashboard editor.

## Stroke Pattern

Named line dash style on a Simple Style: `solid` | `dashed` | `dotted` | `dash-dot`. Unknown names are rejected.

## Fill Pattern

Named area fill texture on a Simple Style: `solid` | `hatched` | `cross-hatched` | `dotted`. Unknown names are rejected.

## Custom SLD

A Layer Style expressed as raw SLD XML supplied by an advanced user. Mutually exclusive with Simple Style for a given Layer at any moment (`mode` discriminator). Switching back to Simple Style discards the Custom SLD.

## Rendering Truth vs Editor State

GeoServer holds the *rendering truth* (the SLD actually applied). The database holds the *editor state* (what the style editor shows on next open). Editor state mirrors, never overrides, rendering truth.

## Default Style (GeoServer sense)

The style GeoServer applies to GetMap requests when none is named. Our per-Layer style is always installed as the Layer's Default Style, so existing WMS URLs keep working unchanged.
