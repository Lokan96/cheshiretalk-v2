from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_NAME: str = "CheshireTalk v2"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # CSWSH mitigation — origens permitidas para WebSocket
    ALLOWED_ORIGINS: List[str] = [
        "https://cheshiretalk-v2.onrender.com",
        "https://cheshiretalk-v2.vercel.app",
        "http://localhost:8000",
        "http://localhost:3000",
    ]
    
    # Rate limiting
    RATE_LIMIT_MSG_PER_MIN: int = 60
    RATE_LIMIT_CONN_PER_IP: int = 10
    
    # Room settings
    DEFAULT_MAX_PARTICIPANTS: int = 2
    DEFAULT_TTL_SECONDS: int = 600
    MAX_TTL_SECONDS: int = 3600
    
    class Config:
        env_file = ".env"


_settings = None

def get_settings():
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


settings = get_settings()
