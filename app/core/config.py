
from typing import List, Union
from functools import lru_cache
from pydantic import AnyHttpUrl, field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from app.config.database import DatabaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "FastAPI Tileserver"
    API_V1_STR: str = "/api/v1"

    # Upload and Data Directories
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    UPLOAD_DIR: Path = BASE_DIR / "data" / "uploads"
    TILES_DIR: Path = BASE_DIR / "data" / "tiles"
    CHUNKS_DIR: Path = BASE_DIR / "data" / "chunks"
    DOWNLOAD_DIR: Path = BASE_DIR / "data" / "download"
    MBTILES_DIR: Path = BASE_DIR / "data" / "mbtiles"

    # Database
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)

    # RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0", env="REDIS_URL")

    # GeoServer
    GEOSERVER_URL: str = Field(default="http://localhost:8080/geoserver", env="GEOSERVER_URL")
    GEOSERVER_USER: str = Field(default="admin", env="GEOSERVER_USER")
    GEOSERVER_PASSWORD: str = Field(default="geoserver", env="GEOSERVER_PASSWORD")
    GEOSERVER_WORKSPACE: str = Field(default="tileserver", env="GEOSERVER_WORKSPACE")

    # Chunked upload threshold in bytes (default 10 MB)
    CHUNK_UPLOAD_THRESHOLD: int = 10_485_760

    # Esri Download
    ESRI_MAX_WORKERS: int = Field(default=4, env="ESRI_MAX_WORKERS")
    ESRI_IGNORE_SSL: bool = Field(default=False, env="ESRI_IGNORE_SSL")
    ESRI_RESUME_CACHE_DIR: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent.parent / "data" / "esri_cache",
        env="ESRI_RESUME_CACHE_DIR",
    )
    ESRI_REQUEST_TIMEOUT: int = Field(default=15, env="ESRI_REQUEST_TIMEOUT")
    ESRI_DOWNLOAD_TIMEOUT: int = Field(default=180, env="ESRI_DOWNLOAD_TIMEOUT")
    ESRI_PROXY_URL: str = Field(default="", env="ESRI_PROXY_URL")
    ESRI_TOKEN: str = Field(default="", env="ESRI_TOKEN")

    # Upload session expiry in hours (default 24)
    UPLOAD_SESSION_EXPIRE_HOURS: int = Field(default=24, env="UPLOAD_SESSION_EXPIRE_HOURS")

    # CORS
    CORS_ALLOWED_ORIGINS: str = Field(default="*", env="CORS_ALLOWED_ORIGINS")
    CORS_ALLOWED_METHODS: str = Field(default="*", env="CORS_ALLOWED_METHODS")
    CORS_ALLOWED_HEADERS: str = Field(default="*", env="CORS_ALLOWED_HEADERS")
    CORS_ALLOW_CREDENTIALS: bool = Field(default=True, env="CORS_ALLOW_CREDENTIALS")

    def get_cors_origins(self) -> List[str]:
        if isinstance(self.CORS_ALLOWED_ORIGINS, str):
            return [i.strip() for i in self.CORS_ALLOWED_ORIGINS.split(",")]
        return self.CORS_ALLOWED_ORIGINS

    def get_cors_methods(self) -> List[str]:
        if isinstance(self.CORS_ALLOWED_METHODS, str):
            return [i.strip() for i in self.CORS_ALLOWED_METHODS.split(",")]
        return self.CORS_ALLOWED_METHODS

    def get_cors_headers(self) -> List[str]:
        if isinstance(self.CORS_ALLOWED_HEADERS, str):
            return [i.strip() for i in self.CORS_ALLOWED_HEADERS.split(",")]
        return self.CORS_ALLOWED_HEADERS

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        extra="allow",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

settings = get_settings()

# Ensure directories exist
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.TILES_DIR.mkdir(parents=True, exist_ok=True)
settings.CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.MBTILES_DIR.mkdir(parents=True, exist_ok=True)
settings.ESRI_RESUME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
