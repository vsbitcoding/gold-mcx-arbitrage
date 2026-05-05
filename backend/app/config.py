from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DHAN_CLIENT_ID: str = ""
    DHAN_ACCESS_TOKEN: str = ""
    DHAN_TOTP_SECRET: str = ""
    DHAN_MPIN: str = ""

    APP_SECRET_KEY: str = "change-me"
    TRADING_MODE: str = "paper"

    # Public API keys (comma-separated). Each key authorises a /api/v1/* client.
    PUBLIC_API_KEYS: str = ""

    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD_HASH: str = ""

    DATABASE_URL: str = "sqlite:///./arbi.db"

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    PETAL_SECURITY_ID: str = ""
    GUINEA_SECURITY_ID: str = ""
    TEN_SECURITY_ID: str = ""
    MINI_SECURITY_ID: str = ""

    EXCHANGE_SEGMENT: str = "MCX_COMM"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def public_api_keys(self) -> set[str]:
        return {k.strip() for k in self.PUBLIC_API_KEYS.split(",") if k.strip()}


settings = Settings()


MULTIPLIERS = {"petal": 10.0, "guinea": 1.25, "ten": 1.0, "mini": 1.0}

# Gold weight (grams) per single lot of each MCX contract
GRAMS_PER_LOT = {"petal": 1, "guinea": 8, "ten": 10, "mini": 100}

# Default max weight cap per pair if user leaves it blank
DEFAULT_MAX_WEIGHT_GRAMS = 1000
# Hard upper limit — client cannot set cap higher than this
MAX_ALLOWED_WEIGHT_GRAMS = 1000


def cycle_grams(pair: dict) -> int:
    """Gold weight (grams) of one full hedge cycle for this pair (big-side)."""
    return pair["big_lots"] * GRAMS_PER_LOT.get(pair["big"], 0)
