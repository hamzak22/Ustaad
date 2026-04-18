from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings) :
    SECRET_KEY : str
    ALGORITHM : str
    TOKEN_EXPIRATION_MINUTES: int
    DB_USERNAME: str
    DB_PASSWORD : str
    DB_HOST : str

    model_config = SettingsConfigDict(env_file='.env')

@lru_cache
def get_settings() :
    return Settings() 