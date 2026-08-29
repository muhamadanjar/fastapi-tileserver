# Impor shapefile ke PostGIS

Related Plan: [Shapefile import to PostGIS](../plans/shapefile-postgis-import.md)
Progress Archive: [shapefile-postgis-import](../progress/shapefile-postgis-import.md)

## Ringkasan

Upload ZIP shapefile menyiapkan sumber untuk dua proses yang independen. Proses tiling/publish GeoServer lama tetap dimulai melalui aksi `Process`, sedangkan aksi `Kirim ke PostGIS` memanggil endpoint impor dan membuat task Celery. Worker mengimpor setiap dataset shapefile lengkap ke tabel dinamis terpisah dalam schema PostgreSQL `geodata`. Keberhasilan atau kegagalan impor tidak mengubah lifecycle tiling yang sudah ada.

Fitur berlaku untuk seluruh metode upload:

- upload langsung melalui `POST /api/v1/upload`;
- chunked upload setelah chunk terakhir diterima;
- artifact handoff melalui `POST /api/v1/uploads/artifact`.

Selesainya upload tidak otomatis menjalankan impor. Format selain ZIP shapefile tetap memakai alur sebelumnya dan memiliki status impor `not_applicable`.

## Prasyarat

- Database aplikasi harus PostgreSQL.
- Extension PostGIS harus sudah terpasang dan dapat diakses oleh user database aplikasi.
- Migration harus dijalankan sampai revision `0007`; migration membuat schema `geodata` dan field tracking pada `upload_sessions`.
- Celery worker harus berjalan dengan konfigurasi broker aplikasi.

```bash
alembic upgrade head
celery -A app.workers.celery_app worker --loglevel=info
```

## Format ZIP

ZIP harus memuat satu atau lebih dataset shapefile. Dataset boleh berada dalam subfolder dan setiap `.shp` harus memiliki sidecar dengan basename yang sama.

```text
data_wilayah.zip
├── administrasi/
│   ├── batas_desa.shp
│   ├── batas_desa.dbf
│   ├── batas_desa.shx
│   └── batas_desa.prj
└── transportasi/
    ├── jalan.shp
    ├── jalan.dbf
    ├── jalan.shx
    ├── jalan.prj
    └── jalan.cpg   # opsional
```

Upload `.shp` tunggal ditolak. ZIP ditolak jika tidak memiliki `.shp`, salah satu dataset tidak memiliki sidecar wajib, CRS tidak dapat dibaca, dataset kosong, geometry rusak/kosong, atau satu dataset mencampur keluarga point/line/polygon.

## Tabel hasil impor

Nama setiap tabel dibentuk dari nama dataset yang disanitasi dan delapan karakter awal `layer_id`:

```text
geodata.batas_desa_a1b2c3d4
```

Struktur tabel:

- `id BIGSERIAL PRIMARY KEY`;
- atribut DBF dengan nama SQL aman dan tipe PostgreSQL yang sesuai;
- `geom geometry(Geometry, 4326) NOT NULL`;
- GiST index pada `geom`.

Geometry dikonversi ke EPSG:4326. CRS asal, encoding, bbox, jumlah feature, keluarga geometry, dan pemetaan nama atribut asli ke nama kolom disimpan di `layers.file_metadata.postgis`.

Worker menulis setiap dataset ke staging table `geodata._import_<upload_id>_<n>` per batch, membuat index, lalu memublikasikan seluruh staging table dalam satu transaksi rename. Tabel final tidak terlihat dalam keadaan setengah terisi. Retry mendeteksi seluruh tabel final yang sudah ada dan menyelesaikan tracking tanpa mengimpor ulang.

## Memantau status

Setelah upload ZIP selesai, mulai impor secara eksplisit:

```http
POST /api/v1/uploads/{upload_id}/import
```

Endpoint menerima upload berstatus `uploaded` atau `done`, memastikan ZIP/artifact sumber masih tersedia, lalu mengembalikan `202 Accepted` dengan task ID Celery. Pemanggilan kedua setelah proses dimulai ditolak dengan `409 Conflict`.

