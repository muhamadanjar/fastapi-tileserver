# Analisis objek unggahan terhadap pola ruang

Status: rangkuman scope disetujui pengguna; desain teknis sedang dirinci.

Desain: [Draft desain teknis](pola-ruang-intersect-technical-design.md)

Progress: [Catatan sesi](../progress/pola-ruang-intersect-workflow.md)

## Kebutuhan awal

Geoportal memilih layer pola ruang dari tileserver sebagai data acuan, menerima
SHP baru sebagai objek analisis, dan menjelaskan kategori pola ruang yang
beririsan dengan objek tersebut. Scope awal yang disepakati adalah informasi
irisan, bukan vonis sesuai/tidak sesuai. Acuan dapat berupa layer polygon lain,
tidak terbatas pada pola ruang.

## Konfirmasi kebutuhan

- Pengguna menyetujui satu ZIP berisi tepat satu dataset SHP beserta berkas
  pendampingnya per unggahan, dengan maksimal 5.000 fitur sumber. Jika ZIP
  berisi beberapa dataset SHP, unggahan ditolak dengan pesan untuk mengunggah
  masing-masing dataset secara terpisah; tidak memilih atau menggabung diam-diam.
  Dukungan jenis geometri berlaku pada dataset yang dapat direpresentasikan
  format input, bukan jaminan satu SHP dapat mencampur semua tipe geometri.
- Pengguna menyetujui penghapusan layer sumber ditolak selama masih terdaftar
  sebagai acuan atau dipakai job aktif. Admin harus melepas konfigurasi acuan
  dan menunggu job aktif selesai sebelum menghapus sumber. Hasil selesai
  tetap tersedia hingga TTL walaupun sumber kemudian dihapus.
- Pengguna menyetujui kategori acuan kosong tetap dilaporkan sebagai
  “Kategori belum diisi”, dengan metrik dan peringatan. Geometri hasil tidak
  dibuang dan kategori tidak ditebak. Ini berbeda dari tidak adanya irisan.
- Pengguna menyetujui persentase luas/panjang memakai ukuran penuh objek
  unggahan sebagai denominator, bukan hanya bagian yang ditemukan beririsan.
  Keputusan ini tidak menambah keluaran bagian di luar cakupan. Persentase
  dapat berjumlah kurang dari 100%; tumpang tindih antarkategori mengikuti
  kebijakan yang telah disepakati.
- Pengguna menyetujui upload yang tidak pernah dianalisis dihapus 24 jam
  setelah upload selesai; analisis gagal beserta input/hasil parsial dihapus
  24 jam setelah gagal. Input job aktif tidak dibersihkan sebagai upload
  terbengkalai. Batas waktu job macet tetap perlu dirancang.
- Pengguna menyetujui deduplikasi rekap dalam kategori yang sama per objek
  unggahan: bagian irisan yang sama dihitung sekali, sementara rincian tetap
  mempertahankan hubungan dengan tiap fitur acuan. Ini bukan deduplikasi antar
  objek unggahan; kategori berbeda tetap independen.
- Pengguna menyetujui analisis baru memakai acuan terbaru saat mulai dieksekusi.
  Hasil selesai tidak dihitung ulang saat sumber berubah, tetap tersedia hingga
  TTL, dan mencantumkan waktu atau versi acuan yang digunakan. Cara menjamin
  pembacaan konsisten selama perubahan sumber masih detail implementasi.
- Acuan analisis merujuk layer tileserver yang sudah ada. Pengguna memilih
  pemakaian sumber SHP yang sama untuk publikasi dan analisis agar tidak ada
  unggahan atau salinan SHP kedua. Tidak diperlukan upload admin khusus acuan.
- Pengguna mengonfirmasi layer sumber tetap tampil sesuai pengaturan publikasi;
  konfigurasi acuan tidak membuat entri katalog tambahan. Ini memperjelas dan
  menggantikan pernyataan awal bahwa layer acuan tidak muncul di katalog.
- Pengguna menyetujui penolakan analisis jika geometri tidak valid atau CRS
  tidak diketahui/tidak dapat dikenali. Pesan harus menjelaskan masalah dan
  objek terkait jika relevan; tidak memperbaiki atau membuang fitur diam-diam.
- Analisis tersedia untuk pengguna login dan pengunjung tanpa akun; login
  bukan prasyarat upload/analisis. Pengguna menyetujui akses tamu cukup dari
  browser yang sama; berbagi tautan lintas perangkat tidak diperlukan.
  Usulan hasil pengguna login dikaitkan dengan akun belum dikonfirmasi secara
  terpisah. Pemulihan sesi tamu yang dihapus tidak termasuk kebutuhan yang
  sudah dinyatakan.
  Kedua jenis pengguna mengikuti retensi 24 jam yang sudah disepakati.
