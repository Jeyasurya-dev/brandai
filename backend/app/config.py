import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///brandgen.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRES_MIN", 60))
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        days=int(os.environ.get("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 7))
    )

    FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")

    # AI
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    AI_MODEL = os.environ.get("AI_MODEL", "gemini-3-flash")

    # Logo generation — reuses GEMINI_API_KEY (Google's Gemini Developer API
    # serves both the text model above and the Imagen image models below
    # via the same client and key; no second provider/key is introduced).
    IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "imagen-4.0-generate-001")

    # Trademark
    # provider options: "none" (honest unavailable state), "markerapi" (USPTO/US
    # only, via markerapi.com — requires an active subscription), "generic_rest"
    # (bring-your-own REST provider via TRADEMARK_API_BASE_URL/TRADEMARK_API_KEY)
    TRADEMARK_PROVIDER = os.environ.get("TRADEMARK_PROVIDER", "none")
    TRADEMARK_API_KEY = os.environ.get("TRADEMARK_API_KEY", "")
    TRADEMARK_API_BASE_URL = os.environ.get("TRADEMARK_API_BASE_URL", "")
    # markerapi.com authenticates via a username/password pair, not a bearer key
    TRADEMARK_API_USERNAME = os.environ.get("TRADEMARK_API_USERNAME", "")
    TRADEMARK_API_PASSWORD = os.environ.get("TRADEMARK_API_PASSWORD", "")

    # Domain
    # "rdap" is the default: it's the free, public, no-API-key IANA/ICANN RDAP
    # bootstrap (https://rdap.org) — real registry data, not fabricated, and
    # needs zero configuration. Set DOMAIN_PROVIDER=none to disable outbound
    # domain lookups entirely, or "generic_rest" to plug in a paid provider.
    DOMAIN_PROVIDER = os.environ.get("DOMAIN_PROVIDER", "rdap")
    DOMAIN_API_KEY = os.environ.get("DOMAIN_API_KEY", "")
    DOMAIN_API_BASE_URL = os.environ.get("DOMAIN_API_BASE_URL", "")

    # Payments
    PAYMENT_PROVIDER = os.environ.get("PAYMENT_PROVIDER", "none")
    PAYMENT_API_KEY = os.environ.get("PAYMENT_API_KEY", "")
    PAYMENT_WEBHOOK_SECRET = os.environ.get("PAYMENT_WEBHOOK_SECRET", "")

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # Default free-tier limit — configurable, not hard-coded into logic.
    DEFAULT_FREE_NAMES_PER_GENERATION = 25
