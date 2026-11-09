from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_token: str = Field(default="change-me", alias="APP_TOKEN")
    # Optional shared secret for the encrypted-bearer scheme (ENC-BEARER v1):
    # AES-256-GCM key material = SHA-256(UTF-8 of this value). Unset ⇒ `enc:`
    # bearers are rejected and clients must send the plain token.
    app_token_enc_key: str | None = Field(default=None, alias="APP_TOKEN_ENC_KEY")
    app_name: str = Field(default="market-data-server", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=False, alias="LOG_JSON")

    yf_max_threads: int = Field(default=4, ge=1, le=32, alias="YF_MAX_THREADS")
    bulk_max_symbols: int = Field(default=25, ge=1, le=100, alias="BULK_MAX_SYMBOLS")
    bulk_intraday_symbols: int = Field(default=5, ge=1, le=100, alias="BULK_INTRADAY_SYMBOLS")
    ohlcv_page_size_max: int = Field(default=5000, ge=1, alias="OHLCV_PAGE_SIZE_MAX")

    @property
    def is_prod(self) -> bool:
        return self.app_env.lower() == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
