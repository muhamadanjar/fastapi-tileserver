---
status: accepted
---

# Get Info kodefikasi via lahat_api (server-side enrichment)

Get Info pola ruang mengembalikan kode mentah (`ORDE01`, `KODKWS`, `JNSRPR` di `app/usecases/getinfo_layer.py:44` + `getinfo_adapters.py:30-392`) yang tidak readable. Tabel arti kode ada di `lahat_api:8090` (`planning_catalog` + `classification` di `lahat_api/app/infrastructure/persistence/models.py:361-435`) sebagai matrix kompleks; tileserver hanya manage sumber peta (tile/mbtiles/WMS/WFS) dan tidak boleh menduplikasi tabel tersebut.

Keputusan: enrichment dilakukan **server-side di tileserver** via `LahatKodefikasiClient` (Infrastructure adapter, `LahatKodefikasiPort` di Domain) yang batch-resolve `domain_code` ke `lahat_api` (`POST /classifications/resolve`, auth berlapis JWT + OAuth2 client_credentials, timeout 800ms + 1 retry, cache TTL 60s). Konfigurasi per-layer disimpan di `Layer.file_metadata.kodefikasi` (`{code_field, catalog_code, plan_component, enrich_fields[]}`) dan dikelola admin tileserver (`tiles.manage`); `null` = tidak di-enrich. Respons diperkaya secara additive (`KODE_label`, `KODE_description`, `_enrichment {status, catalog, resolved, unresolved}`) tanpa replace raw value. `unknown_code` → label null; `lahat_api` down/timeout/401 → `degraded` fallback ke raw (bukan 500).

Alternatif yang ditolak: (a) frontend aggregation — duplikasi logic di semua client dan tidak cover WMS/WFS; (b) replikasi DB classification ke tileserver — staleness & kompleksitas sync; (c) hardcode global field — tiap layer punya field berbeda.

Konsekuensi: `lahat_api` perlu endpoint read-only `POST /classifications/resolve` dengan service auth; tileserver butuh env `LAHAT_API_BASE_URL`/`JWT`/`OAUTH_*` + cache + observability (latency/degraded counter). Tidak ada migrasi DB tileserver fase 1; validasi hanya di `file_metadata` JSON.

Plan: [../plans/getinfo-kodefikasi-enrichment.md](../plans/getinfo-kodefikasi-enrichment.md)
Progress: [../progress/getinfo-kodefikasi-enrichment.md](../progress/getinfo-kodefikasi-enrichment.md)
