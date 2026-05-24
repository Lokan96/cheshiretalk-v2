from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "CheshireTalk v2"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = Field(default=False, alias="CT_DEBUG")
    SECRET_KEY: str = Field(default="change-me-in-production", alias="CT_SECRET_KEY")
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    MAX_ROOMS: int = Field(default=100, alias="CT_MAX_ROOMS")
    MAX_PARTICIPANTS_PER_ROOM: int = Field(default=10, alias="CT_MAX_PARTICIPANTS")
    DEFAULT_ROOM_TTL: int = Field(default=600, alias="CT_DEFAULT_TTL")
    MIN_ROOM_TTL: int = 30
    MAX_ROOM_TTL: int = 86400
    REKEYING_THRESHOLD: int = Field(default=50, alias="CT_REKEY_THRESHOLD")
    REKEYING_TIMEOUT: int = Field(default=300, alias="CT_REKEY_TIMEOUT")
    RATE_LIMIT_MSG_PER_SEC: float = Field(default=10.0, alias="CT_RATE_LIMIT")
    RATE_LIMIT_BURST: int = Field(default=30, alias="CT_RATE_BURST")
    CORS_ORIGINS: list[str] = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
