# 0001 — Per-layer SLD, no shared GeoServer styles

Date: 2026-07-10
Status: accepted

## Context

GeoServer natively supports shared (workspace- or global-level) styles that many layers can reference. We are adding style editing for WMS layers published to GeoServer from this service. The dashboard needs a per-layer style editor where each layer's symbology can diverge freely.

## Decision

Every GeoServer-published layer owns exactly one SLD style, named after its `layer_id` (`layer_{layer_id}`), created in our workspace and set as that layer's default style. Shared/general styles are deliberately not used, even though GeoServer offers them.

Style state is dual-mode: geometry-keyed Simple Style JSON (backend generates SLD 1.0.0) or raw Custom SLD, discriminated by `mode` in `file_metadata.style`. GeoServer is the rendering truth; the DB field is editor state only.

## Consequences

- Editing one layer's style can never affect another layer — no accidental coupling through a shared style.
- Style count in GeoServer grows linearly with published layers.
- Layer deletion does not clean up GeoServer styles (or the store/layer — pre-existing behaviour); orphaned styles accumulate. Accepted as debt.
- Reuse of a style across layers, if ever wanted, requires copying JSON between layers, not referencing.
