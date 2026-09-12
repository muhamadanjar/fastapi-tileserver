# Geospatial Analysis Enhancements — Discovery

Progress: [Discovery progress](../progress/geospatial-analysis-enhancements.md)

Status: Backend implemented; final verification recorded in progress.

Feature documentation: [Polygon intersection area metrics](../features/geospatial-analysis-enhancements.md)

## Objective

Identify missing or improvable WebGIS analysis capabilities based on existing
endpoints and the user's actual decision workflow.

## Scope correction (2026-09-10 — takes precedence)

The user clarified that the objective is general analysis of two spatial
datasets. Village boundaries, flood layers, facilities, village codes, and
event dates are not required inputs for that general capability. The interview
over-specialized an illustrative scenario. Earlier confirmations below apply
only to that example and must not be treated as the general feature contract.

Inputs are generic Layer A and Layer B; compatible geometry types and required
attributes depend on the operation. Generic enhancement candidates include
intersection measurements, spatial aggregation, nearest-feature distances,
and improvements to existing operations. The selected first enhancement is
polygon intersection with per-pair area measurements, specified below.

## Verified baseline (2026-09-09)

- Existing analysis supports intersection, union, dissolve, clip, difference,
  buffer, symmetric difference, simplify, spatial join, and centroid.
- Results support temporary layers, save/discard, export, and explicit async runs.
- `app/analysis/overlay_operations.py`: dissolve uses `aggfunc="first"`;
  spatial join uses a left join without aggregation; simplify tolerance uses
  input geometry units; centroid directly uses the input geometry's centroid.
- `app/domain/schemas.py:AnalysisRequest` exposes no summary aggregation settings.
- `app/api/v1/endpoints/analysis.py:run_overlay_analysis` chooses async only
  when requested. Existing progress documentation claims a >=100k trigger,
  while feature documentation describes that threshold as future functionality.

Evidence is a static inspection of this backend checkout, not runtime or
frontend verification.

## Candidate directions — proposals, not decisions

1. Summarize within: counts, numeric statistics, affected area and percentage
   per input polygon feature; extend spatial join and dissolve aggregation.
2. Proximity: nearest feature with distance and maximum search radius.
3. Existing operation quality: explicit distance/tolerance units, CRS handling,
   geometry quality reporting, and validation of group-by fields.
4. Execution usability: automatic async criteria, progress/cancellation,
   input filtering by selected features or area of interest, repeatable runs.
5. Larger domains only after use-case confirmation: raster zonal statistics,
   terrain analysis, network accessibility, suitability analysis.

