# Fitur: Verifikasi Style SLD & Guard Duplikat Publish

Related: [Plan](../plans/sld-style-verification-and-duplicate-guard.md) · [Progress](../progress/sld-style-verification-and-duplicate-guard.md)

## Masalah yang diselesaikan

Peta WMS menjadi **abu-abu** setelah menyimpan style di editor, dan tidak ada
umpan balik di UI bahwa style benar-benar terpasang. Dua akar masalah:

1. **Warna hilang saat upload SLD 1.1.0** — GeoServer 3.0.0 menyimpan ulang SLD
   1.1.0 menjadi 1.0.0 dan dalam prosesnya membuang semua `se:SvgParameter`
   (`<sld:Fill/>` jadi kosong). Hasil render: abu-abu `#808080`.
2. **Duplikat publish** — file yang sama bisa dipublish sebagai `wms` dan `tile`
   (dua record), membingungkan klien.
3. **Tanpa feedback** — save sukses secara API tapi tidak ada konfirmasi bahwa
   style menjadi default layer di GeoServer.

## Cara kerja

### Konversi SLD 1.1.0 → 1.0.0 (perbaikan warna)

`app/core/style_utils.py` menambah `convert_sld_11_to_10(sld)`:

- SLD versi 1.1.0 ditulis ulang ke 1.0.0: prefix `se:` → `sld:`, elemen tanpa
  prefix diberi `sld:`, dan `SvgParameter` → `CssParameter`.
- SLD yang sudah 1.0.0 dikembalikan apa adanya (idempoten, nol biaya).
- XML invalid ditolak (ValueError) sebelum dikirim.

Dipanggil di `GeoServerService.upsert_style` — satu titik untuk semua alur
simpan (mode `simple` maupun mode `sld`), sehingga **penyimpanan berikutnya
otomatis aman**; layer yang sudah terlanjur rusak tinggal disave ulang.

### Verifikasi pasca-simpan

`put_layer_style` (endpoint API) setelah upload + set default memanggil
`GeoServerService.get_default_style(layer_name)` dan membandingkan
`defaultStyle.name` dengan `{workspace}:{layer_id}`. Response `PUT .../styles`
kini menyertakan:

- `style_verified: bool | null` — `true` bila default style cocok, `false` bila
  tidak, `null` bila GeoServer tidak terjangkau (mis. offline).
- `default_style_name: str | null` — nilai yang sebenarnya terpasang.

### Guard duplikat publish

`publish_to_geoserver` menolak dengan **409 Conflict** bila layer GeoServer
`{workspace}:{slugify(filename)}` sudah dimiliki record lain (id layer berbeda).
Record `wms` dan `tile` untuk file yang sama tidak bisa lagi dibuat dua kali.

### UI feedback

Panel style WMS menampilkan:

- Layer target GeoServer tempat style akan dipasang (`{workspace}:{layer_id}`).
- Konteks bahwa ini WMS (bukan tile biasa).
- Banner hasil verifikasi: `Style saved & verified on GeoServer` bila
  `style_verified === true`, atau `saved but not confirmed` bila tidak.

## Cara pakai

1. Buka detail layer (tipe WMS) → panel style → edit SLD → **Save**.
2. Perhatikan banner verifikasi; bila "verified", style terpasang sebagai
   default layer dan render WMS memakai warna SLD.
3. Cache tile WMS dibypass lewat query `_v=<timestamp>` yang ditambahkan panel.

## Verifikasi

- `venv/bin/python scripts/selfcheck_style_verify.py` → `OK: 6 checks passed`
  (konversi SLD + logika verifikasi default style).
- Uji manual: re-save style → GET `rest/workspaces/tileserver/styles/{name}.sld`
  harus memuat `CssParameter name="fill"` dengan warna; GetMap WMS menampilkan
  warna (bukan `#808080`).

## Catatan

- GeoServer 3.0.0 tidak bisa menyimpan SLD 1.1.0 dengan warna utuh — konversi
  sisi klien adalah perbaikan yang andal; tidak ada opsi konfigurasi server
  yang ditemukan.
- Style layer yang sudah rusak (tersimpan tanpa warna) tidak dipatch otomatis;
  cukup simpan ulang dari editor — `upsert_style` kini mengirim versi 1.0.0.