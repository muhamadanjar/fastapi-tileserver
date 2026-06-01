from typing import Optional, Dict, Any
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent.parent.parent


class DatabaseSettings(BaseSettings):
    url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("database__url", "database_url"),
    )
    type: str = Field(
        default="postgresql",
        validation_alias=AliasChoices("database__type", "database_type", "db_type"),
    )
    host: Optional[str] = Field(
        default="localhost",
        validation_alias=AliasChoices("database__host", "database_host", "db_host"),
    )
    name: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("database__name", "database_name", "db_name"),
    )
    port: Optional[str] = Field(
        default="5432",
        validation_alias=AliasChoices("database__port", "database_port", "db_port"),
    )
    user: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("database__user", "database_user", "db_user"),
    )
    password: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("database__password", "database_password", "db_password", "db_pass"),
    )

    pool_size: int = Field(default=10)
    max_overflow: int = Field(default=20)
    pool_recycle: int = Field(default=3600)
    pool_timeout: int = Field(default=30)
    connect_timeout: int = Field(default=10)
    debug: bool = Field(default=False)

    model_config = SettingsConfigDict(
        env_file=str(_BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    def get_database_url(self, sync: bool = True) -> str:
        if self.url and self.url.strip():
            url = self.url.strip()
            scheme = url.split("://")[0]
            dialect = scheme.split("+")[0]
            if sync:
                drivers = {"postgresql": "", "postgres": "", "mysql": "+pymysql", "sqlite": ""}
                return url.replace(scheme, dialect + drivers.get(dialect, ""), 1)
            else:
                drivers = {"postgresql": "+asyncpg", "postgres": "+asyncpg", "mysql": "+aiomysql", "sqlite": "+aiosqlite"}
                return url.replace(scheme, dialect + drivers.get(dialect, ""), 1)

        db_type = self.type.lower()
        password = quote_plus(self.password) if self.password else ""

        if db_type in ("postgresql", "postgres"):
            prefix = "postgresql" if sync else "postgresql+asyncpg"
            return f"{prefix}://{self.user}:{password}@{self.host}:{self.port}/{self.name}"

        elif db_type == "mysql":
            prefix = "mysql+pymysql" if sync else "mysql+aiomysql"
            return f"{prefix}://{self.user}:{password}@{self.host}:{self.port}/{self.name}"

        elif db_type == "sqlite":
            db_path = self.name or "database.db"
            prefix = "sqlite" if sync else "sqlite+aiosqlite"
            return f"{prefix}:///{db_path}"

        return ""

    @property
    def engine_kwargs(self) -> Dict[str, Any]:
        return {
            "echo": self.debug,
            "pool_pre_ping": True,
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_recycle": self.pool_recycle,
            "pool_timeout": self.pool_timeout,
        }

    @property
    def async_engine_kwargs(self) -> Dict[str, Any]:
        return {
            "echo": self.debug,
            "pool_pre_ping": True,
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_recycle": self.pool_recycle,
            "pool_timeout": self.pool_timeout,
        }
