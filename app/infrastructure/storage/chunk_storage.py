import shutil
from pathlib import Path

from app.core.config import settings


class ChunkStorage:
    def __init__(self, upload_id: str):
        self.upload_id = upload_id
        self.session_dir: Path = settings.CHUNKS_DIR / upload_id

    def ensure_dir(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def write_chunk(self, chunk_index: int, data: bytes) -> None:
        part_path = self.session_dir / f"{chunk_index}.part"
        part_path.write_bytes(data)

    def get_received_size(self) -> int:
        """Returns total bytes of all part files currently on disk."""
        return sum(p.stat().st_size for p in self.session_dir.glob("*.part"))

    def assemble(self, dest_path: Path, part_count: int) -> None:
        """Concatenates all .part files in order then removes the chunk directory."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as out:
            for i in range(part_count):
                part = self.session_dir / f"{i}.part"
                out.write(part.read_bytes())
        shutil.rmtree(self.session_dir)

    def cleanup(self) -> None:
        if self.session_dir.exists():
            shutil.rmtree(self.session_dir)
