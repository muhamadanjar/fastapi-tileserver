Related Plan: [Analisis objek unggahan terhadap pola ruang](../plans/pola-ruang-intersect-workflow.md)

# Progress

## Implementasi dimulai

Pengguna secara eksplisit meminta implementasi. Scope mencakup tileserver,
geoportal, dan konfigurasi acuan pada panel layer dashboard existing.

- [x] Model konfigurasi/job/input dan migrasi autogenerate pada database terisolasi.
- [x] Mesin intersect semua dimensi, deduplikasi, kontak, validasi, dan ekspor.
- [x] API publik sesi browser, API admin berizin, worker, cleanup, guard sumber.
- [x] UI konfigurasi dashboard dan workflow geoportal.
- [x] Pengujian terarah, verifikasi browser, graph update, dokumentasi akhir.

- [x] Baca glossary dan instruksi proyek.
- [x] Periksa jalur intersect tileserver dan panel analisis geoportal.
- [x] Catat kemampuan dan batasan yang dibuktikan oleh kode lokal.
- [x] Sepakati makna kesesuaian dan keluaran utama: informasi kategori, luas,
  persentase, dan atribut acuan cukup; tanpa vonis sesuai/tidak sesuai.
- [x] Sepakati lifecycle input, sumber acuan, dan kasus batas utama.
- [x] Perbarui glossary dan catat ADR pemakaian bersama sumber layer.
- [x] Konfirmasi pemahaman bersama dan scope implementasi.
- [x] Tulis draft desain teknis berdasarkan model dan alur existing.
- [x] Sepakati penggunaan sumber layer existing tanpa duplikasi SHP/katalog.
- [x] Tuntaskan rincian desain teknis yang masih ditandai sebagai usulan.
- [x] Implementasi serta verifikasi setelah scope disepakati.
- [x] Dokumentasi fitur akhir setelah implementasi selesai.

## Sesi 2026-09-13

Kesimpulan sementara: fondasi intersect tersedia, tetapi workflow unggah SHP
hingga laporan pola ruang belum lengkap. Loader juga membatasi sumber input;
layer tampil di peta tidak otomatis dapat dipakai analisis.

