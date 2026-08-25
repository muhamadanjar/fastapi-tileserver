
from typing import List, Union
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class CORSSettings(BaseSettings):

    """
    CORS configuration. Supports:
    - Nested: CORS__ALLOWED_ORIGINS
    - Legacy: CORS_ALLOW_ORIGINS, CORS_ALLOW_METHODS, CORS_ALLOW_HEADERS, CORS_ALLOW_CREDENTIALS
    Env string comma-separated (e.g. "http://a.com,http://b.com") di-parse jadi list.
    """

    # Union agar raw string dari env (comma-sep) diterima; validator normalisasi ke List[str]
    allowed_origins: Union[str, List[str]] = Field(
        default=["*"],
        validation_alias=AliasChoices("cors__allowed_origins", "cors_allowed_origins", "cors_allow_origins"),
    )
    allowed_methods: Union[str, List[str]] = Field(
        default=["*"],
        validation_alias=AliasChoices("cors__allowed_methods", "cors_allowed_methods", "cors_allow_methods"),
    )
    allowed_headers: Union[str, List[str]] = Field(
        default=["*"],
        validation_alias=AliasChoices("cors__allowed_headers", "cors_allowed_headers", "cors_allow_headers"),
    )
    allow_credentials: bool = Field(
        default=True,
        validation_alias=AliasChoices("cors__allow_credentials", "cors_allow_credentials", "cors_allowed_credentials"),
    )
