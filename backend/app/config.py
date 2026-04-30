from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DHAN_CLIENT_ID: str = ""
    DHAN_ACCESS_TOKEN: str = ""
    DHAN_TOTP_SECRET: str = ""
    DHAN_MPIN: str = ""

    APP_SECRET_KEY: str = "change-me"
    TRADING_MODE: str = "paper"

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


settings = Settings()


PAIRS = [
    {"name": "Petal-Guinea", "big": "petal", "small": "guinea", "big_lots": 8, "small_lots": 1},
    {"name": "Petal-Ten", "big": "petal", "small": "ten", "big_lots": 10, "small_lots": 1},
    {"name": "Petal-Mini", "big": "petal", "small": "mini", "big_lots": 100, "small_lots": 1},
    {"name": "Guinea-Ten", "big": "guinea", "small": "ten", "big_lots": 5, "small_lots": 4},
    {"name": "Guinea-Mini", "big": "guinea", "small": "mini", "big_lots": 25, "small_lots": 2},
    {"name": "Ten-Mini", "big": "ten", "small": "mini", "big_lots": 10, "small_lots": 1},
]

MULTIPLIERS = {"petal": 10.0, "guinea": 1.25, "ten": 1.0, "mini": 1.0}

# Gold weight (grams) per single lot of each MCX contract
GRAMS_PER_LOT = {"petal": 1, "guinea": 8, "ten": 10, "mini": 100}

# Default max weight cap per pair if user leaves it blank
DEFAULT_MAX_WEIGHT_GRAMS = 1000
# Hard upper limit — client cannot set cap higher than this
MAX_ALLOWED_WEIGHT_GRAMS = 1000


def cycle_grams(pair: dict) -> int:
    """Gold weight (grams) of one full hedge cycle for this pair (big-side)."""
    return pair["big_lots"] * GRAMS_PER_LOT[pair["big"]]
