# Plan: SLD Style Verification & Duplicate Publish Guard

## Problem

Peta mode `sld` tampak abu-abu walaupun SLD berisi fill berwarna. Investigasi
menunjukkan **proses simpan style sudah benar** (sudah terbukti berjalan untuk
beberapa layer WMS), dan akar masalahnya bukan versi GeoServer (3.0.0 menerima
SLD 1.0.0 hasil normalisasi dengan baik).

Akar masalah yang ditemukan:

1. **Duplikat publish**: file yang sama (mis. `RENCANA_POLA_RUANG_2026_AR.zip`)
   bisa ter-publish sebagai beberapa record layer, sebagian `wms` (bisa di-style)
   dan sebagian `tile` (jalur render PNG lokal, tidak bisa di-style). UI tidak
   menampilkan mana yang WMS/target, jadi pengguna tidak sadar style menempel ke
   record yang keliru.
2. **Tidak ada verifikasi pasca-simpan**: setelah `set_default_style`, tidak ada
   konfirmasi bahwa default style layer sudah benar-benar terpasang.

## Goal

- Cegah terulangnya duplikasi layer WMS saat publish.
- Setelah simpan style, verifikasi default style benar-benar aktif di GeoServer.
- UI panel editor menampilkan layer target GeoServer + hasil verifikasi, sehingga
  pengguna tahu style akan/sudah diterapkan ke mana.

## Scope (non-goals)

- Tidak mengubah pipline simpan yang sudah benar (`upsert_style` + `set_default_style`).
- Tidak menambah validasi struktural SLD baru pada request (di luar yang sudah ada).
- Tidak memigrasi data/records yang sudah ter-duplikat (opsional, di luar scope ini).

## Approach

### 1. Duplicate publish guard (backend)

Di `publish_to_geoserver` (`app/api/v1/endpoints/upload.py`), sebelum enqueue
worker, hitung `layer_name = workspace:slugify(filename)`. Query layer `wms` yang
sudah punya `geoserver.layer_name` sama. Jika ada → tolak dengan `409` + pesan yang
menyebut layer target dan bahwa file ini sudah pernah di-publish sebagai WMS.

- Lokasi: setelah validasi file/status, sebelum `task.delay`.
- Butuh query helper di `LayerRepository` (mis. `find_by_geoserver_layer_name`).

### 2. Style verification pasca-simpan (backend)

Di `put_layer_style` (`app/api/v1/endpoints/layers.py`), setelah
`set_default_style`, baca `rest/layers/{layer_name}.json` dari GeoServer dan
bandingkan `defaultStyle.name` dengan `workspace:layer_<id>`.

- Tambah method `GeoServerService.get_default_style(layer_name) -> str | None`.
- Response `put_layer_style` menambahkan field `style_verified: bool` dan
  `default_style_name: str | None`.

### 3. Frontend feedback (dashboard)

Di `wms-style-panel.tsx`:
- Tampilkan layer target GeoServer (dari `file_metadata.geoserver.layer_name`)
  dan flag bahwa layer adalah WMS (bisa di-style).
- Banner hasil simpan: "✔ Style aktif pada {layer}" vs "⚠ Style belum terpasang
  sebagai default di {layer}".
- Tipe `LayerResponse`/request response diperluas dengan field verifikasi.

## Files touched

- `services/tileserver_api/app/api/v1/endpoints/upload.py` (guard)
- `services/tileserver_api/app/api/v1/endpoints/layers.py` (verifikasi + response)
- `services/tileserver_api/app/infrastructure/services/geoserver_service.py` (get_default_style)
- `services/tileserver_api/app/infrastructure/repositories/layers.py` (find_by_geoserver_layer_name)
- `services/dashboard/features/geo/tile/types.ts`
- `services/dashboard/features/geo/tile/api.ts`
- `services/dashboard/features/geo/tile/components/wms-style-panel.tsx`

Related progress: [../progress/sld-style-verification-and-duplicate-guard.md](../progress/sld-style-verification-and-duplicate-guard.md)