Pertanyaan pertama dijawab: pengguna membutuhkan kedua keluaran karena kasus
intersect beragam. Detail makna dan aturan kesesuaian belum selesai disepakati.
Pengguna memperjelas bahwa admin mengatur layer acuan khusus analisis, yang
tidak muncul di katalog layer. Pengguna cukup upload SHP dan menerima hasil
otomatis tanpa memilih profil atau menunggu tindakan admin. Glossary diperbaiki
agar tidak menganggap matriks aturan tambahan sudah disepakati.
Pengguna menerima informasi irisan tanpa vonis sesuai/tidak sesuai. Pengguna
kemudian meminta dukungan SHP dengan atau tanpa atribut. Inspeksi kode memastikan
ID per fitur dapat dibuat otomatis per run saat kolom ID tidak dipilih.
Pengguna mengonfirmasi “tanpa atribut” berarti isi atribut kosong dan geometri
selalu ada. Ini bukan permintaan dukungan berkas pendamping SHP yang hilang.
Pengguna meminta dukungan semua tipe geometri. Keluaran titik/garis memerlukan
perluasan backend karena jalur saat ini tidak mempertahankan atribut acuan
seperti kebutuhan laporan kategori. Dukungan Multi/koleksi dan metrik sesuai
dimensi dicatat sebagai rincian desain yang harus dituntaskan.
Pengguna menerima rekomendasi kontak batas: tampilkan semua kategori yang
bersentuhan dengan penanda “pada batas”; kontak polygon tanpa luas dipisahkan
dari irisan berluas positif. Istilah kontak batas dicatat dalam glossary.
Pengguna menolak pemeriksaan seluruh acuan aktif secara otomatis. Pengguna
ingin memilih layer acuan, sehingga hanya pilihan tersebut diproses. Layer
tetap tersembunyi dari katalog peta, tetapi tersedia di pilihan khusus analisis.
Pengguna menetapkan satu acuan per proses untuk membatasi beban analisis.
Pengguna menyetujui unggahan dan hasil sementara, tidak masuk katalog, dengan
pembersihan otomatis untuk mengurangi storage. Pemeriksaan existing menemukan
default retensi hasil 24 jam dan cleanup hasil, tetapi cleanup tersebut tidak
menghapus SHP input asli. Scheduler deployment belum diverifikasi.
Pengguna menyetujui masa simpan unggahan dan hasil 24 jam setelah analisis
selesai. Layer acuan admin tidak ikut dibersihkan. Detail lifecycle kegagalan
dan unggahan terbengkalai masih perlu dituntaskan.
Pengguna menyetujui peta irisan, rincian per objek, dan rekap per kategori,
dengan label otomatis untuk objek tanpa atribut serta satuan titik/garis/area
yang terpisah. Pengguna mengecualikan pelaporan bagian di luar cakupan acuan
dari scope, lalu menyetujui admin memilih kolom kategori dan atribut acuan
yang ditampilkan dalam hasil.
Pengguna meminta tambahan unduhan SHP, sehingga format hasil mencakup GeoJSON,
CSV, dan SHP. Kemasan ZIP dengan dataset SHP terpisah per keluarga geometri
diusulkan untuk hasil campuran. Pengguna menetapkan layer acuan hanya polygon
untuk tahap sekarang; unggahan tetap mendukung semua jenis geometri.
Jawaban “ya” ditafsirkan mengikuti rekomendasi menerima acuan tumpang tindih,
menampilkan kategori terkait dan penanda, serta menjelaskan bahwa persentase
antar kategori dapat melebihi 100%. Penafsiran disampaikan kepada pengguna.
Pengguna menyebut unggahan umumnya sedikit, dengan batas yang diinginkan pada
skala ribuan fitur. Pengguna kemudian menyetujui batas awal 5.000 fitur sumber
per unggahan yang dapat dikonfigurasi; kelebihan ditolak, bukan dipotong.
Angka ini bukan hasil benchmark.
Batas kompleksitas geometri serta ukuran berkas perlu ditentukan terpisah.
Pengguna menetapkan akses untuk pengguna login maupun tamu tanpa akun.
Pengguna menyetujui akses tamu dari browser yang sama; tautan berbagi lintas
perangkat tidak diperlukan. Retensi tetap 24 jam. Pengaitan hasil pengguna
login dengan akun masih usulan dan bukan klaim autentikasi existing.
Pengguna menyetujui penolakan geometri tidak valid atau CRS tidak dikenali,
dengan pesan jelas dan tanpa perbaikan/penghapusan fitur diam-diam.
Rencana dibersihkan dari pertanyaan/usulan lama yang sudah tergantikan.
Pengguna mengonfirmasi rangkuman scope sebagai dasar desain teknis berikutnya.
Draft: [Desain teknis](../plans/pola-ruang-intersect-technical-design.md).
Model Layer/UploadSession/AnalysisResult/AnalysisRequest sudah diperiksa.
Draft mencatat komponen, kontrak konseptual, lifecycle, geometri, dan kriteria
verifikasi; proposal teknis tidak dianggap persetujuan implementasi.
Pengguna menetapkan acuan memakai layer existing agar SHP publikasi dan analisis
tidak diduplikasi. Upload admin khusus acuan tidak diperlukan. Pertanyaan
berikutnya tentang katalog sudah dijawab: layer sumber tetap tampil sesuai
publikasi, konfigurasi acuan tidak membuat duplikat katalog. Plan, draft teknis,
dan glossary diperbarui untuk menggantikan asumsi awal menyembunyikan sumber.
Pengguna menyetujui hasil selesai tetap hingga TTL, proses baru memakai acuan
terbaru saat mulai dieksekusi, dan hasil mencantumkan waktu/versi acuan.
Pengguna menyetujui union per kategori per objek dalam rekap tanpa menghilangkan
rincian pasangan fitur sumber. Antarkategori dan antarobjek tetap independen.
Pengguna menyetujui retensi 24 jam untuk upload tak dijalankan (sejak upload
selesai) dan job gagal (sejak gagal); job aktif tidak dibersihkan sebagai input
terbengkalai. Pengguna menyetujui denominator persentase luas/panjang terhadap
keseluruhan objek unggahan, tanpa menambahkan laporan bagian di luar cakupan.
Pengguna menyetujui kategori kosong/null tetap dilaporkan sebagai “Kategori
belum diisi” dengan metrik dan peringatan. Kriteria verifikasi diperbarui.
Perilaku utama produk sudah disepakati; rincian implementasi yang belum final
tetap ditandai pada draft teknis. ADR sumber bersama:
[0006](../adr/0006-analysis-references-reuse-published-layer-sources.md).
Pada tahap interview tersebut belum ada perubahan kode aplikasi atau pengujian runtime.