Gunakan endpoint status upload yang sudah ada:

```http
GET /api/v1/uploads/{upload_id}/status
```

Contoh bagian respons impor:

```json
{
  "import": {
    "status": "processing",
    "task_id": "bbf42b8f-91ad-4a08-9bda-f9808c64e886",
    "schema": "geodata",
    "table": "batas_desa_a1b2c3d4",
    "processed_rows": 25000,
    "total_rows": 100000,
    "progress_percent": 25.0,
    "row_count": null,
    "tables": [],
    "error": null,
    "imported_at": null
  }
}
```

Ketika selesai, `tables` berisi seluruh hasil. Setiap item menyertakan `schema`, `table`, `geometry_family`, `row_count`, dan `bbox`; `row_count` pada level proses adalah total seluruh tabel.

Status yang mungkin:

- `not_applicable`: impor belum dimulai (untuk ZIP) atau format tidak mendukung impor shapefile;
- `pending`: task sudah masuk antrean;
- `processing`: worker sedang memvalidasi atau menulis batch;
- `completed`: tabel final dan Layer tersedia;
- `failed`: validasi atau proses database gagal;
- `cancelled`: task dibatalkan pengguna.

## Retry dan pembatalan

Retry manual hanya tersedia setelah status `failed` dan memakai sumber serta nama tabel yang sama:

```http
POST /api/v1/uploads/{upload_id}/import/retry
```

Task dengan status `pending` atau `processing` dapat dibatalkan:

```http
DELETE /api/v1/uploads/{upload_id}/import
```

Pembatalan me-revoke task Celery dan membersihkan staging table. Endpoint tersebut tidak menghapus tabel final dari impor yang sudah selesai.

## Registrasi dan penghapusan Layer

Impor sukses membuat atau memperbarui record Layer dengan ID yang sudah dialokasikan upload. Sebelum tiling/publish, Layer memakai:

- `layer_type = postgis`;
- `tile_url_template = ""`;
- `is_active = false`;
- `is_visible = false`.

Tiling atau publish berikutnya dapat mengubah tipe dan URL Layer, tetapi metadata `file_metadata.postgis` tetap dipertahankan.

`GET /api/v1/layers/{layer_id}/delete-preview` menampilkan seluruh tabel PostGIS yang akan dihapus. `DELETE /api/v1/layers/{layer_id}` menjatuhkan seluruh tabel tersebut dalam satu transaksi terlebih dahulu. Jika drop gagal, record Layer dan file lain tidak dihapus sehingga operasi aman untuk diulang.

## Konfigurasi

| Variabel | Default | Fungsi |
|---|---:|---|
| `SHP_IMPORT_MAX_UNCOMPRESSED_BYTES` | `1073741824` | Batas total ukuran ZIP setelah ekstraksi (1 GiB) |
| `SHP_IMPORT_MAX_FEATURES` | `1000000` | Batas total feature seluruh dataset dalam ZIP |
| `SHP_IMPORT_BATCH_SIZE` | `5000` | Jumlah feature per batch dan interval progress |
| `SHP_IMPORT_MAX_COMPRESSION_RATIO` | `200` | Batas rasio kompresi untuk deteksi ZIP bomb |

## Keamanan dan kegagalan

Worker menolak path traversal, symlink, entry terenkripsi, nama member duplikat, ZIP bomb, dan identifier database yang tidak aman. SQL identifier dibentuk server-side dan dikutip; nilai atribut dikirim sebagai parameter query.

Kesalahan validasi deterministik langsung berstatus `failed`. Gangguan database sementara dapat di-retry Celery sampai tiga kali. Direktori ekstraksi temporer dan staging table dibersihkan saat gagal, sedangkan ZIP/artifact sumber tetap mengikuti lifecycle upload agar masih tersedia untuk retry, tiling, atau GeoServer.
