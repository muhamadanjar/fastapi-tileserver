from pydantic_settings import BaseSettings
from pydantic import AliasChoices, Field
from typing import List, Union, Optional


class RedisSettings(BaseSettings):
    url:str = Field(default="")
    host:Optional[str] = Field()
    