# Multi-SHP ZIP: Batch Layer dan Layer Group

Related Plan: [Multi-SHP ZIP: batch layer dan group peta](../plans/multi-shapefile-layer-groups.md)
Related Progress: [Progress implementasi](../progress/multi-shapefile-layer-groups.md)
Related ADR: [Layer Group mengomposisikan Layer mandiri](../adr/0005-layer-groups-compose-independent-layers.md)

## Ringkasan

Satu ZIP berisi beberapa dataset SHP dapat diperiksa, dikonfigurasi, dan diproses sekaligus. Hasilnya berupa:

- **Mode standalone**: satu Layer mandiri per dataset SHP.
- **Mode group**: satu Layer mandiri per dataset, ditambah Layer Group yang mengomposisikan anggota menjadi satu peta.

Keluaran versi pertama: **raster tile**, **vector tile (MVT)**, dan **WMS**, berlaku untuk kedua mode. Satu format berlaku untuk seluruh dataset dalam ZIP (format campuran per anggota di luar cakupan).

Arsitektur mengikuti clean architecture:

- **Domain** — `app/domain/map_batches.py`: protokol `Catalog`/`Store`/`MapRenderer` dan dataclass `Batch`, `Dataset`, `Group`, `Member`, `LayerData`.
- **Application** — `app/application/map_batches.py`: `MapBatches` use case (inspect, configure, process, retry, cancel, group CRUD, deletion guard).
- **Infrastructure** — `app/infrastructure/db/catalog.py` (persistence SQLModel), `app/infrastructure/services/map_renderer.py` (GeoServer/tiling).
- **Presentation** — `app/api/v1/endpoints/batches.py`.

## Alur kerja

```
Upload ZIP (Upload API / upload session)
  → POST /batches/inspect          (pemeriksaan isi ZIP, validasi per dataset)
  → POST /batches/{id}/configure   (konfigurasi + mulai proses: mode, format, kode, style, group)
  → GET  /batches/{id}             (status batch, progress per dataset)
  → GET  /batches/groups           (daftar group)
  → GET  /groups/{group_id}/legend (legenda terstruktur per anggota)
```

### Pemeriksaan (`inspect`)

- Mengekstrak ZIP dari path sumber upload, mengelompokkan file `.shp` beserta sidecar (`.dbf`, `.shx`, `.prj`) berdasarkan basename.
- Validasi per dataset: dataset dengan sidecar lengkap ditandai `valid=true`; dataset tanpa sidecar ditandai tidak valid dengan alasan, tetapi **tidak menghalangi** dataset lain yang valid.
- Metadata diambil dari SHP via `pyogrio.read_info`: geometri (normalisasi ke `Polygon`/`LineString`/`Point`), jumlah fitur, dan bounding box.
- Kerusakan/keamanan arsip tingkat ZIP menolak seluruh pemeriksaan, termasuk traversal path, nama duplikat, jumlah file berlebih, dan ukuran hasil ekstraksi berlebih.
- Dataset tidak valid tidak dapat dipilih pada konfigurasi.

### Konfigurasi & proses (`configure` → `process`)

- Pilihan: `mode` = `group` | `standalone`, `output_format` = `raster` | `mvt` | `wms`, `max_zoom`, nama, kode otomatis yang dapat disesuaikan.
- Kode group dibuat dari nama ZIP (`slug-xxxxxx`); kode layer dari nama SHP. Bentrok diberi akhiran unik. Kode stabil saat retry dan setelah publikasi.
- Mode group: `datasets` berisi id dataset pilihan + urutan tampil + visibility awal.
- Setiap dataset mendapat style awal otomatis sesuai geometri (hex color, format konsisten dengan editor style dashboard).
- Proses berjalan sebagai task background (`run_batch_task` di `app/workers/tasks.py`) dengan progress per dataset.
- Hasil layer disimpan sebagai `Layer` mandiri (tile baik raster/MVT via `TilingService`, atau publikasi WMS via GeoServer).
- Setelah seluruh anggota pilihan berhasil: group dipublikasikan otomatis (`published`). Group tanpa anggota tetap `draft`.
- Gagal sebagian: anggota berhasil tetap disimpan; `retry` hanya memproses anggota yang gagal.
- Bila publikasi group gagal setelah semua anggota selesai, group dan batch menjadi `failed`; retry mengulang publikasi tanpa membangun ulang anggota yang sudah berhasil.

### Keluaran group

**WMS** — satu layer group di GeoServer dengan mode `SINGLE` (menggabungkan seluruh anggota terlihat dalam satu gambar), nama group = kode group. Anggota tetap dapat diakses sendiri.

