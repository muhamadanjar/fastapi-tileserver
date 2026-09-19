# Get Info Kodefikasi Enrichment — Pola Ruang (ORDE, KODKWS, JNSRPR)

Status: disepakati (grill 2026-09-18), belum diimplementasi
Design doc: ini
Progress: [../progress/getinfo-kodefikasi-enrichment.md](../progress/getinfo-kodefikasi-enrichment.md)
ADR: [0007](../adr/0007-getinfo-kodefikasi-enrichment-via-lahat-api.md)
Glossary: [../../CONTEXT.md](../../CONTEXT.md) — Kodefikasi, Kode Pola Ruang, Enriched Get Info, LahatKodefikasiClient

## 1. Masalah

`GET /layers/{id}/features` (`QueryLayerFeaturesUseCase` di `app/usecases/getinfo_layer.py:44` + adapters `app/usecases/getinfo_adapters.py:30-392`) sudah mengembalikan `properties` raw sesuai sumber (shp via GeoPandas, wms via GetFeatureInfo, wfs/esri via identify). Untuk pola ruang, field berisi kode `ORDE01`, `ORDE02`, `KODKWS`, `JNSRPR` yang tidak readable. Tabel kodefikasi yang readable ada di `lahat_api:8090` (`planning_catalog` + `classification` + `zoning_regulation` di `lahat_api/app/infrastructure/persistence/models.py:361-785`), bukan di tileserver. Tidak ada join antara kode di peta dengan tabel tersebut, sehingga Get Info tidak bisa menjelaskan artinya.

Contoh matrix (user):
```
ORDE01 → 32040000
ORDE02 → 32043000
ORDE03 → 32043000
KODKWS → 32043000
JNSRPR → 32000000
```
Setiap kode memetakan ke `area_code`/`domain_code` yang berbeda, dikelola di `lahat_api`.

## 2. Tujuan

- Get Info tetap 1 call (`GET /layers/{id}/features?lon=&lat=`) tapi mengembalikan label readable di samping raw code, tanpa merusak style/filter yang masih pakai raw code.
- Kodefikasi tetap single owner di `lahat_api` (tileserver tidak duplikasi tabel, tidak manage matrix).
- Enrichment per-layer, configurable, dengan fallback graceful kalau `lahat_api` down atau kode tidak dikenal.

Non-tujuan: replikasi DB classification ke tileserver, penilaian kesesuaian (vonis sesuai/tidak), atau pengayaan analysis-reference intersect (scope hanya Get Info).

## 3. Keputusan yang disepakati (Q1–Q6)

1. **Owner kodefikasi tetap di `lahat_api:8090`** — tileserver hanya manage sumber peta (tile/mbtiles/WMS). Alasan: matrix kompleks, sudah ada di `lahat_api`.
2. **Kunci join = `classification.domain_code` (+ konteks `planning_catalog.code` & `plan_component`)**. Contoh: `ORDE01` → `classification` dengan `domain_code=ORDE01`, `planning_catalog_id` dari `catalog_code=RDTR_LAHAT_2024`, `plan_component=PR`. `area_code`/`classification_key`/`zone_identifier` dipakai sebagai atribut turunan, bukan kunci primer.
3. **Pola integrasi A: server-side enrichment di tileserver** via `LahatKodefikasiClient` (Infrastructure adapter). Bukan frontend aggregation, bukan replikasi periodik. Alasan: semua client (geoportal/dashboard/external) otomatis dapat readable label; WMS/WFS yang tidak lewat frontend tetap ter-enrich.
4. **Konfigurasi per-layer di `Layer.file_metadata.kodefikasi`** (admin tileserver, permission `tiles.manage`):
   ```json
   {
     "code_field": "KODE",
     "catalog_code": "RDTR_LAHAT_2024",
     "plan_component": "PR",
     "enrich_fields": ["KODKWS", "JNSRPR"]
   }
   ```
   `null` = tidak di-enrich (backward compat). Admin tileserver yang atur mapping field→catalog karena dia yang tau schema shapefile/WMS.
