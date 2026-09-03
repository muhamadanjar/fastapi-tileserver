# Progress: SLD Style Verification & Duplicate Publish Guard

Related Plan: [../plans/sld-style-verification-and-duplicate-guard.md](../plans/sld-style-verification-and-duplicate-guard.md)

## Status

Implementasi selesai; menunggu uji ulang save dari dashboard.

## Investigasi (selesai)

- SLD terpasang benar di GeoServer 3.0.0 (semua rule + filter NAMOBJ utuh).
- Pipeline simpan (`upsert_style` + `set_default_style`) terbukti benar.
- Akar masalah utama peta abu-abu **ditemukan**: SLD 1.1.0 (`se:SvgParameter`)
  yang di-upload GeoServer disimpan-ulang sebagai 1.0.0 **tanpa warna sama sekali**
  (DB punya 21 warna, style tersimpan 0 CssParameter, semua `<sld:Fill/>` kosong).
  Verify: kirim SLD hasil konversi 1.0.0 → 21 hex terpelihara; WMS GetMap dari
  abu-abu `#808080` menjadi berwarna (contoh `#325f28` dari SLD user).
- Masalah sekunder: duplikat publish (file sama → record `wms` + `tile`), dan
  tanpa verifikasi / feedback UI bahwa style terpasang pada layer target.

## Tasks

- [x] Tulis plan & progress (ini)
- [x] Backend: `GeoServerService.get_default_style`
- [x] Backend: verifikasi default style di `put_layer_style` + field response
- [x] Backend: duplicate publish guard di `publish_to_geoserver`
- [x] Repository: `find_geoserver_layer_name`
- [x] Backend: konversi SLD 1.1.0 → 1.0.0 sebelum upload (`convert_sld_11_to_10`)
- [x] Frontend: tampilkan layer target + banner verifikasi
- [x] Runnable check: `scripts/selfcheck_style_verify.py` (6 checks pass)
- [ ] Docs fitur final (`docs/features/...`)
- [ ] Uji ulang save dari dashboard (user)

## Decisions

- Verifikasi memakai GET `rest/layers/{layer}.json` → banding `defaultStyle.name`
  — murah, cukup menangkap kasus "style belum jadi default".
- Guard duplikat: tolak publish WMS kedua untuk filename yang sama dengan 409.
- Fix warna di sisi klien: konversi SLD 1.1.0 → 1.0.0 (`se:SvgParameter` →
  `sld:CssParameter`) sebelum upload; GeoServer 3.0.0 tidak bisa dipaksa
  menyimpan 1.1.0 dengan warna utuh.

## Log

- 2025-xx: Root cause peta abu-abu ditemukan = SLD 1.1.0 kehilangan warna saat
  disimpan GeoServer. Konversi 1.0.0 terbukti (style uji + layer riil re-PUT,
  WMS berwarna). `get_default_style` memperbaiki paren yang salah; selfcheck
  bertambah jadi 6 assertion.