"""Temporary, authorized local access to an Upload API artifact source."""

import asyncio
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from app.infrastructure.services.upload_artifact_client import UploadArtifactClient


@asynccontextmanager
async def artifact_source_context(
    final_path: Optional[str],
    filename: Optional[str],
    authorization: Optional[str],
    reference: str,
) -> AsyncIterator[Optional[Path]]:
    """Yield a readable source path, granting and leasing artifact-backed files."""
    if not final_path:
        yield None
        return
    if not final_path.startswith("artifact://"):
        path = Path(final_path)
        yield path if path.exists() else None
        return
    artifact_id = final_path.removeprefix("artifact://")
    # ponytail: cache local dulu seperti getinfo_layer._source_context; add when
    # cache eviction/per-tenant isolation dibutuhkan
    cache_dir = Path(os.getenv("ARTIFACT_CACHE_DIR", "/app/data/artifacts"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{artifact_id}{Path(filename or 'source').suffix}"
    if cached.exists():
        yield cached
        return

    if not authorization:
        raise PermissionError("Authorization is required to read an artifact-backed layer source")

    client = UploadArtifactClient()
    grant_id = await asyncio.to_thread(client.create_user_grant, artifact_id, authorization)
    lease = await asyncio.to_thread(
        client.acquire_lease,
        artifact_id,
        grant_id,
        f"{reference}:{uuid.uuid4()}",
    )
    lease_id = str(lease["lease_id"])
    try:
        with client.materialize(artifact_id, filename or "artifact.bin") as source:
            try:
                shutil.copyfile(source, cached)
            except Exception:
                pass  # gagal cache tidak boleh menyembunyikan hasil source
            yield cached if cached.exists() else source
    finally:
        try:
            await asyncio.to_thread(client.release_lease, artifact_id, lease_id)
        except Exception:
            # The source operation has already completed; a failed cleanup must
            # not hide its result. Upload API lease expiry remains the fallback.
            pass
