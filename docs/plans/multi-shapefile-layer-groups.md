# Multi-SHP ZIP: batch layer dan group peta

Status: disetujui; implementasi berlangsung dengan clean architecture dan prinsip deep module dari codebase-design.

Related Progress: [Progress](../progress/multi-shapefile-layer-groups.md)

Related ADR: [Layer Group mengomposisikan Layer mandiri](../adr/0005-layer-groups-compose-independent-layers.md)

## Kebutuhan pengguna

- Satu ZIP dapat berisi beberapa dataset SHP dan diproses sekaligus.
- Pengguna dapat memilih hasil berupa group peta atau beberapa layer terpisah.
- Keluaran versi pertama: raster tile, vector tile (MVT), dan WMS untuk kedua mode.
- Style harus mendukung hasil group dan setiap tipe keluaran yang didukung.
- Upload API menangani upload; Tileserver menerima sumber file untuk pemrosesan peta.
- Kode layer/group dibuat otomatis dan dapat disesuaikan sebelum proses.

## Bukti awal repository

- `app/workers/tasks.py:63`: `import_shapefile_task` mengimpor seluruh dataset, tetapi menyimpan hasil ke satu Layer berdasarkan `upload.layer_id`; kode Layer dibuat dari nama file dan pemeriksaan keunikan.
- `app/infrastructure/services/file_service.py:33`: helper `extract_zip` mengembalikan SHP pertama. Penggunaan helper pada setiap jalur publish/tiling masih perlu ditelusuri.
- `docs/features/upload-artifact-handoff.md`: handoff Upload API sudah memakai artifact, grant, handoff ID, dan lease.
- `docs/adr/0001-per-layer-sld-no-shared-styles.md`: style WMS dimiliki masing-masing Layer, bukan style bersama.
- `app/domain/schemas.py:43`: `ArtifactTilingRequest.output_format` menerima `raster` dan `mvt`; publikasi GeoServer tersedia melalui jalur `publish_to_geoserver` terpisah. Daftar `LayerType` juga memuat tipe layanan eksternal dan tidak boleh langsung dianggap sebagai daftar format konversi SHP.
- `docs/features/artifact-manual-tiling.md` memperbarui dokumentasi handoff lama: artifact disiapkan tanpa otomatis menjalankan tiling. Dokumentasi ini menyebut lease dilepas setelah tiling sukses atau retry terakhir gagal; kebijakan tersebut perlu diubah/diverifikasi terhadap kebutuhan retensi yang disepakati.
- Checkout kandidat integrasi ditemukan di `/home/anjar/Development/base-project-apps/services/dashboard` dan `/home/anjar/Development/base-project-apps/services/upload_api`. Graph project `dashboard` memuat `features/geo/tile/hooks.ts::useMultipleUploads` yang memanggil `/uploads/artifact`; kesesuaian index dengan checkout dan instruksi lokal perlu diverifikasi sebelum perubahan.

## Verifikasi teknis yang masih diperlukan

