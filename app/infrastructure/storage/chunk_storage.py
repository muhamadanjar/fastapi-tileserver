import shutil
from pathlib import Path

from app.core.config import settings


class ChunkStorage:
    def __init__(self):
        self.chunks_dir: Path = settings.CHUNKS_DIR

    def ensure_dir(self, session_id: str) -> None:
        (self.chunks_dir / session_id).mkdir(parents=True, exist_ok=True)

    def write_chunk(self, session_id: str, data: bytes, start_offset: int) -> None:
        path = self.chunks_dir / session_id / f"chunk_{start_offset}"
        path.write_bytes(data)

    def assemble_chunks(self, session_id: str, dest_path: Path) -> None:
        session_dir = self.chunks_dir / session_id
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        chunk_files = sorted(
            session_dir.glob("chunk_*"),
            key=lambda p: int(p.name.split("_", 1)[1])
        )
        with open(dest_path, "wb") as out:
            for chunk_file in chunk_files:
                out.write(chunk_file.read_bytes())
        shutil.rmtree(session_dir)

    def cleanup_chunks(self, session_id: str) -> None:
        session_dir = self.chunks_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)
