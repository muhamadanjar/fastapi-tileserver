# Plan: Clean Architecture Fix (Phase 1)

> Related progress: [progress/clean-architecture-fix.md](../progress/clean-architecture-fix.md)

## Goal

Hilangkan pelanggaran arah dependensi (audit: 26 outward imports dari usecases/application + endpoint god-layer):

1. **Ports di domain** — use cases bergantung pada protocol (domain), bukan kelas infra konkret.
2. **Relokasi file salah tempat** — `core/mbtiles.py` → `infrastructure/`, `core/response.py` → `presentation/`.
3. **Shrink endpoint god-layer** (`layers.py` 1100L) — pindah orkestrasi ke use cases (fase 2).

## Scope (Phase 1)

- [x] Audit dependensi (selesai, lihat progress)
- [ ] `app/domain/ports.py` — Protocol untuk repos & services yang dipakai use cases
- [ ] retype 11 usecases → ports; injeksi opsional utk instantiasi internal (ChunkStorage, UploadArtifactClient, NominatimClient)
- [ ] relokasi `core/mbtiles.py`, `core/response.py` + update 3 file import
- [ ] verifikasi: scan import ulang + smoke import + pytest unit

## Prinsip

- Runtime behavior TIDAK berubah — ports = structural typing (duck typing), zero-risk.
- Endpoint tetap meng-instantiate repo konkret (composition root via Depends) — itu benar.
- Yang dilarang hanya: inner layer import outer layer concrete class.