**Raster** — endpoint tile group `GET /tiles/_group/{group_code}/{z}/{x}/{y}.png` menyajikan gabungan gambar anggota terlihat mengikuti urutan/style. Data dan URL anggota tetap terpisah.

**MVT** — `GET /tiles/_group/{group_code}/{z}/{x}/{y}.pbf` menyatukan tile anggota dan mempertahankan setiap `source-layer` dengan ID Layer asal. Style Mapbox valid tersedia di `GET /tiles/_group_styles/{group_code}/style.json`; style ini diturunkan dari style, urutan, dan visibility anggota. Style group bukan salinan yang diedit terpisah — dihapus bersama group, tidak memengaruhi style Layer anggota.

**Legenda** — `GET /batches/groups/{group_id}/legend` mengembalikan struktur:

```json
[
  {
    "layer_id": "…", "layer_name": "…", "visible": true, "sort_order": 0,
    "symbols": [{"geometry": "Polygon", "label": "Polygon layer",
                 "fillColor": "#3388ff", "strokeColor": "#3388ff",
                 "strokeWidth": 1, "opacity": 0.5}]
  }
]
```

Satu simbol per tipe geometri pada style anggota yang terlihat; anggota tersembunyi tidak tercantum.

### Manajemen group & lifecycle

| Operasi | Endpoint |
|---|---|
| Daftar group | `GET /batches/groups` |
| Ambil group | `GET /batches/groups/{group_id}` |
| Update anggota/urutan/visibility/nama | `PATCH /batches/{group_id}/group` |
| Hapus group | `DELETE /batches/{group_id}/group` |
| Legenda | `GET /batches/groups/{group_id}/legend` |
| Group pemakai layer | `GET /groups/layer/{layer_id}/usage` |

- Satu Layer boleh menjadi anggota beberapa group; style milik Layer sehingga perubahan style memengaruhi seluruh group pemakai.
- Update group menaikkan `revision`; konflik (revision tidak cocok) ditolak 409 — klien harus reload dulu.
- Menghapus group hanya menghapus susunan peta + akses kode/URL group; layer anggota tetap tersedia mandiri (data, style, URL). Tidak menghapus layer secara berantai.
- Penghapusan **layer** yang dipakai group ditolak (`deletion_guard`, 409) dengan daftar group pemakai; pengguna harus mengeluarkan layer dari seluruh group dulu.
- Format anggota harus sama dengan format group (`_publish` memvalidasi).

## Skema database

Tambahan Alembic `0009_add_batch_group_tables.py`:

- `batches` — batch pemeriksaan/proses (upload_id, mode, output_format, max_zoom, status, task_token, group_id, error).
- `datasets` — item dataset per batch (path di ZIP, nama, geometri, feature_count, bbox, valid, error, status, progress, layer_id, style). ID dataset dan `layer_id` UUID5 deterministik dibuat dari batch + path dalam arsip.
- `layer_groups` — group (code, name, status: draft/published/failed, revision).
- `layer_group_members` — keanggotaan (group_id, layer_id, visible, sorting).
- `code_reservations` — reservasi kode untuk mencegah bentrok saat proses bersamaan.

Catatan: FK `datasets.layer_id → layers.id` dan `layer_group_members.layer_id → layers.id` **tidak** ada — layer row baru dibuat setelah proses, sedangkan id sudah ditentukan (UUID5) saat pemeriksaan. Integritas dijaga di lapisan aplikasi melalui `deletion_guard`. (ADR-internal trade-off, lihat plan/progress.)

## Batasan & keputusan versi pertama

- Satu format output untuk seluruh ZIP (bukan campuran per anggota).
- Artifact source dari Upload API dimaterialisasi sekali per artifact dan dipakai ulang oleh seluruh dataset batch selama lease masih aktif.
- Restore/publish ulang group yang dihapus tidak tersedia; tambah anggota ke group yang terbit akan me-republish (revision bump).
- Versi publik lama tetap tersedia selama pembangunan versi baru adalah perilaku target; pergantian versi atomik belum diimplementasikan penuh.
- Verifikasi QGIS/klien GIS eksternal perlu dilakukan pada lingkungan dengan GeoServer tersedia.

## Pengujian

`tests/test_batch_group.py`, `tests/test_map_renderer_group.py`, dan `tests/test_upload_retention.py` memeriksa lifecycle, komposit raster/MVT, style Mapbox, visibility, dan retensi. Verifikasi GeoServer serta QGIS tetap memerlukan layanan eksternal yang tersedia.
