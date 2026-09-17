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

## Layer Group

A named, ordered composition of independent Layers presented together as one map without merging their datasets. A Layer may belong to multiple groups: display order and visibility belong to each membership, while style belongs to the Layer and changes affect every group using it.
_Avoid_: Merged Layer, Project (which means a survey container).

## Batch Group Mode

A batch of datasets from one source ZIP processed together: `separate` publishes each dataset as an independent Layer; `group` additionally composes visible members into a Layer Group (named, ordered, per-member style + visibility) with combined WMS/raster/MVT URLs and legend. Group publishing is tied to `format == wms` (groupable) vs vector/raster (WMS-composite still works via layer group).

## Artifact Source & Cached Materialization

A batch may render from an Upload API artifact (`artifact://`) instead of a local file. `_resolve_source_path` downloads once per `artifact_id` into `_batch_work/artifact_{id}/` and reuses the file for every dataset in the batch. A successful cancellation or release marks the cache for cleanup only when no Layer or active Batch still references the upload session (reference-counted retention).

## Upload Lease (pin) & Retention

Upload API artifact leases have **no expiry**: holding a lease pins the artifact so `request_deletion` is blocked. The tileserver holds the lease while any Layer or active Batch references the upload session (`count_layers_referencing`, `count_batches_referencing`; terminal batches excluded). Release is idempotent and reference-counted: last consumer releases, failures flag `pending_release` on the upload session for the `reconcile_pending_release_task` to retry. Deleting the last consuming Layer also releases the lease and removes the source file/session.

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

## Geocoding (of a Feature)

Resolving an address from a Feature's coordinates (reverse) or finding Features near a place name (forward), via an external geocoder (Nominatim/OSM). Reverse targets a single Feature identified by its 0-based row index within the Layer. Forward returns the nearest Features within a radius, sorted by great-circle distance; non-point geometries are represented by a single representative point for distance and addressing.

## Overlay Analysis

Spatial operation performed on two (or one) vector layers to produce a new geometry result. Supported operations in Phase 1: Intersection, Union, Dissolve, Clip, Difference, Buffer. Each operation has geometry-type compatibility rules — incompatible operations are disabled for a given input pair. The result is an ephemeral Layer that appears on the map; the user may choose to persist it or discard it.

## Overlay Operation

A specific spatial analysis function applied to input layers. Each operation defines: required input count (1 or 2), compatible geometry types for each input, and the geometry type of the output. Operations are divided into Phase 1 (core) and Phase 2 (extended).

## Ephemeral Layer

A Layer created by overlay analysis that exists temporarily on the map. It has a GeoJSON result file on disk and a Layer record in the database, but is flagged as ephemeral in `file_metadata.analysis.ephemeral`. The user may persist it (removing the ephemeral flag) or discard it (deleting both file and record).

## Dissolve (spatial)

Merging features within a single layer into fewer or one geometry. Full dissolve merges all features into one. Group-by dissolve merges features that share the same attribute value, producing one geometry per unique value.

## Feature-pair Intersection (Perpotongan Pasangan Fitur)

The spatial overlap between one polygon feature from Layer A and one polygon feature from Layer B, associated with both source feature identities. Its measurements include overlap area and the percentage of each source feature's full area occupied by that overlap.

For polygon-area analysis, a result requires positive overlap area; contact only along an edge or at a point does not produce a result.

Different feature pairs remain independent even when their overlaps cover the same area; summing pair areas does not necessarily give unique coverage.

## Analysis Source Feature ID (ID Fitur Sumber Analisis)

An identifier linking an analysis result to a feature in its input layer. It comes from a selected unique, non-empty source field or is assigned for one analysis run with a mapping to the source record; an assigned ID does not imply stable identity across runs.

## Analysis Reference Layer (Layer Acuan Analisis)

Layer existing yang ditetapkan admin sebagai acuan untuk intersect atau query analisis terhadap objek unggahan pengguna; pengguna memilih tepat satu acuan setiap proses. Acuan memakai sumber yang sama dengan publikasi, tanpa SHP atau entri katalog tambahan, dan tidak mengubah penampilan layer sumber sesuai pengaturan publikasinya.
_Avoid_: Basemap (peta latar).

## Suitability Assessment (Penilaian Kesesuaian)

Pemeriksaan otomatis objek SHP unggahan pengguna terhadap layer acuan analisis yang dikonfigurasi admin. Dalam cakupan awal, informasi kesesuaian berarti kategori acuan yang beririsan, luas, persentase, dan atribut terkait, tanpa vonis sesuai/tidak sesuai.

