Related Plan: [Multi-SHP ZIP: batch layer dan group peta](../plans/multi-shapefile-layer-groups.md)

# Progress

Status: implementasi disetujui pengguna; menerapkan clean architecture dan codebase-design. Mulai dari model domain, interface aplikasi, dan adapter persistence/publikasi.

- [x] Catat kebutuhan awal pengguna.
- [x] Periksa glossary, ADR style, handoff artifact, dan kode impor multi-SHP yang tersedia.
- [x] Sepakati model group dan layer anggota; catat istilah Layer Group dalam CONTEXT.md.
- [x] Sepakati akses group melalui kode/URL untuk aplikasi lain, dengan akses anggota tetap tersedia.
- [x] Sepakati satu format keluaran untuk seluruh SHP dalam ZIP pada kedua mode untuk versi pertama.
- [x] Sepakati kode otomatis yang dapat disesuaikan sebelum proses, penanganan bentrok kode otomatis, dan stabilitas kode saat retry/setelah publikasi.
- [x] Sepakati pemeriksaan ZIP oleh Tileserver, pemilihan sebagian dataset tanpa upload ulang, konfigurasi, dan aksi eksplisit “Proses”.
- [x] Sepakati penyimpanan hasil sukses, retry hanya anggota gagal, progress per dataset, dan publikasi group setelah seluruh anggota pilihan berhasil.
- [x] Sepakati style awal otomatis per geometri yang bisa disesuaikan sebelum proses, urutan tampil/visibility awal group, dan penggunaan style anggota tanpa salinan style group.
- [x] Sepakati penghapusan group mempertahankan data, style, dan URL seluruh layer anggota.
- [x] Sepakati penolakan penghapusan layer yang masih dipakai group, dengan daftar group pemakai sebagai informasi bagi pengguna.
- [x] Sepakati penggunaan satu Layer oleh beberapa group, urutan/visibility per group, dan dampak perubahan style ke seluruh group pemakai; perbarui glossary.
- [x] Sepakati penambahan anggota dari Layer siap berformat sama termasuk ZIP lain, pengeluaran anggota, dan perubahan urutan setelah publikasi tanpa perubahan kode/URL group.
- [x] Sepakati group kosong tetap tersimpan sebagai draft, tidak dapat dipublikasikan, dan mempertahankan nama/kode; akses peta terbit dinonaktifkan ketika anggota terakhir dikeluarkan.
- [x] Sepakati pemilihan dataset valid meskipun dataset lain tidak valid, alasan validasi per dataset, dan penolakan seluruh ZIP untuk kerusakan/masalah keamanan arsip.
- [x] Sepakati default Layer mandiri untuk ZIP single-SHP, dengan pemeriksaan ZIP tetap berjalan dan penambahan ke group dapat dilakukan kemudian.
- [x] Sepakati pembatalan batch mempertahankan hasil sukses, membersihkan hasil sementara, menahan publikasi group yang belum lengkap, dan memungkinkan melanjutkan anggota yang belum selesai.
- [x] Sepakati pemrosesan ulang style di background dengan versi lama tetap tersedia hingga hasil baru berhasil dan retry tanpa menghilangkan versi lama saat gagal.
- [x] Sepakati retensi satu ZIP sumber bersama selama dibutuhkan Layer/proses, tanpa penghapusan akibat penghapusan group, dan pelepasan referensi ke Upload API setelah tidak ada pemakai.
- [x] Sepakati target akses group untuk aplikasi GIS umum seperti QGIS, terutama WMS; kontrak vector/raster tile masih perlu diverifikasi.
- [x] Arsipkan keputusan komposisi dan kepemilikan style dalam [ADR 0005](../adr/0005-layer-groups-compose-independent-layers.md).
- [x] Periksa pilihan artifact raster/MVT dan jalur publikasi GeoServer terpisah; temukan kebijakan pelepasan lease lama yang perlu disesuaikan.
- [x] Sepakati cakupan keluaran versi pertama: raster tile, vector tile (MVT), dan WMS untuk group serta Layer terpisah.
- [x] Sepakati URL tile group MVT dengan identitas anggota terpisah dan Style URL pendamping mengikuti style anggota, urutan tampil, serta visibility group.
- [x] Sepakati URL tile group raster berupa gambar gabungan anggota terlihat mengikuti urutan/style, dengan data dan URL anggota tetap mandiri.
- [x] Sepakati informasi klik group WMS untuk anggota terlihat yang terkena klik, dipisahkan menurut Layer asal; anggota tersembunyi tidak ikut.
- [x] Sepakati legenda gabungan untuk WMS, raster tile, dan MVT berisi nama/simbol anggota terlihat mengikuti style dan urutan group.
- [x] Sepakati implementasi sampai dashboard, dengan Upload API sebagai penyimpan file dan Tileserver sebagai pemeriksa/pemroses peta.
- [x] Sepakati publikasi group otomatis setelah seluruh anggota berhasil, termasuk setelah retry/resume; group kosong tetap draft.
- [x] Susun rancangan lintas layanan, urutan implementasi, dan kriteria verifikasi dalam plan.
- [x] Telusuri jalur publish/tiling serta kontrak format sesuai model yang dipilih.
- [x] Sepakati deteksi, kode, style, kegagalan, dan lifecycle.
- [x] Perbarui glossary dan ADR jika keputusan memenuhi kriterianya.
- [x] Konfirmasi pemahaman bersama sebelum implementasi; pengguna meminta implementasi sampai dashboard dengan clean architecture.
- [x] Rinci implementasi dan verifikasi setelah desain disepakati.
- [x] Implementasi dan verifikasi.
- [x] Buat dokumentasi final fitur (lihat [Dokumentasi Fitur](../features/multi-shapefile-layer-groups.md)).

