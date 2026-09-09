# ADR-0004: Vector Overlay Analysis — Ephemeral Layer Pattern

## Status

Accepted

## Context

The system needs vector overlay analysis (intersection, union, dissolve, clip,
difference, buffer) to let users combine and manipulate spatial layers. The
result must be viewable on the map immediately, but should not permanently
consume database and storage resources unless the user explicitly saves it.

There are two plausible approaches:

1. **Persistent-only**: Every analysis result is immediately saved as a full
   Layer with file and DB record. User must delete unwanted results manually.
2. **Ephemeral-first**: Analysis results are created as temporary (ephemeral)
   Layers that display on the map. The user chooses to persist or discard.
   Discarded results are cleaned up automatically.

## Decision

We adopt **ephemeral-first** for overlay analysis results.

- Result is created as a Layer record + GeoJSON file, flagged as ephemeral in
  `file_metadata.analysis.ephemeral = true`.
- User views result on map immediately.
- User may call `POST /analysis/{id}/save` to persist (remove ephemeral flag)
  or `DELETE /analysis/{id}` to discard (remove file + record).
- Execution is synchronous (MVP). Future enhancement: async via Celery for
  large datasets.

## Consequences

- **Pros**: No storage/DB bloat from exploratory analysis; user has full
  control over persistence; simpler mental model (analyze first, save if useful).
- **Cons**: Ephemeral results may be lost if server restarts before user saves;
  requires cleanup logic for abandoned ephemeral layers.
- **Mitigation**: Periodic cleanup task (future) to remove ephemeral layers
  older than a configurable TTL.

## Alternatives considered

- Persistent-only (status quo for uploads): rejected because analysis is often
  exploratory — users run multiple analyses and keep only the useful ones.
- In-memory only (no DB record): rejected because result needs a layer_id for
  map display and API interaction.
