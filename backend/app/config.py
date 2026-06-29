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

    # Optional: URL to a daily-refreshed JSON feed of MCX SPAN margins per contract.
    # Format expected: [{"security_id":"459277","margin_per_lot":146000}, ...]
    # If unset OR fetch fails, the engine falls back to calibrated margin %.
    SPAN_MARGIN_FEED_URL: str = ""

    # Firebase Cloud Messaging — absolute path to the service-account JSON key.
    # Empty = push disabled (the register API still stores device tokens).
    FCM_KEY_PATH: str = ""

    # MCXCCL daily bullion warehouse-stock scrape (watch-only analytics).
    # Runs once/IST-day in the maintenance loop as an isolated subprocess.
    # Requires `playwright install chromium` in the backend venv on the server.
    BULLION_STOCK_ENABLED: bool = True
    MCXCCL_STOCK_PAGE_URL: str = "https://www.mcxccl.com/warehousing-logistics/stock-position"
    MCXCCL_FETCH_HOUR_IST: int = 18
    MCXCCL_FETCH_MINUTE_IST: int = 0
    MCXCCL_SCRAPE_TIMEOUT: int = 150   # seconds; subprocess killed past this

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def public_api_keys(self) -> set[str]:
        return {k.strip() for k in self.PUBLIC_API_KEYS.split(",") if k.strip()}


settings = Settings()


# Price normalisation to a common per-unit basis so spreads are comparable.
# Gold legs → ₹ per 10 g.  Silver legs → ₹ per kg (each silver pair is
# intra-silver so 1.0 keeps both legs on the same quote basis).
MULTIPLIERS = {
    "petal": 10.0, "guinea": 1.25, "ten": 1.0, "mini": 1.0,
    "gold": 1.0,                       # GOLD full (1 kg) quoted per 10 g, like ten/mini
    "silver": 1.0, "silverm": 1.0, "silvermic": 1.0,  # all silver quoted per kg
    "silver100": 100.0,                # SILVER100 quoted ~1/100 of per-kg basis → ×100 (client)
}

# Weight (grams) per single lot of each MCX contract
GRAMS_PER_LOT = {
    "petal": 1, "guinea": 8, "ten": 10, "mini": 100,
    "gold": 1000,        # GOLD full = 1 kg
    "silver": 30000,     # SILVER full = 30 kg
    "silverm": 5000,     # SILVER MINI = 5 kg
    "silvermic": 1000,   # SILVER MIC = 1 kg
    "silver100": 100,    # SILVER100 = 100 g
}

# Default max weight cap per pair if user leaves it blank
DEFAULT_MAX_WEIGHT_GRAMS = 1000
# Hard upper limit — client cannot set cap higher than this
MAX_ALLOWED_WEIGHT_GRAMS = 1000


def cycle_grams(pair: dict) -> int:
    """Gold weight (grams) of one full hedge cycle for this pair (big-side)."""
    return pair["big_lots"] * GRAMS_PER_LOT.get(pair["big"], 0)
