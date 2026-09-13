---
status: accepted
---

# Acuan analisis menggunakan sumber layer existing

Acuan analisis merujuk layer existing dan menggunakan sumber SHP yang sama
dengan publikasi, tanpa upload atau penyimpanan SHP kedua. Pengguna memilih
pendekatan ini untuk menghindari duplikasi data dan storage; konfigurasi acuan
hanya menentukan kelayakan analisis, kategori, serta atribut keluaran.

Menjadikan layer sebagai acuan tidak mengubah status publikasinya dan tidak
menambahkan entri katalog baru. Pendekatan ini menggantikan interpretasi awal
bahwa layer sumber harus disembunyikan dari katalog. Input dan hasil sementara
pengguna tetap memiliki lifecycle tersendiri.

Konsekuensinya, resolver geometri analisis harus mampu membaca sumber layer
yang sama; keberadaan tile/WMS saja bukan bukti tersedianya geometri analitis.
Pengguna menyetujui penghapusan sumber ditolak selama masih terdaftar sebagai
acuan atau dipakai job aktif; admin harus melepas konfigurasi acuan dan menunggu
job aktif selesai. Hasil selesai tetap tersedia hingga TTL setelah sumber
dihapus. Proses baru memakai acuan terbaru saat eksekusi dimulai, sedangkan
hasil selesai tidak dihitung ulang. Mekanisme konsistensi job masih perlu dirinci.

Scope: [Rencana](../plans/pola-ruang-intersect-workflow.md).
Progress: [Catatan keputusan](../progress/pola-ruang-intersect-workflow.md).
