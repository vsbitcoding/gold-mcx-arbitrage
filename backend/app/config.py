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

    # Premium-calc live inputs (isolated feed): XAU/USD via Deriv WS, USD/INR via TwelveData.
    PREMIUM_FEED_ENABLED: bool = True
    DERIV_APP_ID: str = "1089"
    # IB Gateway (paper login, headless on this server) — spot XAU/XAG in
    # real-time for free; COMEX/NYMEX futures once the account is funded and
    # subscribed. Deriv delisted frxXAUUSD/frxXAGUSD (27-Jul), IBKR replaced it.
    IBKR_ENABLED: bool = True
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 4002
    IBKR_CLIENT_ID: int = 21
    # International COMEX/NYMEX feed (own connection + clientId so it can never
    # disturb anything else). Subscriptions: COMEX L1 + NYMEX L1.
    IBKR_FEED_ENABLED: bool = True
    IBKR_FEED_CLIENT_ID: int = 22
    # Spot metals + crude come from the IBKR feed (client's choice, 30-Jul).
    # Flip IBKR_SPOTS_ENABLED off and FINNHUB_ENABLED on to roll back instantly.
    # MCX crude option chain with IV + greeks, via Dhan's REST option-chain
    # endpoint (the WebSocket tick stream carries no IV). Reuses the live feed's
    # cached token; Dhan allows one call per 3 s so the service polls every 5 s.
    # Angel One SmartAPI - the only source for NSE commodity (Dhan's API has no
    # such segment, IBKR does not list the contracts). Also supplies real-time
    # USD/INR. Credentials live in ~/.config/arbi-secrets/angelone.env.
    ANGEL_ENABLED: bool = True
    ANGEL_STATIC_IP: str = "34.180.20.239"   # Angel locks the key to this IP
    CRUDE_IV_ENABLED: bool = True
    IBKR_SPOTS_ENABLED: bool = True
    FINNHUB_ENABLED: bool = False
    TWELVEDATA_API_KEY: str = ""
    # Finnhub free WS (WTI + Brent crude for the app board). ONE connection per
    # key — this server must be the only consumer of this key.
    FINNHUB_API_KEY: str = ""

    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD_HASH: str = ""

    DATABASE_URL: str = "sqlite:///./arbi.db"

    # Secret for the TradingView paper-trade webhook. Empty = webhook disabled.
    # Value lives only in the server .env, never in git.
    WEBHOOK_TRADE_KEY: str = ""

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
    # Runs in the maintenance loop as an isolated subprocess. MCXCCL posts the
    # daily PDF with an irregular lag, so we start in the morning and retry
    # every MCXCCL_RETRY_HOURS until the stored data catches up to yesterday
    # (rather than one fragile daily attempt). Requires `playwright install
    # chromium` in the backend venv on the server.
    BULLION_STOCK_ENABLED: bool = True
    MCXCCL_FETCH_HOUR_IST: int = 9     # first attempt of the day (IST)
    MCXCCL_FETCH_MINUTE_IST: int = 0
    MCXCCL_RETRY_HOURS: int = 3        # re-attempt cadence while still behind yesterday
    MCXCCL_SCRAPE_TIMEOUT: int = 180   # seconds; subprocess killed past this (backfill day-1)
    MCXCCL_LOOKBACK_DAYS: int = 14     # how far back to look for the latest / backfill daily files
    # Browser overrides (optional). Leave blank → auto-detect (bundled Chromium,
    # then system Google Chrome/Chromium). Set channel="chrome" or an explicit
    # path if auto-detect ever picks the wrong one.
    MCXCCL_CHROME_CHANNEL: str = ""
    MCXCCL_CHROME_PATH: str = ""

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
    "elecmbl": 1.0,                    # electricity quoted per MWh; calendar legs 1:1
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
