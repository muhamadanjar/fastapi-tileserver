
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    PROJECT_NAME: str = "FastAPI Tileserver"
    API_V1_STR: str = "/api/v1"
    
    # Upload and Data Directories
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    UPLOAD_DIR: Path = BASE_DIR / "data" / "uploads"
    TILES_DIR: Path = BASE_DIR / "data" / "tiles"
    CHUNKS_DIR: Path = BASE_DIR / "data" / "chunks"

    # RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"

    # Chunked upload threshold in bytes (default 10 MB)
    CHUNK_UPLOAD_THRESHOLD: int = 10_485_760

    @property
    def SESSIONS_DB_URL(self) -> str:
        return f"sqlite:///{self.BASE_DIR / 'data' / 'sessions.db'}"

    @property
    def SESSIONS_DB_URL_ASYNC(self) -> str:
        return f"sqlite+aiosqlite:///{self.BASE_DIR / 'data' / 'sessions.db'}"
    
    # CORS
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Database (PostGIS)
    DB_USER: str = "postgres"
    DB_PASS: str = "postgres"
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    DB_NAME: str = "gis_db"
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")

settings = Settings()

# Ensure directories exist
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.TILES_DIR.mkdir(parents=True, exist_ok=True)
settings.CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