- Pengguna menyetujui maksimal 5.000 fitur sumber per unggahan, dapat
  dikonfigurasi. Unggahan yang melebihi batas ditolak dengan pesan jelas,
  bukan dipotong diam-diam. Ini bukan klaim kapasitas teruji.
  Batas ukuran berkas, total vertex, komponen Multi/koleksi, dan jumlah hasil
  tetap perlu dirancang agar satu fitur kompleks tidak melewati kendali beban.
- Jawaban “ya” pengguna ditafsirkan sebagai persetujuan rekomendasi untuk
  menerima polygon acuan yang saling tumpang tindih, menampilkan semua kategori
  terkait, dan menandai tumpang tindih. Rekap antar kategori dapat berjumlah
  lebih dari 100% karena bagian yang sama terkait dengan beberapa kategori;
  hasil harus menjelaskan ini dan tidak menyajikan jumlah tersebut sebagai
  cakupan unik. Deduplikasi dalam kategori yang sama mengikuti keputusan
  gabungan irisan per kategori per objek unggahan.
- Layer acuan admin dibatasi pada Polygon/MultiPolygon untuk tahap sekarang.
  Batasan ini tidak mengubah dukungan semua jenis geometri unggahan pengguna.
- Unduhan mencakup GeoJSON, CSV rincian/rekap, dan SHP; pengguna meminta SHP
  ditambahkan pada format GeoJSON dan CSV yang ditawarkan.
- Usulan kemasan SHP: satu ZIP dengan dataset terpisah per keluarga geometri
  (titik, garis, polygon), termasuk geometri kontak batas jika ada. Identitas
  objek asal tetap terhubung. Rincian pemetaan nama atribut dan komponen koleksi
  perlu dirancang dan diverifikasi saat implementasi.
- Admin memilih kolom kategori dan atribut acuan yang ditampilkan dalam hasil
  saat menyiapkan layer acuan analisis; pengguna menyetujui konfigurasi ini.
- Pengguna mengecualikan pelaporan bagian di luar cakupan acuan dari scope.
  Hasil berfokus pada irisan dan kontak batas. Jika tidak ada hasil, usulan
  pesan UI adalah “Tidak ditemukan irisan dengan layer acuan.” Tidak dibuat
  geometri sisa atau rekap kategori “di luar cakupan”.
- Pengguna menyetujui lifecycle sementara untuk unggahan dan hasil: tidak masuk
  katalog, dapat dilihat/diunduh, kemudian dibersihkan untuk membatasi storage.
  Riwayat permanen tidak diperlukan dalam alur ini. Pengguna menyetujui retensi
  unggahan dan hasil selama 24 jam setelah analisis selesai, lalu dihapus otomatis.
  Layer acuan admin tetap disimpan. Retensi upload tak dijalankan dan job gagal
  mengikuti keputusan di atas; penanganan proses macet masih perlu dirinci.
- Existing menyediakan cleanup hasil ephemeral dan snapshot dengan default
  `ANALYSIS_EPHEMERAL_TTL_HOURS=24`. `cleanup_ephemeral` menghapus file hasil,
  layer hasil, dan record analisis, bukan SHP input asli. Lifecycle input sementara
  harus dilengkapi dan pelaksanaan cleanup terjadwal harus diverifikasi saat
  implementasi; keberadaan task bukan bukti scheduler deployment aktif.
- Kebutuhan awal mencakup keduanya, tetapi setelah contoh konkret pengguna
  menyatakan informasi kategori pola ruang, luas, persentase, dan atribut terkait
  sudah cukup. Scope awal tidak memerlukan vonis sesuai/tidak sesuai.
- Unggahan dapat memiliki atribut atau tidak memiliki atribut pengguna;
  atribut bisnis dan kolom ID tidak boleh menjadi prasyarat intersect.
  Pengguna memperjelas bahwa “tanpa atribut” berarti isi atribut kosong,
  sedangkan geometri selalu ada; bukan permintaan dukungan paket SHP yang rusak.
  Mesin area saat ini menghasilkan ID per run jika kolom ID tidak dipilih
  (`app/analysis/intersection_area.py:52`). Keberadaan geometri tidak menjamin
  validitas atau CRS, sehingga validasi tetap wajib.
- Pengguna menyetujui peta irisan, tabel rincian per objek, dan rekap per
  kategori acuan. Objek tanpa atribut diberi label otomatis “Objek 1”,
  “Objek 2”, dan seterusnya. Jumlah titik, panjang garis, serta luas polygon
  ditampilkan terpisah agar satuannya tidak tercampur.
- Pengguna meminta semua tipe geometri, bukan polygon saja. Cakupan yang perlu
  ditangani meliputi Point/MultiPoint, LineString/MultiLineString,
  Polygon/MultiPolygon, serta GeometryCollection jika diterima oleh jalur input.
  Kebijakan pemecahan koleksi dan dimensi Z/M belum dirinci.