GeoPandas supports configurable dissolve aggregation:
[official API](https://docs.geopandas.org/en/stable/docs/reference/api/geopandas.GeoDataFrame.dissolve.html).

## Archived example discussion: flood impact per village

Confirmed while discussing this example, superseded as general requirements
by the scope correction above:

- Focus: impact summaries per administrative area, reporting affected hectares,
  percentage of area, and affected object counts.
- First scenario: flood impact per village, using village boundary polygons,
  inundation polygons, and facility points.

- A facility point inside or on the boundary of the inundation area counts
  as affected, once even when inundation polygons overlap. This represents
  spatial exposure, not verified damage or operational disruption.

- For a facility on a shared village boundary, use its village code when it
  matches one of the candidate villages. If absent or inconsistent, classify
  it as "desa belum pasti": count it once in the overall exposed total and
  exclude it from individual village counts until resolved.

- Affected area is the part of each village covered by at least one inundation
  polygon, with overlapping inundation counted once. Report hectares and
  percentage relative to the full area of that village.

- Version one: each run represents one flood event or observation time, using
  the corresponding inundation layer. Different dates are not implicitly
  combined into a cumulative analysis. How this scope is selected and validated
  remains to be specified.

- Output: thematic map per village and a table with CSV export. Columns:
  village code/name, total hectares, affected hectares, affected percentage,
  and affected facility count. Show the overall affected facility total and
  uncertain-village count separately.

- Village boundaries and inundation polygons are required; facility data is
  optional. Without facility input, facility metrics are unavailable
  ("tidak dihitung"), not zero. Exact API/CSV representation remains to be specified.

- When facility data is supplied, the user selects a facility ID field.
  Repeated IDs with consistent locations and village attribution count once;
  conflicting records for the same ID require correction before facility
  counting. Distinct IDs at the same coordinates remain distinct facilities.

Unanswered example question (no longer the active decision): villages with no exposure. Recommendation for
discussion: include every village in the selected analysis scope, including
zero affected hectares and zero affected percentage. Facility counts are zero
only when supplied facility data yields no exposed facilities; without facility
input they remain "tidak dihitung". This is not yet agreed.

## Active generic feature — confirmed

- Prioritize polygon intersection enhancement for generic Layer A and Layer B.
- Each feature-pair result identifies its source feature in A and in B and
  reports intersection area plus percentages of each original input feature's
  full area. Output field names remain to be specified.
- Example: A = 100 ha, B = 40 ha, intersection = 20 ha; result percentages
  are 20% of A and 50% of B.

- Retain each A–B pair independently, even where their intersection geometries
  overlap; do not merge pairs automatically. Pair areas are not a unique
  coverage total and must not be presented as one. Unique coverage would
  require a separate aggregation.

- This polygon-area enhancement returns only pairs with positive intersection
  area. Polygons touching only along an edge or at a point produce no result
  row; if no pair has positive area, the result is empty.

- Provide square meters and hectares together, with percentages on a 0–100
  scale. Preserve calculation precision and round only for presentation.
  Measurement method and output field names remain to be specified.

- Allow selection of a non-null unique ID field on each input. When no suitable
  ID field exists, generate identifiers scoped to the input snapshot of this
  run and retain their source-record mapping. Generated identifiers do not
  promise stable identity across later runs or changed input.

- Preflight identifies invalid polygons by source ID and reason and blocks
  this analysis until inputs are corrected. Do not silently repair or omit
  invalid polygons when computing areas and percentages. This requirement
  concerns the polygon-area enhancement, not every existing operation.

- Add an optional area-and-percentage calculation setting to the existing
  intersection operation, available for polygon–polygon inputs. Existing
  callers retain their current behavior when the option is disabled; the
  confirmed enhanced rules apply when enabled.

## Approved implementation scope

Implement the agreed enhancement in this backend's existing analysis flow,
including request validation, operation metadata, result attributes, sync/async
behavior, regression tests, and API feature documentation. This does not
implicitly authorize changes to a separate frontend repository.

Acceptance checks derived from the confirmed behavior:

1. A 20 ha intersection between 100 ha A and 40 ha B reports 200000 m²,
   20 ha, 20% of A, and 50% of B, with the correct source identities.
2. Different intersecting pairs remain separate even when their overlap areas
   themselves overlap. No unique-coverage total is inferred from their sum.
3. Edge-only/point-only contact and disjoint polygons produce no area rows.
4. Invalid polygons are reported by source ID and reason before execution;
   they are not silently repaired or dropped by the enhanced operation.
5. Selected IDs are unique and non-null; absent ID fields can use generated
   run-scoped IDs with source mappings.
6. Disabling the option preserves existing intersection behavior.

Technical details are resolved in the implementation contract below and the
linked feature documentation.

## Implementation contract (2026-09-12)

- Request: `calculate_area=false` by default; optional `source_id_field_a` and
  `source_id_field_b` apply only with enhanced intersection.
- Result fields (also fit Shapefile's 10-character field limit): `src_a_id`,
  `src_b_id`, `src_a_row`, `src_b_row`, `area_m2`, `area_ha`, `pct_a`, `pct_b`.
  Source row positions are zero-based within the execution input snapshot.
- Preserve selected source attributes under `a_` / `b_` prefixes, avoiding
  collisions with computed fields. IDs and metrics are always included.
- Use EPSG:6933 equal-area coordinates for both intersection and all area
  denominators; publish result geometry in EPSG:4326. Reject missing CRS,
  invalid/null/empty/zero-area geometries, non-polygon features, and coordinates
  outside the projection's supported domain (86°S–86°N or unsplit dateline
  crossings), with actionable errors instead of guessing or repairing.
- Persist source snapshots beside the result for generated-ID traceability;
  expose a sources download. Use existing layer metadata and file storage;
  no database-field additions or migrations are needed.
- Sync and workers share the same enhanced execution and validation. Async
  geometry validation occurs in the worker against inputs loaded at execution.
- Projection reference: [NSIDC EASE grids](https://nsidc.org/data/user-resources/help-center/guide-ease-grids).

## Documentation policy for this session

Record agreed domain terms in CONTEXT.md when resolved. Create an ADR only
for an agreed decision with meaningful trade-offs and reversal cost. Example-only
flood terms were removed from the project glossary following the scope correction;
their meanings remain archived above. No architectural decision has been made.
