import asyncio
import os
import uuid
from pathlib import Path
from typing import Optional

from app.core.exceptions import LayerSourceUnavailableError
from app.domain.models import Layer
from app.infrastructure.db.repository import UploadSessionRepository
from app.infrastructure.services.upload_artifact_client import UploadArtifactClient


async def resolve_layer_source_path(
    layer: Layer,
    session_repo: UploadSessionRepository,
    authorization: Optional[str] = None,
) -> Optional[Path]:
    """Resolve the local source file for a layer (downloads artifact:// when needed).

    Returns None when the layer has no upload session or the file is gone.
    Raises LayerSourceUnavailableError when a remote artifact cannot be materialized
    and no legacy artifact path exists.
    """
    if not layer.upload_session_id:
        return None
    session = await session_repo.get_by_id(layer.upload_session_id)
    if not session or not session.final_path:
        return None
    final_path = session.final_path
    if not final_path.startswith("artifact://"):
        path = Path(final_path)
        return path if path.exists() else None

    artifact_id = final_path.removeprefix("artifact://")
    cache_dir = Path(os.getenv("ARTIFACT_CACHE_DIR", "/app/data/artifacts"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / f"{artifact_id}{Path(session.filename or 'source').suffix}"
    if not destination.exists():
        client = UploadArtifactClient()
        try:
            with client.materialize(artifact_id, session.filename or "artifact.bin") as source:
                destination.write_bytes(source.read_bytes())
        except Exception as exc:
            if authorization:
                lease_id = None
                try:
                    grant_id = await asyncio.to_thread(
                        client.create_user_grant, artifact_id, authorization,
                    )
                    lease = await asyncio.to_thread(
                        client.acquire_lease,
                        artifact_id,
                        grant_id,
                        f"source:{layer.id}:{uuid.uuid4()}",
                    )
                    lease_id = str(lease["lease_id"])
                    with client.materialize(artifact_id, session.filename or "artifact.bin") as source:
                        destination.write_bytes(source.read_bytes())
                except Exception as renewal_exc:
                    legacy = legacy_artifact_path(session.id, session.filename)
                    if legacy:
                        return legacy
                    raise LayerSourceUnavailableError(
                        "File sumber artifact tidak tersedia."
                    ) from renewal_exc
                finally:
                    if lease_id:
                        try:
                            await asyncio.to_thread(client.release_lease, artifact_id, lease_id)
                        except Exception:
                            pass
            else:
                legacy = legacy_artifact_path(session.id, session.filename)
                if not legacy:
                    raise LayerSourceUnavailableError(
                        "File sumber artifact tidak tersedia."
                    ) from exc
                return legacy
    return destination


def legacy_artifact_path(session_id: str, filename: Optional[str]) -> Optional[Path]:
    if not session_id or not filename:
        return None
    root = Path(os.getenv("LEGACY_ARTIFACT_DIR", "/app/data/upload-artifacts"))
    for candidate in (
        root / "objects" / "uploads" / session_id / Path(filename).name,
        root / "uploads" / session_id / Path(filename).name,
    ):
        if candidate.is_file():
            return candidate
    return None