- Keluaran sesuai dimensi: titik mendapat kategori dan jumlah titik;
  garis mendapat kategori, panjang irisan, dan persentase panjang; polygon
  mendapat kategori, luas irisan, dan persentase luas. Detail denominator dan
  deduplikasi rekap perlu dirinci dalam desain teknis.
- Pengguna menerima rekomendasi kontak batas: tampilkan semua kategori yang
  bersentuhan dan tandai “pada batas”, tanpa memilih kategori secara arbitrer.
  Polygon yang hanya menyentuh batas dilaporkan sebagai kontak dengan luas
  irisan nol, terpisah dari hasil irisan berluas positif. Titik di batas dan
  garis mengikuti batas dapat terkait dengan lebih dari satu kategori.
  Rekap cakupan unik tidak boleh menjumlahkan kontak/pasangan secara naif.
  Presisi/toleransi kedekatan batas belum ditentukan; keputusan ini tidak
  menyatakan bahwa objek dekat batas otomatis dianggap menyentuh batas.
- Pengguna mengunggah SHP dan memilih layer acuan dari daftar khusus analisis
  yang dikonfigurasi admin. Hanya acuan terpilih dianalisis, tanpa menunggu
  tindakan admin. Ini memperbarui keinginan awal upload saja.
- Pengguna menolak usulan pemeriksaan otomatis terhadap seluruh acuan aktif.
  Pengguna menetapkan tepat satu layer acuan per proses untuk membatasi beban
  analisis. Pemeriksaan terhadap acuan lain dilakukan sebagai proses terpisah.
- Admin mengonfigurasi layer existing yang dapat digunakan untuk intersect atau
  query analisis lain, tanpa membuat layer baru atau mengubah publikasi sumber.
- Contoh acuan: peta pola ruang. Objek SHP unggahan diperiksa terhadap acuan
  tersebut dan informasi hasilnya langsung disajikan kepada pengguna.
- Pernyataan awal tentang aturan admin diperjelas: tanggung jawab admin yang
  sudah pasti adalah konfigurasi layer acuan. Informasi kategori acuan dan ukuran
  irisan cukup untuk scope awal; matriks penilaian tambahan tidak diperlukan.
- Usulan sebelumnya tentang halaman/profil pemeriksaan yang dipilih pengguna
  tidak diterima sebagai alur yang diinginkan.

## Bukti implementasi lokal

- Tileserver `app/analysis/intersection_area.py:159` menghitung irisan polygon
  per pasangan fitur, `area_m2`, `area_ha`, `pct_a`, dan `pct_b`.
- `app/usecases/overlay_analysis.py:510` memuat fitur survei terpublikasi,
  hasil analisis selesai, atau file lokal dari upload session. `artifact://`
  dikembalikan sebagai `None`; loader ini tidak mengambil geometri remote WMS/WFS.
- Geoportal `features/geoportal/components/analysis-tools-panel.tsx` memilih
  dua layer terdaftar, mengirim `calculate_area`, menampilkan preview, dan
  menyediakan simpan/unduh. Panel belum memiliki upload SHP atau rekap kategori.
- `app/analysis/overlay_operations.py:26` menangani titik-polygon dengan
  predicate `within` dan mempertahankan kolom sisi titik saja. Garis-polygon
  memakai clip dan mempertahankan kolom sisi garis. Jalur ini perlu diperluas
  untuk pelacakan kategori acuan per hasil; opsi area hanya untuk polygon.
- Referensi geoportal yang diperiksa:
  `/home/anjar/Development/base-project-apps/services/geoportal`.

Temuan berasal dari inspeksi kode lokal, bukan pengujian deployment atau SHP nyata.

## Rincian desain teknis yang masih perlu dituntaskan

- Sumber geometri acuan dan dukungan artifact, bentuk konfigurasi admin,
  kontrak API, dan pemisahan daftar acuan dari katalog peta.
- Akses hasil pengguna login dan sesi tamu pada endpoint hasil/unduhan.
- Batas byte, vertex, hasil, waktu proses, serta antrean dan concurrency.
- Retensi unggahan terbengkalai, pekerjaan gagal/macet, dan titik awal TTL.
- Denominator persentase, deduplikasi dalam kategori, identitas komponen Multi,
  koleksi, Z/M, pengukuran panjang, dan presisi kontak batas.
- Kemasan ekspor SHP dan pemetaan atribut tanpa kehilangan identitas sumber.
- Verifikasi integrasi upload → analisis → hasil/unduh → pembersihan.

Rincian ini belum menjadi keputusan arsitektur final. Tidak ada klaim kapasitas
5.000 fitur sebelum pengujian dengan geometri serta acuan yang representatif.

Tidak ada implementasi yang dimulai selama sesi penyelarasan kebutuhan.

Implementasi selesai: [panduan fitur](../features/reference-analysis.md). Batas verifikasi dicatat pada progress.