Catatan verifikasi protokol: [GeoServer layer groups](https://docs.geoserver.org/stable/en/user/rest/api/layergroups/) mendukung satu nama group pada WMS GetMap. [QGIS 3.44 vector tiles](https://docs.qgis.org/3.44/en/docs/user_manual/working_with_vector_tiles/vector_tiles.html) mendukung sumber tile XYZ dan Style URL terpisah; data vector tile tidak memuat style kartografis. Kontrak MVT di bawah telah disepakati sebagai desain, tetapi belum diverifikasi melalui integrasi.

1. Verifikasi ketiga kontrak layanan group pada renderer dan klien aktual, termasuk GetFeatureInfo dan legenda WMS serta dukungan simbol di QGIS/MVT.
2. Ikat hasil pemeriksaan ke identitas/versi artifact dan identitas dataset yang stabil agar input tidak berubah di antara pemeriksaan, proses, dan retry.
3. Gunakan constraint database untuk reservasi kode saat proses bersamaan; rincian penanganan konflik kode manual harus konsisten dengan validasi dashboard.
4. Verifikasi pergantian versi hasil dan invalidasi cache seluruh group pemakai, termasuk ketika publikasi group gagal setelah anggota berhasil.
5. Verifikasi retensi/referensi artifact bersama pada Upload API, renewal bila diperlukan, serta pelepasan idempotent tanpa merusak pemakai layanan lain.
6. Pastikan alur impor PostGIS dan kontrak API lama tetap berfungsi; jangan menganggap dukungan impor multi-SHP saat ini sama dengan registrasi multi-Layer yang baru.

Hal-hal tersebut adalah pekerjaan desain teknis dan pembuktian implementasi. Keputusan produk di bawah tetap menjadi acuan; bila keterbatasan teknis mengharuskan perubahan perilaku yang disepakati, perubahan itu harus dibahas dengan pengguna.

## Keputusan disepakati

- Satu dataset SHP menjadi satu Layer mandiri.
- Layer Group menyusun beberapa Layer menjadi satu peta tanpa melebur dataset.
- Setiap Layer tetap memiliki style sendiri; visibility dan urutan anggota diatur per group, dan group memiliki identitas sendiri.
- Group dapat diakses aplikasi lain melalui kode/URL group sebagai satu peta; layer anggota tetap dapat diakses sendiri. Group bukan hanya pengelompokan di dashboard.
- Untuk versi pertama, satu pilihan format keluaran berlaku bagi seluruh dataset SHP dalam ZIP, baik mode group maupun layer terpisah. Format campuran per anggota tidak termasuk cakupan versi pertama.
- Kode group dibuat otomatis dari nama ZIP; kode layer anggota dari nama SHP. Pengguna boleh menyesuaikan kode sebelum proses dimulai dan tidak wajib mengisi kode satu per satu.
- Kode otomatis yang bentrok diberi akhiran unik. Kode tetap sama saat retry dan setelah dipublikasikan agar URL stabil; nama tampilan tetap dapat diubah.
- Setelah Upload API menerima ZIP, Tileserver memeriksa isinya dan menampilkan daftar dataset SHP beserta hasil validasi sebelum pemrosesan peta dimulai.
- Pengguna dapat memilih sebagian dataset tanpa upload ulang, memilih mode group/layer terpisah, satu format keluaran, serta nama dan kode; aksi eksplisit “Proses” memulai pemrosesan seluruh pilihan sekaligus.
- Jika sebagian SHP gagal diproses, hasil anggota yang berhasil tetap disimpan. Retry hanya memproses anggota yang gagal; progress menampilkan status dan alasan kegagalan per dataset.
- Pada mode layer terpisah, anggota yang berhasil langsung tersedia. Pada mode group, group belum dipublikasikan sampai seluruh anggota pilihan berhasil, agar peta tidak dipublikasikan dengan data yang tidak lengkap. Ketersediaan endpoint mandiri anggota sebelum group selesai belum diputuskan.
- Setiap SHP mendapat style awal otomatis sesuai geometri (garis, polygon, atau titik). Pengguna boleh menyesuaikan style sebelum “Proses”, tetapi tidak wajib mengatur setiap anggota secara manual.
- Pada mode group, konfigurasi sebelum proses juga menyediakan urutan tampil dan visibility awal tiap anggota. Group menggunakan style milik masing-masing anggota agar tampilan konsisten ketika layer diakses sendiri; tidak memiliki salinan style terpisah.
- Menghapus group hanya menghapus susunan peta dan akses kode/URL group. Layer anggota tetap tersedia secara mandiri, termasuk data, style, dan URL masing-masing; penghapusan group tidak menghapus anggota secara berantai.
- Penghapusan layer yang masih menjadi anggota group ditolak. Sistem menampilkan group pemakainya; pengguna harus mengeluarkan layer dari seluruh group pemakai sebelum menghapusnya, sehingga penghapusan tidak diam-diam mengubah peta yang dipublikasikan.
- Satu Layer boleh menjadi anggota beberapa group tanpa menggandakan data. Urutan tampil dan visibility diatur pada keanggotaan masing-masing group; style tetap milik Layer, sehingga perubahan style memengaruhi semua group yang memakai Layer tersebut.
- Setelah publikasi, group boleh ditambah anggota dari Layer yang sudah siap dengan format yang sama, termasuk hasil ZIP lain. Anggota boleh dikeluarkan dan urutannya diubah tanpa mengubah kode/URL group; upload ulang anggota lama tidak diperlukan. Mekanisme penerapan perubahan pada layanan publikasi masih perlu dirinci.
- Group tanpa anggota boleh tetap tersimpan sebagai draft, tetapi tidak dapat dipublikasikan. Mengeluarkan anggota terakhir dari group terbit menonaktifkan akses petanya dengan keterangan “group belum memiliki layer”; nama dan kode dipertahankan agar dapat digunakan kembali setelah anggota ditambahkan. Mekanisme publikasi ulang belum diputuskan.
- Pada pemeriksaan ZIP, kegagalan validasi per dataset tidak menghalangi pemilihan dataset lain yang valid. Dataset tidak valid ditandai dengan alasan dan tidak dapat dipilih; kelengkapan group dihitung berdasarkan dataset yang dipilih, bukan seluruh isi ZIP. Kerusakan atau masalah keamanan pada tingkat arsip menyebabkan seluruh ZIP ditolak.
- ZIP dengan satu SHP tetap melalui pemeriksaan ZIP dan secara default menghasilkan satu Layer mandiri, tanpa kewajiban membuat group. Layer tersebut dapat ditambahkan kemudian ke group yang sesuai.
- Pembatalan batch mempertahankan Layer yang sudah berhasil, menghentikan pekerjaan yang belum selesai, dan membersihkan hasil sementara. Pada mode group, group yang belum lengkap tetap belum dipublikasikan. Pengguna dapat melanjutkan anggota yang belum selesai tanpa mengulang anggota yang berhasil.
- Perubahan style setelah publikasi yang membutuhkan pembuatan ulang tile diproses di background. Versi lama tetap tersedia sampai hasil baru berhasil, lalu Layer dan seluruh group pemakainya menggunakan hasil baru. Jika proses gagal, versi lama tetap tersedia dan pengguna dapat retry. Ini merupakan perilaku target, bukan klaim kemampuan pergantian versi atomik pada implementasi saat ini.
- ZIP sumber tetap tersedia selama masih ada Layer hasilnya atau proses yang belum selesai dan membutuhkan sumber. Satu ZIP digunakan bersama seluruh hasil, dan penghapusan group tidak menghapus ZIP. Setelah semua Layer hasil dihapus dan tidak ada proses yang membutuhkan sumber, Tileserver melepas referensinya kepada Upload API untuk pembersihan sesuai kebijakan layanan tersebut. Pengguna menerima konsekuensi penyimpanan sumber lebih lama; dukungan retensi/lease aktual Upload API masih perlu diverifikasi.
- Akses group ditargetkan untuk aplikasi GIS umum seperti QGIS, terutama melalui WMS, bukan hanya aplikasi web khusus yang membaca konfigurasi anggota. Kompatibilitas aktual ketiga kontrak layanan yang disepakati harus diuji pada klien.
- Cakupan keluaran versi pertama adalah raster tile, vector tile (MVT), dan WMS pada kedua mode (group maupun Layer terpisah). Tipe layanan lain dalam enum LayerType tidak otomatis termasuk format keluaran fitur ini.
- Group MVT menyediakan URL data tile yang menyajikan seluruh anggota dengan identitas Layer tetap terpisah, serta URL style pendamping yang diturunkan otomatis dari style anggota, urutan tampil, dan visibility group. Style URL bukan style independen atau salinan konfigurasi yang diedit terpisah dari Layer anggota. Kebijakan apakah anggota tersembunyi tetap dikirim sebagai data tile belum diputuskan; visibility merupakan pengaturan tampilan.
- Group raster menyediakan URL tile yang menyajikan satu gambar gabungan seluruh anggota yang terlihat, sesuai urutan tampil dan style masing-masing. Penggabungan hanya pada gambar tampilan; data dan URL Layer anggota tetap terpisah serta tersedia secara mandiri.
- Informasi klik group WMS menampilkan atribut dari seluruh anggota yang terlihat dan terkena klik, dipisahkan berdasarkan nama Layer asal. Anggota tersembunyi tidak menghasilkan informasi klik melalui group. Mekanisme GetFeatureInfo, format respons, dan batas hasil masih perlu diverifikasi pada jalur WMS aktual.
- Group WMS, raster tile, dan MVT memiliki legenda gabungan yang dibuat otomatis mengikuti style, urutan tampil, dan visibility anggota. Legenda mencantumkan nama Layer dan simbolnya; anggota tersembunyi tidak ditampilkan. Format penyajian legenda dan integrasi klien belum dirinci.
- Cakupan implementasi mencakup dashboard sampai alur pengguna selesai, bukan backend Tileserver saja. Upload API tetap menyimpan file, Tileserver memeriksa/memproses peta, dan dashboard menyediakan pemeriksaan ZIP, pemilihan dataset, konfigurasi group/style, serta pemantauan proses. Integrasi retensi Upload API disesuaikan jika diperlukan. Lokasi checkout dashboard/Upload API yang ditargetkan masih perlu dipastikan sebelum perubahan lintas repository.
- Setelah pengguna menekan “Proses”, group dipublikasikan otomatis ketika seluruh anggota pilihan berhasil, tanpa tombol publikasi tambahan. Aturan ini juga berlaku setelah retry atau melanjutkan proses melengkapi seluruh anggota; group kosong tetap draft.

## Rancangan implementasi untuk ditinjau

### 1. Kontrak dan model data

- Tambahkan representasi hasil pemeriksaan ZIP, batch pemrosesan, item dataset, Group, dan keanggotaan Group–Layer. Nama model/tabel final mengikuti struktur repository setelah penelusuran.
- Satu item dataset mempunyai identitas stabil, sumber dataset di dalam ZIP, Layer tujuan, konfigurasi, status, progress, dan alasan gagal. Satu batch mempunyai pilihan format dan mode serta referensi artifact bersama; retry menggunakan identitas yang sama.
- Keanggotaan menyimpan urutan dan visibility. Style tetap dimiliki Layer; style MVT group dan legenda diturunkan dari konfigurasi tersebut.
- Definisikan perubahan database pada SQLModel terlebih dahulu, lalu generate migration Alembic. Tidak membuat migration manual kecuali pengecualian metadata yang diizinkan AGENTS.md.
- Pisahkan API pemeriksaan/configuration/process/status/retry/cancel dari API CRUD group dan endpoint peta publik. Sesuaikan naming dengan API aktual, dan pertahankan kontrak single-upload lama.

### 2. Pemeriksaan ZIP dan orkestrasi

- Gunakan referensi artifact Upload API; pemeriksaan berat dilakukan di worker agar request tidak menunggu ekstraksi/validasi seluruh ZIP.
- Bedakan kegagalan keamanan/struktur arsip yang menolak seluruh ZIP dari kesalahan dataset yang dapat ditampilkan per item. Identitas dataset menggunakan lokasi dalam arsip, bukan basename saja, untuk menghindari tabrakan SHP di subfolder berbeda.
- Alokasikan kode/Layer/item secara idempotent sebelum dispatch, dengan pemeriksaan keunikan transaksional. Kode manual yang bentrok diusulkan menghasilkan error yang dapat diperbaiki pengguna, bukan diubah diam-diam.
- Jalankan item melalui worker dengan concurrency terkendali. Publikasi group menjadi tahap tersendiri setelah semua anggota siap; retry publikasi group tidak perlu mengulang konversi anggota yang sudah berhasil.
- Tangani perlombaan cancel/worker selesai dan dispatch ganda; hasil sukses tetap dipertahankan. Bersihkan hanya hasil sementara milik pekerjaan yang bersangkutan.

### 3. Publikasi dan perubahan tampilan

| Format | Kontrak target group |
| --- | --- |
| WMS | Satu nama/kode group pada layanan WMS, mengikuti style/urutan/visibility; anggota tetap dapat diakses sendiri; informasi klik dipisahkan per anggota terlihat. |
| Raster tile | Satu endpoint tile gambar gabungan anggota terlihat, tanpa melebur data anggota. |
| MVT | Satu endpoint data tile dengan identitas anggota terpisah dan Style URL turunan konfigurasi group/anggota. |

- Gunakan adapter per format di balik lifecycle group yang sama. Untuk WMS, verifikasi mode GeoServer group yang tetap mempertahankan akses anggota.
- Untuk raster dan MVT, evaluasi komposisi hasil anggota dan caching per versi group; jangan mengunci library atau strategi materialisasi sebelum memeriksa renderer yang tersedia.
- Pertahankan versi publik lama selama pembangunan versi baru. Pergantian output/konfigurasi publik dan cache harus merujuk versi yang konsisten, dengan kegagalan dapat di-retry.
- Legenda tersedia sebagai representasi terstruktur bagi dashboard dan gambar yang dapat digunakan klien sesuai kemampuan format. Detail endpoint final mengikuti verifikasi layanan yang ada.

### 4. Retensi sumber dan integrasi Upload API

- Ganti pelepasan lease pada akhir setiap task dengan lifecycle referensi pemakai sumber yang memenuhi kebutuhan retensi. Verifikasi API lease/pinning yang tersedia sebelum memilih bentuk perubahan.
- Jangan menggandakan ZIP untuk setiap anggota. File kerja temporer tetap dapat dibersihkan setelah pemrosesan, sementara artifact sumber dipertahankan.
- Sediakan retry/rekonsiliasi pelepasan referensi jika Upload API tidak tersedia. Penghapusan satu Layer tidak boleh menghapus sumber yang masih digunakan anggota atau job lain.

### 5. Dashboard

- Perluas alur upload yang sudah ada: upload → pemeriksaan → daftar dataset/validasi → pemilihan mode/format/kode/style → Proses → progress per anggota → hasil Layer/group dan URL pemakaian.
- Tampilkan kode otomatis yang dapat diedit sebelum proses; kesalahan per dataset dan konflik kode harus dapat diperbaiki tanpa mengulangi upload yang masih valid.
- Sediakan pengelolaan anggota, urutan/visibility, legenda, retry/resume/cancel, status draft/publishing/published/failed sesuai state backend final, serta daftar group yang menghalangi penghapusan Layer.
- Gunakan modul fitur dashboard dan API langsung ke backend sesuai instruksi lokal. Inisialisasi plan/progress terkait di setiap repository yang diubah sebelum menulis kodenya; ikuti permission dan komponen yang sudah tersedia.

### 6. Verifikasi dan dokumentasi akhir

- Uji ZIP multi-SHP di subfolder, nama dataset berulang, validasi parsial, serta penolakan arsip rusak/tidak aman.
- Uji idempotensi proses/retry, tabrakan kode bersamaan, cancel yang berlomba dengan task selesai, retry publikasi, dan retensi sumber setelah kegagalan.
- Uji semua format pada mode group dan terpisah: isi hasil, style, urutan/visibility, legenda, URL anggota, serta WMS feature info.
- Uji reuse Layer lintas group, pergantian style dengan output lama tetap tersedia, perubahan anggota, group kosong, dan aturan penghapusan.
- Jalankan alur browser dari upload hingga publikasi, termasuk gagal/retry/cancel/resume; verifikasi API dan data yang mendasarinya. Verifikasi kompatibilitas QGIS secara aktual bila lingkungan tersedia, dan laporkan keterbatasan jika belum dapat diuji.
- Jalankan regression untuk single-SHP, artifact handoff, impor PostGIS, dan publikasi/tiling lama. Perbarui graph setelah perubahan kode.
- Setelah implementasi dan verifikasi selesai, tulis dokumentasi fitur di `docs/features/multi-shapefile-layer-groups.md` dan dokumentasi dashboard/Upload API yang relevan, dengan tautan balik ke plan/progress.

## Batas sesi

Dokumentasi keputusan dan glossary diperbarui selama wawancara. Kode aplikasi belum diubah. ADR hanya dibuat setelah trade-off yang relevan diputuskan; dokumentasi fitur final dibuat setelah implementasi selesai.
