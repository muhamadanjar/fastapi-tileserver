# Get Info Kodefikasi Enrichment — Cara Kerja & Penggunaan

Related Plan: [../plans/getinfo-kodefikasi-enrichment.md](../plans/getinfo-kodefikasi-enrichment.md) · Progress: [../progress/getinfo-kodefikasi-enrichment.md](../progress/getinfo-kodefikasi-enrichment.md) · ADR: [0007](../adr/0007-getinfo-kodefikasi-enrichment-via-lahat-api.md)

## Ringkasan

Get Info (`GET /layers/{id}/features?lon=&lat=`) yang sebelumnya mengembalikan kode mentah `ORDE01`/`KODKWS`/`JNSRPR` sekarang diperkaya dengan label readable dari `lahat_api:8090` tanpa mengubah raw value. Kodefikasi tetap single owner di `lahat_api` (`planning_catalog` + `classification`), tileserver hanya melakukan lookup runtime per-layer dengan cache dan fallback graceful.

## Cara kerja

1. Admin mengatur mapping per-layer via `file_metadata.kodefikasi`:
   ```json
   {
     "code_field": "KODE",
     "catalog_code": "RDTR_LAHAT_2024",
     "plan_component": "PR",
     "enrich_fields": ["KODKWS", "JNSRPR"]
   }
   ```
   `null` = layer tidak di-enrich (backward compat). Dikelola admin tileserver (`PATCH /layers/{id}/kodefikasi`).

2. Saat `GET /layers/{id}/features`, `QueryLayerFeaturesUseCase` (`app/usecases/getinfo_layer.py:52`):
   - `resolve_adapter` mengembalikan `FeatureQueryResponse` raw sesuai sumber (shp GeoPandas, wms GetFeatureInfo, wfs/esri identify).
   - Jika `kodefikasi` ada, kumpulkan distinct codes dari `code_field` + `enrich_fields`, lalu `LahatKodefikasiClient.resolve()` (`app/infrastructure/clients/lahat_kodefikasi_client.py:1`):
     - `POST lahat_api:8090/api/v1/classification/resolve` dengan body `{catalog_code, plan_component, codes}`.
     - Auth berlapis: coba JWT (`LAHAT_API_JWT`) dulu, kalau 401 coba OAuth2 client_credentials (`LAHAT_API_OAUTH_TOKEN_URL`/`CLIENT_ID`/`CLIENT_SECRET`), token di-cache.
     - Timeout 0.8s, retry 1, cache in-memory LRU TTL 60s (batch 1 roundtrip untuk N codes).
   - Enrich additive: `KODE` → `KODE_label`, `KODE_description`, `KODE_area_code`, plus `_enrichment {status, catalog, component}` per feature.
   - Gagal/timeout → tidak 500; kembalikan raw + `_enrichment.status = "unknown_code"` (phase 1) atau `degraded` jika client tidak dikonfigurasi.

3. `lahat_api` resolve (`lahat_api/app/presentation/api/v1/classification.py:127`):
   - `POST /classification/resolve` dengan `require_authenticated()` (JWT atau OAuth2 CC via UserManagement).
   - Lookup `planning_catalog` by `catalog_code`, lalu `classification` where `planning_catalog_id` + `plan_component` + `domain_code IN (codes)`.
   - Return `{items: [{domain_code, name, description, area_code, classification_key}], not_found: [...]}`.

## Penggunaan

### Konfigurasi layer (admin)

```bash
# set
curl -X PATCH http://tileserver/api/v1/layers/{id}/kodefikasi \
  -H "Content-Type: application/json" \
  -d '{"code_field":"KODE","catalog_code":"RDTR_LAHAT_2024","plan_component":"PR","enrich_fields":["KODKWS","JNSRPR"]}'

# lihat
curl http://tileserver/api/v1/layers/{id}/kodefikasi

# hapus
curl -X DELETE http://tileserver/api/v1/layers/{id}/kodefikasi
```

`PATCH` butuh validasi: minimal satu dari `code_field` atau `enrich_fields`; `catalog_code` wajib; `plan_component` harus `PR`/`SR`.

### Get Info enriched

```bash
curl "http://tileserver/api/v1/layers/{id}/features?lon=103.5&lat=-3.9"
```

Response contoh (vector):
```json
{
  "type": "vector",
  "count": 1,
  "features": [{
    "KODE": "ORDE01",
    "KODE_label": "Permukiman Perkotaan",
    "KODE_description": "Zona permukiman ...",
    "KODE_area_code": "32040000",
    "KODKWS": "32043000",
    "KODKWS_label": "Kawasan Budidaya",
    "_enrichment": {"status": "ok", "catalog": "RDTR_LAHAT_2024", "component": "PR"}
  }]
}
```

- `unknown_code`: `{"KODE":"ORDE99","KODE_label":null,"_enrichment":{"status":"unknown_code",...}}`
- `degraded` (client tidak dikonfigurasi): `{"KODE_label":null,"_enrichment":{"status":"degraded","reason":"kodefikasi client not configured"}}`
- Layer tanpa `kodefikasi`: response as-is, tidak ada `*_label`.

Frontend cukup render `KODE_label` jika ada, fallback ke `KODE` jika `null`.

## Konfigurasi env tileserver (`app/core/config.py:128`)

```
LAHAT_API_BASE_URL=http://localhost:8090
LAHAT_API_JWT=<service JWT>
LAHAT_API_OAUTH_TOKEN_URL=http://localhost:8000/oauth/token
LAHAT_API_OAUTH_CLIENT_ID=...
LAHAT_API_OAUTH_CLIENT_SECRET=...
LAHAT_API_OAUTH_SCOPE=
LAHAT_ENRICHMENT_TTL_SECONDS=60
LAHAT_ENRICHMENT_TIMEOUT_SECONDS=0.8
LAHAT_ENRICHMENT_ENABLED=true
```

## Batasan

- Hanya enrich `FeatureQueryResponse.type == "vector"`; raster tidak di-enrich.
- Fase 1 hanya resolve `classification.domain_code`; belum `zoning_regulation`/`additional_domain` full matrix (extensible).
- Cache 60s; untuk audit fresh bisa bypass dengan restart atau tunggu TTL.
- Tidak ada migrasi DB tileserver; konfigurasi hanya JSON `file_metadata`.