## Log Implementasi

- [x] **Model domain** (`app/domain/models.py`): tambah `BatchRecord`, `DatasetRecord`, `GroupRecord`, `GroupMemberRecord`, `CodeReservation`.
- [x] **Migrasi** (`alembic/versions/0009_add_batch_group_tables.py`): buat kelima tabel; tanpa FK ke `layers` untuk `datasets.layer_id`/`layer_group_members.layer_id` karena layer dibuat setelah proses (integritas dijaga di lapisan aplikasi via `deletion_guard`).
- [x] **Adapter persistence** (`app/infrastructure/db/catalog.py`): `SyncCatalog` + `SyncStore` mengimplementasikan protokol `Catalog`/`Store`.
- [x] **Adapter publikasi** (`app/infrastructure/services/map_renderer.py`): `FileBackedMapRenderer` mengimplementasikan protokol `MapRenderer`; deteksi dataset ZIP + metadata (geometri, jumlah fitur, bbox via pyogrio), publish raster/MVT via `TilingService`, WMS via `GeoServerService`, layer group via REST GeoServer.
- [x] **API** (`app/api/v1/endpoints/batches.py`): endpoint inspect/configure/retry/cancel/status, group CRUD, guard pemakaian layer.
- [x] **Worker** (`app/workers/tasks.py`): `run_batch_task` menjalankan inspect/process di background.
- [x] **Guard penghapusan layer** (`app/api/v1/endpoints/layers.py`): tolak delete layer yang dipakai group.
- [x] **Verifikasi E2E raster**: inspect → configure group → process → layer tile dibuat → group published → guard/update/delete group berfungsi.
- [x] **MVT group composite**: `publish()` mode group + mvt menghasilkan `style.json` turunan (style anggota, urutan, visibility) di `_group_styles/{code}/style.json`; `remove()` membersihkan dir.
- [x] **Legenda**: `legend_for_group` di renderer + endpoint `GET /batches/groups/{group_id}/legend`; simbol per tipe geometri dari style anggota.
- [x] **Regression tests**: `tests/test_batch_group.py` 14 test (deletion guard, inspect, configure, process standalone/group, group CRUD, legend) terhadap in-memory store.
- [x] **Dokumentasi final fitur** (`docs/features/multi-shapefile-layer-groups.md`).

## Phase 4 — Retensi Sumber & Integrasi Upload API

- [x] **Riset kontrak lease**: baca repo Upload API (`/home/anjar/Development/base-project-apps/services/upload_api`): `ArtifactLease` tanpa expiry (pin); `request_deletion` diblokir saat ada active lease; `release_lease` idempotent; `consumer_reference` idempotent.
- [x] **Materialisasi artifact** (`app/infrastructure/services/map_renderer.py`): `_resolve_source_path` mendukung `artifact://` — unduh sekali per `artifact_id` ke `_batch_work/artifact_{id}/`, dipakai ulang tanpa duplikasi; gagal unduh → MapError 502 + cleanup.
- [x] **Lease reference-counted** (`app/workers/tasks.py`): `_release_artifact_lease(artifact_id, lease_id, upload_id)` hanya release bila `count_layers_referencing == 0` dan `count_batches_referencing == 0` (batch terminal diecualikan). Semua callsite meneruskan `upload_id`.
- [x] **Rekonsiliasi release gagal**: `_mark_pending_release(upload_id)` flag `pending_release` di upload session; task `reconcile_pending_release_task` scan flag + retry release; `_mark_released` clear flag + set `released_at`.
- [x] **Retensi delete_layer** (`app/api/v1/endpoints/layers.py`): hapus source + upload session hanya saat layer terakhir yang pakai `upload_session_id` dihapus; release lease eksplisit sebelum session dihapus.
- [x] **Layer upload_session_id** (`app/infrastructure/db/catalog.py`): `_save_layer` sekarang menulis `upload_session_id` dari batch, sehingga reference counting tepat sasaran.
- [x] **Cancel → release check** (`app/api/v1/endpoints/batches.py`): setelah cancel, panggil `_release_artifact_lease` (best-effort) untuk melepas lease jika tidak ada layer/batch aktif lain.
- [x] **Migrasi 0010** (`0010_add_upload_retention_tracking.py`): tambah `pending_release` (bool) + `released_at` (datetime) di `upload_sessions`.
- [x] **Tests** (`tests/test_upload_retention.py`): 5 test reference counting (lease kept while consumers exist, released when last consumer gone, reconciliation flag on failure).
- [x] **Existing tests**: 79 tests pass (batch_group + map_renderer_group + sld_builder + layer_legend + artifact_lease_release + retile + geoserver_style + style_utils + upload_retention). `test_upload_artifact_client_auth` pre-existing failure (header assertion drift), bukan dari perubahan ini.