Pengguna menyetujui guard penghapusan sumber: tolak selama terdaftar sebagai
acuan atau dipakai job aktif; lepas konfigurasi dan tunggu job selesai sebelum
hapus. Hasil selesai tetap hingga TTL. Kriteria verifikasi diperluas untuk
penghapusan sumber dan race dengan penerimaan job.

Pengguna menyetujui satu ZIP berisi tepat satu dataset SHP dan berkas
pendampingnya. Multi-dataset ditolak dengan instruksi upload terpisah; batas
5.000 fitur tetap berlaku. Rencana dan kriteria verifikasi diperbarui, termasuk
pemisahan kemampuan geometri mesin dari batas representasi format SHP.


## Penyelesaian implementasi — 2026-09-13

Panduan final: [Analisis SHP terhadap acuan](../features/reference-analysis.md).
Desain teknis diperbarui menjadi keputusan implementasi final.

- 70 pengujian lulus: test_reference_analysis.py, test_intersection_area.py,
  test_intersection_area_api.py, test_overlay_operations.py (37 warning existing).
- TypeScript --noEmit lulus pada geoportal dan dashboard; lint terarah geoportal
  lulus. Lint dashboard tidak dapat mulai karena @rushstack/eslint-patch gagal
  mengenali ESLint 9.39.4, sehingga tidak diklaim lulus. Detector UI kedua
  komponen baru tidak menemukan masalah mekanis.
- Migrasi 0011 di-autogenerate dari SQLModel, diuji pada SQLite terisolasi dan
  PostgreSQL terisolasi dari base sampai head. Alembic check database penuh
  menemukan drift nullable/index tabel lama; tidak ada perubahan drift pada
  empat tabel fitur baru. Drift lama tidak diperbaiki dalam scope ini.
- Browser Geoportal nyata dengan PostgreSQL dan worker Celery (broker memory
  terisolasi): ZIP SHP tanpa atribut bisnis, satu acuan, polling hingga done,
  tiga kategori termasuk nilai kosong, versi sumber, peta difokuskan ke bbox,
  tiga format unduhan berhasil; GeoJSON dan integritas ZIP diverifikasi.
- Tampilan desktop 1440x1000 dan mobile 390x844 diperiksa. Basemap provider
  existing menampilkan permintaan API key pada lingkungan uji; overlay hasil
  tampil. Verifikasi bukan audit konfigurasi provider/deployment produksi.
- DELETE layer acuan melalui router async nyata + PostgreSQL mengembalikan 409.
  Test lifecycle mencakup pelepasan konfigurasi, pin job, penghapusan sumber
  setelah terminal, hasil tetap bisa diunduh, TTL dan retry cleanup parsial.
- graphify update . selesai pada ketiga repositori (AST-only).

Batas bukti: belum benchmark dataset acuan produksi atau browser dekat batas
250 MiB, belum menguji deployment broker jaringan/prefork dengan beban paralel,
dan belum memverifikasi login terhadap layanan usermanagement produksi.
Angka kapasitas adalah batas awal, bukan SLA. Runtime browser memakai database,
berkas dan otorisasi development terisolasi. Tidak ada commit/push/deployment
atau perubahan database layanan pengguna.

Dialog admin juga diuji melalui browser dalam harness komponen terisolasi: membaca konfigurasi, mengubah nama/kategori, menyimpan (PUT 200), melepas, dan memasang kembali acuan berhasil terhadap API PostgreSQL nyata. Harness memakai komponen dan tileApi asli, tanpa mengklaim verifikasi login/menu dashboard penuh.

Perbandingan metadata PostgreSQL yang dibatasi pada empat tabel fitur menghasilkan nol drift; git diff --check ketiga repositori lulus.
