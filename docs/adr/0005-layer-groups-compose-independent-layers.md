# Layer Group mengomposisikan Layer mandiri

Status: accepted (keputusan desain; implementasi belum dimulai)

Satu ZIP multi-SHP menghasilkan Layer mandiri per dataset, sementara Layer Group menyusun referensi Layer menjadi satu peta dengan kode/URL sendiri. Pengguna memilih komposisi ini agar setiap Layer tetap dapat digunakan sendiri dan dipakai beberapa group tanpa menggandakan atau melebur data. Urutan tampil dan visibility dimiliki keanggotaan group, sedangkan style dimiliki Layer sehingga perubahan style berlaku di seluruh group pemakainya.

Menghapus group mempertahankan seluruh Layer anggota. Menghapus Layer yang masih dipakai group ditolak sampai keanggotaannya dilepas secara eksplisit; ini mencegah penghapusan Layer diam-diam mengubah peta terbit.

Keputusan ini memperluas [kepemilikan style per Layer](0001-per-layer-sld-no-shared-styles.md): group tidak membuat salinan style sendiri. Format anggota group harus sama pada versi pertama; bentuk endpoint tiap format masih dibahas.

Related Plan: [Multi-SHP ZIP](../plans/multi-shapefile-layer-groups.md)
Related Progress: [Progress](../progress/multi-shapefile-layer-groups.md)
