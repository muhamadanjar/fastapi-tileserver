# Analisis SHP terhadap layer acuan

[Rencana](../plans/pola-ruang-intersect-workflow.md) · [Desain](../plans/pola-ruang-intersect-technical-design.md) · [Progress](../progress/pola-ruang-intersect-workflow.md)

## Cara menggunakan

1. Admin membuka menu layer di dashboard → **Acuan analisis**. Pilih nama,
   kolom kategori dan atribut yang boleh tampil, kemudian simpan. Sumber harus
   berupa polygon/MultiPolygon yang geometri vektornya dapat dibaca tileserver.
2. Pengguna membuka Geoportal → **Analisis → Upload SHP**, mengunggah satu ZIP
   SHP beserta SHX, DBF dan PRJ, lalu memilih tepat satu acuan.
3. Jalankan analisis. Hasil otomatis ditambahkan dan difokuskan pada peta.
   Rekap kategori dan rincian menampilkan luas, panjang atau jumlah titik
   sesuai dimensinya. Atribut input boleh kosong; setiap fitur mendapat Objek N.
4. Unduh GeoJSON, CSV ZIP atau SHP ZIP. Hasil tersedia kembali melalui browser
   yang sama sampai 24 jam setelah selesai. Pengguna dapat menghapus lebih awal.

Konfigurasi memakai layer existing tanpa upload SHP admin kedua. Konfigurasi,
input dan hasil tidak menambah katalog layer; publikasi sumber tetap mengikuti
pengaturan existing. Acuan yang dilepas hilang dari pilihan proses baru.
Layer sumber tidak dapat dihapus/unpublish selama terdaftar sebagai acuan atau
masih dipakai job aktif. Hasil selesai tetap dapat dibuka setelah sumber dihapus.

## Membaca hasil

Hasil adalah informasi irisan, bukan keputusan hukum sesuai/tidak sesuai.
Tidak melaporkan bagian di luar cakupan. Persentase rincian memakai ukuran penuh
objek input, sehingga total dapat kurang dari 100%. Antar kategori yang overlap
bisa melebihi 100%. Kategori sama dihitung sekali per objek dalam rekap; rincian
pasangan sumber tetap utuh. “Objek tumpang tindih” menandai cakupan berulang
pada objek/dimensi, bukan posisi overlap eksak masing-masing baris.

Kontak pada batas tetap ditampilkan. Sentuhan polygon yang hanya berupa garis
atau titik tidak menambah luas. Kategori kosong muncul sebagai “Kategori belum
diisi”, dengan peringatan. Tidak ada irisan merupakan hasil sukses kosong.
Waktu baca dan SHA256 isi acuan tersedia pada **Sumber analisis**.

Area dihitung dengan EPSG:6933; panjang dengan segmen geodesik WGS84.
Topologi 2D EPSG:4326 tanpa toleransi snapping; Z/M tidak dianalisis. Geometri
invalid, CRS tak dikenal, lintasan antimeridian lebar, serta koordinat di luar
86°S–86°N ditolak. Dukungan Multi/koleksi pada mesin tidak membuat satu SHP
mampu mencampur semua keluarga geometri.

SHP hasil dipisah menjadi points/lines/polygons bila ada. `fields.json` memetakan
nama atribut pendek SHP, `result.geojson` menyertakan data lengkap untuk nilai
yang tidak dapat direpresentasikan DBF. Ekspor membatasi gabungan 200 kolom atribut;
nilai teks DBF dapat dipendekkan, nilai lengkap tetap ada di GeoJSON. CSV ZIP
berisi details.csv dan summary.csv. Hasil kosong tetap menghasilkan paket valid.

## API dan akses

Semua route berada di `/api/v1`.

