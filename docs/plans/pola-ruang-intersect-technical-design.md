# Desain teknis analisis terhadap acuan polygon

Status: diimplementasikan; keputusan produk pada [rencana alur](pola-ruang-intersect-workflow.md).
Progress: [pelaksanaan](../progress/pola-ruang-intersect-workflow.md).
Panduan: [fitur dan API](../features/reference-analysis.md).

## Arsitektur final

Konfigurasi AnalysisReference merujuk satu Layer existing. Keberadaan konfigurasi
mengaktifkan acuan; pelepasannya menonaktifkan pilihan analisis. Tidak menambah
entri katalog atau menyalin sumber publikasi. Loader mendukung berkas vektor
satu dataset, artifact yang dimaterialisasi sementara, dan fitur proyek survei.
Acuan wajib Polygon/MultiPolygon dengan kolom kategori yang tersedia.

AnalysisUpload menyimpan kepemilikan sesi browser, metadata dan expiry. Berkas
ZIP divalidasi lalu dinormalisasi ke GeoJSON privat; ZIP dan ekstraksinya dibuang.
ReferenceAnalysisJob menyimpan status, snapshot konfigurasi, versi isi sumber,
waktu dan hasil. ActiveAnalysisSource menjadi pin FK selama job aktif. Empat
model SQLModel melahirkan revisi 0011 melalui Alembic autogenerate.

API baru di /api/v1/analysis-workspace melayani upload, satu input + satu acuan,
status, pagination rincian, rekap dan ekspor. /api/v1/analysis-references/{layer_id}
melayani admin dengan pemeriksaan tiles.manage ke layanan otorisasi. Token acak
32 byte dari browser disimpan di localStorage, dikirim lewat X-Analysis-Session,
dan hanya hash-nya disimpan server. Akses ini sama untuk tamu dan pengguna login;
tidak menyinkronkan hasil antarperangkat atau lewat akun.

Worker Celery melakukan validasi ulang, pembacaan sumber terbaru, intersect dan
ekspor. Penerimaan job memakai advisory transaction lock PostgreSQL dan row lock;
FK pin dan guard API melindungi sumber. Hasil selesai tidak bergantung lagi pada
sumber. Cleanup Celery Beat setiap lima menit menangani TTL dan timeout; gagal
menghapus satu direktori tidak menghambat direktori lain, record dipertahankan
untuk retry. Worker dan API harus berbagi direktori data yang sama.

## Geometri dan metrik

Topologi 2D EPSG:4326 tanpa snapping/repair. Koordinat Z/M tidak digunakan.
Domain pengukuran 86°S–86°N, tanpa geometri melintasi antimeridian lebih dari
180°. Area EPSG:6933; panjang segmen geodesik WGS84; titik memakai jumlah unik.
Mesin mendukung Point/LineString/Polygon, Multi dan koleksi, sementara satu
SHP tetap mengikuti batas keluarga geometri format tersebut.

Rincian mempertahankan pasangan objek input dan fitur acuan. Label Objek N
tersedia ketika atribut input kosong. Kontak batas dipisahkan per dimensi;
kontak polygon tanpa area memiliki persentase area nol. Rekap melakukan union
per kategori/objek/dimensi; bagian interior mengungguli boundary kategori sama.
Antarobjek dan antarkategori tetap independen. Penanda overlap berarti objek
memiliki cakupan acuan berulang pada dimensi tersebut, bukan geometri tumpang
tindih eksak setiap baris. Persentase memakai ukuran penuh objek input.
Tidak mengeluarkan sisa di luar cakupan atau vonis sesuai/tidak sesuai.

## Batas dan operasional

Nilai awal: 5.000 fitur input, ZIP 50 MiB, ekstraksi/hasil GeoJSON 250 MiB,
1 juta vertex input, 10 juta vertex acuan/hasil, 100.000 rincian,
4 job aktif global, 5 input per sesi, 200 input tersimpan global. Batas
merupakan pengaman konfigurasi, bukan klaim hasil benchmark kapasitas.
Timeout worker 900 detik dengan batas keras 930 detik; pending dibatasi 1 jam.
Retensi 24 jam sejak selesai/gagal, atau upload jika belum dijalankan.
Aktif tidak dibersihkan sebagai upload terbengkalai.

Geoportal menyediakan Upload SHP dan tetap mempertahankan Overlay & ukur lama.
Dashboard menyediakan Acuan analisis pada menu layer dengan permission gate
configureFields existing. Detail endpoint dan langkah penggunaan ada di panduan
fitur. Pengujian, batas verifikasi lingkungan, dan catatan migrasi dicatat pada
progress, bukan dianggap sebagai hasil uji beban produksi.
