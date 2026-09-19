Related Plan: [Get Info Kodefikasi Enrichment](../plans/getinfo-kodefikasi-enrichment.md)

# Progress — Get Info Kodefikasi Enrichment

## Status

- [x] Grill Q1–Q6 selesai — shared understanding tercapai 2026-09-18
- [x] Plan ditulis (`docs/plans/getinfo-kodefikasi-enrichment.md`)
- [x] CONTEXT.md diperbarui (glossary Kodefikasi dkk.)
- [x] ADR 0007 ditulis (`docs/adr/0007-getinfo-kodefikasi-enrichment-via-lahat-api.md`)
- [x] Lahat_api: `POST /classification/resolve` + auth JWT/OAuth2 CC (`lahat_api/app/presentation/api/v1/classification.py:127`, `app/application/classification/service.py:113`, `app/infrastructure/persistence/classification_repository.py:219`)
- [x] Tileserver: `LahatKodefikasiPort` + `HttpLahatKodefikasiClient` + cache + config (`app/domain/ports.py:152`, `app/infrastructure/clients/lahat_kodefikasi_client.py:1`, `app/core/config.py:128`)
- [x] Tileserver: enrich `QueryLayerFeaturesUseCase` (additive `*_label`, `_enrichment`, degraded) (`app/usecases/getinfo_layer.py:52`)
- [x] Tileserver: admin `PATCH /layers/{id}/kodefikasi` + `GET` + `DELETE` + validasi (`app/presentation/router/api/v1/endpoints/layers.py:1024`, `app/domain/schemas.py:130`)
- [x] Tests: unit `_enrich_kodefikasi` (ok/unknown/no-cfg/no-client) + `GET /layers/{id}/features` enrichment + kodefikasi CRUD; existing `tests/test_getinfo*` 6 passed
- [x] Verifikasi manual + `graphify update .` (2978 nodes, 6569 edges)
- [x] Final docs `docs/features/getinfo-kodefikasi-enrichment.md`

## Keputusan yang dikunci

- Kodefikasi owner tetap di `lahat_api:8090` (`planning_catalog` + `classification`), tileserver tidak duplikasi tabel — Q1.
- Join key = `classification.domain_code` + `planning_catalog.code` + `plan_component` (ORDE01 dkk.) — Q2.
- Pola A: server-side enrichment di tileserver via `LahatKodefikasiClient`, cache 60s, batch, timeout 800ms+1 retry, fallback raw — Q3.
- Per-layer `file_metadata.kodefikasi` (admin tileserver), unknown code = raw + label null — Q4.
- Auth berlapis JWT + OAuth2 client_credentials, service token cache — Q5.
- Kontrak `POST /resolve` batch + additive `*_label`/`*_description` + `_enrichment` — Q6.

## Grill log ringkas

- Q1: dimana tabel kodefikasi? → `lahat_api`, tileserver hanya map store.
- Q2: field sumber vs kolom kunci? → `domain_code` + catalog/component, per-layer `code_field`.
- Q3: pola integrasi? → A server-side enrich + cache + degraded fallback, additive field.
- Q4: konfigurasi per-layer & fallback? → `file_metadata.kodefikasi`, as-is raw, admin tileserver.
- Q5: auth & ketahanan? → berlapis JWT + OAuth2 CC, 800ms/1 retry, degraded bukan 500.
- Q6: kontrak API? → `POST /resolve` batch + `*_label` + `_enrichment`, scope Get Info saja.

## Catatan implementasi

- Tidak ada migrasi DB tileserver fase 1 (pakai JSON `file_metadata`).
- Lahat_api endpoint baru harus read-only, service auth, tidak butuh permission user.
- Observability: log latency + degraded counter.
- Next: mulai dari `lahat_api` resolve endpoint, lalu client di tileserver.

## Verifikasi yang akan dilakukan

- `test_getinfo_enrichment`: ok, unknown_code, degraded (lahat down/timeout/401→CC fallback).
- Manual `GET /layers/{id}/features` dengan/without kodefikasi, cache hit, latency <1.5s.
- `graphify update .` setelah code change.

Tidak ada klaim kapasitas atau benchmark sebelum pengujian dengan data real ORDE/KODKWS.