| Metode dan route | Kegunaan |
|---|---|
| GET /analysis-workspace/references | Pilihan acuan dan batas upload |
| POST /analysis-workspace/inputs | Multipart field `file` ZIP SHP |
| DELETE /analysis-workspace/inputs/{id} | Hapus input dan hasil terminal |
| POST /analysis-workspace/jobs | JSON `input_id`, `reference_id` |
| GET /analysis-workspace/jobs | Riwayat sementara sesi browser |
| GET /analysis-workspace/jobs/{id} | pending/processing/done/failed |
| GET /analysis-workspace/jobs/{id}/rows | offset/limit; rincian, summary, warnings, reference |
| GET /analysis-workspace/jobs/{id}/download?format=geojson | Format geojson, csv, shp |
| GET/PUT/DELETE /analysis-references/{layer_id} | Baca/simpan/lepas konfigurasi admin |

Semua endpoint workspace selain daftar acuan memerlukan `X-Analysis-Session`.
Browser membuat token acak 32 byte dan menyimpannya di localStorage. Server
menyimpan hash, memeriksa kepemilikan untuk setiap akses; UUID saja tidak cukup.
Token merupakan kredensial akses hasil: jangan menaruhnya di URL. Tamu dan
pengguna login memakai mekanisme browser yang sama, tanpa sinkronisasi akun.
Menghapus data browser menghilangkan akses ke hasil yang masih tersimpan.

Admin memerlukan Bearer token berizin `tiles.manage`; validasi dilakukan ke
layanan otorisasi walaupun middleware global belum diaktifkan. `AUTH_DISABLED`
hanya untuk lingkungan pengembangan/pengujian. PUT menerima `name`,
`category_field`, `attributes` (maksimal 100). GET tetap mengembalikan konfigurasi
dan source_error jika sumber rusak, agar admin dapat melepaskan acuan tersebut.

## Menjalankan layanan

Terapkan migrasi model pada database layanan dengan `alembic upgrade head`
(revisi fitur 0011), lalu jalankan API, worker Celery dan tepat satu scheduler
Beat. API dan worker harus berbagi UPLOAD_DIR. production.yml menyertakan beat
pada volume tileserver-data; broker/backend mengikuti konfigurasi existing.
Tidak ada deployment atau migrasi database produksi yang dilakukan otomatis.

Geoportal: `NEXT_PUBLIC_TILESERVER_API_URL` menunjuk origin tileserver.
Dashboard: runtime `NEXT_PUBLIC_TILESERVER_URL` menunjuk origin yang sama.
Atur CORS untuk origin frontend dan header sesi/Authorization. Sumber berupa
remote WMS/raster saja tidak menyediakan geometri untuk intersect; gunakan
layer vektor single-dataset, artifact sumber, atau layer survei yang didukung.

| Pengaturan | Default |
|---|---:|
| ANALYSIS_MAX_FEATURES | 5000 |
| ANALYSIS_MAX_UPLOAD_BYTES | 52428800 |
| ANALYSIS_MAX_EXTRACTED_BYTES | 262144000 |
| ANALYSIS_MAX_VERTICES | 1000000 |
| ANALYSIS_MAX_RESULTS | 100000 |
| ANALYSIS_MAX_ACTIVE_JOBS | 4 |
| ANALYSIS_MAX_OWNER_INPUTS | 5 |
| ANALYSIS_MAX_STORED_INPUTS | 200 |
| ANALYSIS_JOB_TIMEOUT_SECONDS | 900 |
| ANALYSIS_QUEUE_TIMEOUT_SECONDS | 3600 |
| ANALYSIS_EPHEMERAL_TTL_HOURS | 24 |

Cleanup berjalan tiap lima menit. Batas waktu processing mendapat grace 120
detik sebelum cleanup menandainya gagal; Celery memakai soft/hard timeout.
Input aktif dilindungi, input tanpa job dihitung sejak upload, hasil terminal
sejak selesai/gagal. Kegagalan penghapusan berkas dicatat dan dicoba kembali.
Batas ini perlu disesuaikan berdasarkan uji beban data acuan nyata. Tabel memakai
pagination, tetapi preview memakai GeoJSON hasil utuh yang dibatasi server;
hasil dekat batas maksimum tetap dapat berat bagi memori browser.