5. **Fallback**: unknown code → raw value tetap keluar + `*_label = null` + `_enrichment.status = "unknown_code"`. `lahat_api` down/timeout → `status = "degraded"` + raw value, bukan 500.
6. **Auth berlapis**: JWT service account + OAuth2 client_credentials (coba JWT dulu, fallback ke client_credentials kalau 401, token di-cache). Endpoint `POST /classifications/resolve` di `lahat_api` butuh service auth, bukan user JWT.
7. **Cache**: in-memory LRU TTL 60s, batch lookup `codes=[...]` 1 roundtrip per Get Info, timeout 800ms + 1 retry, budget <1.5s.
8. **Bentuk enriched response**: additive (`KODE_label`, `KODE_description` + `_enrichment` metadata), tidak replace raw value.

## 4. Arsitektur

```
Browser/Geoportal
  → GET /layers/{id}/features?lon=&lat=  (tileserver)
    → QueryLayerFeaturesUseCase.execute()
      → resolve_adapter(layer).query()  → raw FeatureQueryResponse
      → if layer.file_metadata.kodefikasi:
          LahatKodefikasiClient.resolve(catalog_code, plan_component, codes)
            → POST lahat_api:8090/api/v1/classifications/resolve
              Authorization: Bearer <JWT|OAuth2 CC>
              Body: { catalog_code, plan_component, codes }
            → cache (60s) + timeout 800ms + retry 1
          → enrich additive fields
      → _apply_field_configs (existing)
    → FeatureQueryResponse enriched
```

Layering (Clean Architecture):
- `app/domain/ports.py`: `LahatKodefikasiPort` (interface `resolve(catalog_code, component, codes) -> dict`)
- `app/infrastructure/clients/lahat_kodefikasi_client.py`: `HttpLahatKodefikasiClient` (httpx, token cache, retry, timeout)
- `app/usecases/getinfo_layer.py`: inject optional `LahatKodefikasiPort`, panggil setelah `adapter.query`, sebelum `_apply_field_configs`
- `app/config`: `LAHAT_API_BASE_URL`, `LAHAT_API_JWT`, `LAHAT_API_OAUTH_*`, `LAHAT_ENRICHMENT_TTL`, `LAHAT_ENRICHMENT_TIMEOUT`
- Tidak ada perubahan `Layer` table schema (pakai JSON `file_metadata`), tidak ada migrasi SQLModel — tapi tambah validasi `kodefikasi` di schemas.

Lahat_api side:
- Endpoint baru `POST /api/v1/classifications/resolve` di `lahat_api/app/presentation/api/v1/classification.py` (atau planning_catalog), read-only, auth service (JWT/OAuth2), query `classification` join `planning_catalog` by `code`, filter `plan_component` + `domain_code IN (...)`, return `name`/`description`/`area_code`/`classification_key`.

## 5. Kontrak API

### Tileserver → lahat_api

Request:
```
POST /api/v1/classifications/resolve
Authorization: Bearer <service JWT atau OAuth2 CC>
Content-Type: application/json
{
  "catalog_code": "RDTR_LAHAT_2024",
  "plan_component": "PR",
  "codes": ["ORDE01", "KODKWS", "32040000"]
}
```
Response 200:
```json
{
  "catalog_code": "RDTR_LAHAT_2024",
  "plan_component": "PR",
  "items": [
    {"domain_code":"ORDE01","name":"Permukiman Perkotaan","description":"Zona permukiman ...","area_code":"32040000","classification_key":"RDTR_PR_ORDE01","is_active":true},
    {"domain_code":"KODKWS","name":"Kawasan Budidaya ...","area_code":"32043000"}
  ],
  "not_found": ["32040000"]
}
```

### Tileserver → frontend (enriched Get Info)

Tetap `FeatureQueryResponse` (`app/domain/schemas.py`):

```json
{
  "type": "vector",
  "count": 1,
  "features": [{
    "KODE": "ORDE01",
    "KODE_label": "Permukiman Perkotaan",
    "KODE_description": "Zona permukiman ...",
    "KODKWS": "32043000",
    "KODKWS_label": null,
    "_enrichment": {
      "status": "ok",
      "catalog": "RDTR_LAHAT_2024",
      "component": "PR",
      "resolved": 1,
      "unresolved": 1,
      "degraded": false
    }
  }],
  "_enrichment": {
    "status": "degraded",
    "reason": "lahat_api timeout"
  }
}
```
Status: `ok` | `unknown_code` (sebagian) | `degraded` (lahat_api unavailable) | `disabled` (layer tanpa kodefikasi).

