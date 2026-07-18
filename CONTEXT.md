# Ubiquitous Language — tileserver_api

## Project

A survey container for capturing spatial data. Owns exactly one Form Schema (the dynamic attribute form definition) and many Features (spatial records entered against that form). Declares exactly one Geometry Type (`point` | `line` | `polygon`) at creation; every Feature in the Project must match it. A Project is not itself renderable; it may be published as a Layer to appear on the map.

## Form Schema

The dynamic attribute form definition owned by a Project. An ordered list of Fields, each with a Field Type drawn from the fixed v1 set: `text`, `textarea`, `number`, `select`, `multiselect`, `date`, `checkbox`, `file`. Select-like fields carry their options inside the schema.

The schema is mutable and unversioned. Existing Feature attribute values are never destroyed by schema edits: a removed Field's values stay stored but are no longer rendered; a new required Field is enforced only on subsequent create/edit; a removed select option stays readable but becomes invalid on re-edit.

## Feature (survey sense)

A single spatial record captured in a Project: one geometry (matching the Project's Geometry Type) plus attribute values conforming to the Project's Form Schema. Carries optional client-supplied attribution (who captured it); the service itself does not authenticate surveyors.

## Attachment

A file uploaded through a Project's `file` Field (photo, document). Owned by the Project; referenced from Feature attribute values. Deleting a Feature deletes its Attachments; deleting a Project deletes all of them. Attachments are publicly served, like tiles.

## Publishing (a Project)

Making a Project visible on the map by creating a Layer backed by the Project's live Feature data. A published Project's Layer always reflects current Features — publishing is not a snapshot. The Layer is only a projection: unpublishing (or deleting the Layer directly) removes the Layer but never touches Features; deleting the Project removes everything — Features, Attachments, and the Layer. "Published" is not a stored status; it is derived from the Layer's existence.

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

A Layer Style expressed as raw SLD XML supplied by an advanced user. Stored alongside the Simple Style in the editor state; the `mode` discriminator marks which one is active (installed in GeoServer). Saving a Simple Style regenerates the stored SLD from it (keeping both in sync and replacing any Custom SLD); saving a Custom SLD keeps the last Simple Style settings for later reuse.

## Rendering Truth vs Editor State

GeoServer holds the *rendering truth* (the SLD actually applied). The database holds the *editor state* (what the style editor shows on next open). Editor state mirrors, never overrides, rendering truth.

## Default Style (GeoServer sense)

The style GeoServer applies to GetMap requests when none is named. Our per-Layer style is always installed as the Layer's Default Style, so existing WMS URLs keep working unchanged.