## Boundary Contact (Kontak Batas)

Hubungan objek unggahan dengan batas kategori acuan, misalnya titik pada batas,
garis yang mengikuti batas, atau polygon yang hanya menyentuh zona lain.
Semua kategori yang bersentuhan ditampilkan dengan penanda “pada batas”;
kontak polygon tanpa luas dibedakan dari irisan berluas positif.

## Analysis Category (Kategori Acuan Analisis)

Nilai dari kolom acuan yang dipilih admin untuk mengelompokkan informasi
hasil irisan. Nilai kosong tetap dilaporkan sebagai “Kategori belum diisi”
dan tidak berarti objek tidak beririsan dengan acuan.

## Category Summary (Rekap Kategori)

Ringkasan hasil irisan per kategori dengan jumlah titik, panjang, dan luas
dipisahkan. Bagian yang sama dalam kategori yang sama dihitung sekali per
objek unggahan; kategori berbeda tetap independen.

## Kodefikasi Perencanaan (Planning Codebook)

Kamus tabular perencanaan yang menjadi single source of truth arti kode peta. Dikelola di `lahat_api:8090` (`planning_catalog` + `classification` + `additional_domain`/`zoning_regulation`), bukan di tileserver. Tileserver tidak menduplikasi tabelnya; hanya melakukan lookup runtime bila diperlukan.
_Avoid_: Tabel kode di tileserver, duplikasi matrix.

## Planning Catalog

Entitas katalog perencanaan di `lahat_api` (`planning_catalog.code`, `planning_level`, `document_type` RTRW/RDTR, `plan_component` PR/SR). Menjadi konteks katalog untuk resolve kode (mis. `RDTR_LAHAT_2024`).
_Avoid_: Layer code, file_metadata code.

## Classification (Kode Pola Ruang)

Baris kodefikasi untuk satu domain dalam satu katalog & komponen: `classification.domain_code` (mis. `ORDE01`, `KODKWS`, `JNSRPR`), `name` readable, `area_code`, `classification_key` unique, `parent_id` hierarki. `domain_code` adalah canonical join key untuk Get Info; `area_code`/`classification_key`/`zone_identifier` adalah atribut turunan.
_Avoid_: Raw KODE, area_code sebagai kunci.

## Kode Pola Ruang (Pola Ruang Code)

Nilai kode pada atribut fitur peta pola ruang (mis. `ORDE01` pada field `KODE`). Tidak readable tanpa join ke `classification.name`. Selalu di-resolve bersama konteks `catalog_code` + `plan_component`.
_Avoid_: Label, readable name.

## Kodefikasi Layer Config

Konfigurasi per-Layer di tileserver `Layer.file_metadata.kodefikasi` yang memetakan field sumber peta ke katalog kodefikasi: `{ code_field, catalog_code, plan_component, enrich_fields[] }`. `null` berarti layer tidak di-enrich. Dikelola admin tileserver (`tiles.manage`), bukan admin `lahat_api`.
_Avoid_: Global kodefikasi switch, hardcode field `KODE`.

## Enriched Get Info (Get Info Terperkaya)

Respons `GET /layers/{id}/features` yang telah diperkaya dengan label kodefikasi secara additive: field raw tetap (`KODE: ORDE01`) plus `KODE_label`/`KODE_description` dan metadata `_enrichment { status, catalog, resolved, unresolved }`. Gagal enrichment tidak menggagalkan Get Info — fallback ke raw dengan `status: degraded` atau `unknown_code`.
_Avoid_: Replace raw code, error 500 saat lahat_api down.

## LahatKodefikasiClient

Infrastructure adapter di tileserver yang melakukan batch resolve kode ke `lahat_api:8090` (`POST /classifications/resolve`) dengan auth berlapis JWT + OAuth2 client_credentials, timeout 800ms + 1 retry, cache in-memory TTL 60s. Di-inject sebagai `LahatKodefikasiPort` ke `QueryLayerFeaturesUseCase`.
_Avoid_: Direct DB join, frontend aggregation.

## Degraded Enrichment

Kondisi ketika `lahat_api` tidak tersedia/timeout/401 dan Get Info tetap mengembalikan raw `properties` dengan `_enrichment.status = "degraded"` (bukan error). Unknown code adalah kasus terpisah: `status = "ok"` tapi `*_label = null` + `unresolved` bertambah.
_Avoid_: Unknown code = error, degraded = 500.