## Perbaikan hasil review

- [x] Endpoint daftar group didaftarkan sebelum route batch dinamis sehingga `GET /batches/groups` tidak lagi tertangkap sebagai ID batch.
- [x] Group raster menyajikan komposit PNG on-demand di `GET /tiles/_group/{code}/{z}/{x}/{y}.png`; hanya anggota terlihat yang dikompositkan sesuai urutan group.
- [x] Group MVT menyajikan tile gabungan dan style Mapbox valid di bawah `/tiles/_group/{code}/…` dan `/tiles/_group_styles/{code}/style.json`.
- [x] Publikasi WMS memakai kode stabil sebagai nama GeoServer dan hanya memasukkan anggota terlihat.
- [x] ID dataset dan Layer diturunkan dari batch + path arsip; entri ZIP traversal/absolut/backslash ditolak sebelum ekstraksi.
- [x] PATCH membership tanpa nama mempertahankan nama group; group kosong kembali menjadi draft dan representasi publiknya dihapus.
- [x] Penghapusan layer mempertahankan source/upload session bila batch aktif masih memakainya, dan mempertahankan session `pending_release` untuk rekonsiliasi lease gagal.
- [x] Uji regresi perbaikan review: 36 test batch/group/retention lulus.
- [x] Legenda group hanya mengembalikan anggota terlihat.
- [x] Pemeriksaan ZIP membatasi jumlah dan ukuran hasil ekstraksi serta menolak nama anggota duplikat.
- [x] Reservasi kode memeriksa Layer dan Group lama; cache artifact lokal dibersihkan setelah lease terakhir berhasil dilepas.
- [ ] Dashboard ditunda: MVP backend harus diverifikasi terhadap PostgreSQL, GeoServer, dan QGIS lebih dahulu.
- [x] Kegagalan publikasi group disimpan sebagai `failed`; retry mengulang publikasi tanpa merender ulang anggota yang sudah selesai.
- [x] Rekonsiliasi release artifact dijadwalkan setiap lima menit oleh Celery Beat; service Beat tersedia pada profile development dan production.
- [x] `SyncLayerRepository.code_exists` ditambahkan agar task impor sinkron dapat menjamin kode Layer unik, selaras dengan repository async yang telah ada.
- [x] Import shapefile mendeteksi schema ekstensi PostGIS dan memasukkannya ke `search_path` hanya pada koneksi impor; instalasi PostGIS di `geodata` didukung tanpa memindahkan tabel aplikasi.

## Verifikasi lingkungan MVP

- [x] Konfigurasi Docker Compose tervalidasi dan health service lokal menunjukkan PostgreSQL serta Redis terhubung.
- [x] Migrasi Alembic pada database runtime telah berada di `0010 (head)`; `alembic upgrade head` idempoten.
- [x] Uji E2E task impor pada PostgreSQL/PostGIS runtime: migrasi berada di `0010`, ekstensi PostGIS 3.6 berada di schema `geodata`, ekstraksi ZIP shapefile, impor PostGIS, pencatatan progres, dan pendaftaran Layer berhasil. Perbaikan `SyncLayerRepository.code_exists` dan search path PostGIS telah diverifikasi oleh uji ini.
- [x] Uji E2E antrean: task impor dipublikasikan ke RabbitMQ sementara, diproses worker dari checkout fitur, menulis ke PostGIS runtime, dan menyelesaikan result backend Redis sementara.
- [ ] Runtime lama belum siap untuk E2E batch melalui HTTP: container TileServer belum memuat checkout fitur, dan konfigurasi RabbitMQ runtime memakai hostname yang tidak dapat diresolusikan dari container fitur. Worker/Beat juga belum aktif.
- [ ] Verifikasi GeoServer WMS/GetFeatureInfo dan kompatibilitas QGIS menunggu environment yang menjalankan checkout ini beserta worker, RabbitMQ, dan GeoServer.