### Admin tileserver

```
PATCH /layers/{id}/kodefikasi
Authorization: Bearer <user JWT dengan tiles.manage>
Body: { "code_field":"KODE", "catalog_code":"RDTR_LAHAT_2024", "plan_component":"PR", "enrich_fields":["KODKWS","JNSRPR"] }
→ validasi catalog_code exists via preflight call ke lahat_api (best-effort, warning bukan block)
```

## 6. Alur & edge cases

- `file_metadata.kodefikasi == null` → skip enrichment, response as-is (existing behaviour).
- Multi-field: `code_field` utama + `enrich_fields` tambahan, semua di-batch dalam 1 resolve call.
- Empty/null code value → skip lookup, label null.
- Unknown code → `*_label = null`, `_enrichment.status` tetap `ok` tapi `unresolved` bertambah; UI bisa tampil badge "kode tidak dikenal".
- `lahat_api` 401 → coba OAuth2 CC token, cache, retry sekali. Gagal → degraded.
- Timeout 800ms → retry 1, total 1.6s max, lalu degraded (jangan block peta).
- Cache key: `(catalog_code, plan_component, sorted(codes))`, TTL 60s, LRU 1000 entries.
- Field config filtering (`_apply_field_configs`) tetap jalan setelah enrichment — `*_label` ikut visible filter kalau `original` field visible.

## 7. Keamanan & operasional

- Service token disimpan di env, tidak di DB. JWT expiry di-cache sampai 5 menit sebelum expire.
- OAuth2 CC: `token_url`, `client_id`, `client_secret` di env, token di-cache.
- Rate limit di `lahat_api` untuk `/resolve` — service account bypass user rate limit.
- Observability: log `lahat_enrichment{layer_id, catalog, resolved, unresolved, degraded, latency_ms}` + metric counter.
- Tidak ada migrasi DB tileserver untuk fase 1; kalau butuh index, tambah validasi JSON saja.

## 8. Rencana implementasi (tracer-bullet)

1. `lahat_api`: tambah `POST /classifications/resolve` + service auth (JWT + OAuth2 CC).
2. `tileserver`: `LahatKodefikasiPort` + `HttpLahatKodefikasiClient` + config env + cache.
3. `tileserver`: modifikasi `QueryLayerFeaturesUseCase` untuk enrichment additive + degraded handling.
4. `tileserver`: admin endpoint `PATCH /layers/{id}/kodefikasi` + validasi.
5. Tests: unit `test_lahat_kodefikasi_client`, `test_getinfo_enrichment`, integration degraded/timeout/unknown.
6. Docs & ADR + update CONTEXT.md.

## 9. Kriteria verifikasi

- Get Info layer tanpa `kodefikasi` tetap return raw (no regression, existing tests pass).
- Get Info layer dengan `kodefikasi` + `lahat_api` up → `*_label` terisi, `_enrichment.status=ok`.
- Get Info dengan kode tidak dikenal → raw + label null + unresolved.
- `lahat_api` down/timeout/401 → raw + degraded, status 200 bukan 500, latency <1.5s.
- Batch: 1 call untuk N codes, cache hit tidak call lagi dalam 60s.
- Auth berlapis: JWT fail → CC succeed → tetap ok.
- Admin patch butuh `tiles.manage`, validasi field موجود.

## 10. Risiko & mitigasi

- `lahat_api` matrix kompleks (parent/children, additional_domain) — fase 1 hanya resolve `classification.domain_code`, belum `zoning_regulation` full matrix; extensible ke `additional_domain_value`.
- Staleness cache 60s — acceptable untuk Get Info interaktif; tidak untuk audit. Kalau butuh fresh, admin bisa `?no_cache=1`.
- Circular dependency env — tileserver butuh `LAHAT_API_BASE_URL` yang benar di docker-compose `extra_hosts`/`host.docker.internal`.
