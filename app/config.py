import os
from dataclasses import dataclass, field


def _env(name, default):
    return os.environ.get(name, default)


def _env_int(name, default):
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


    

def _env_float(name, default):
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    service_name: str = "tea"
    environment: str = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/gateway"
    database_pool_size: int = 10
    database_max_overflow: int = 10

    bank_base_url: str = "http://127.0.0.1:8787"
    bank_connect_timeout_seconds: float = 2.0
    bank_read_timeout_seconds: float = 5.0
    bank_max_attempts: int = 4
    bank_backoff_base_seconds: float = 0.2
    bank_backoff_cap_seconds: float = 3.0

    in_flight_stale_seconds: int = 30
    idempotency_ttl_hours: int = 24
    idempotency_stale_seconds: int = 60
    auth_expiry_hours: int = 168

    reconcile_enabled: bool = True
    reconcile_interval_seconds: int = 60
    reconcile_batch_size: int = 100

    card_hash_pepper: str = field(
        default_factory=lambda: _env("CARD_HASH_PEPPER", "dev-only-pepper")
    )

    @classmethod
    def from_env(cls):
        return cls(
            service_name=_env("SERVICE_NAME", "tea"),
            environment=_env("ENVIRONMENT", "dev"),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            database_url=_env(
                "DATABASE_URL",
                "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/gateway",
            ),
            database_pool_size=_env_int("DATABASE_POOL_SIZE", 10),
            database_max_overflow=_env_int("DATABASE_MAX_OVERFLOW", 10),
            bank_base_url=_env("BANK_BASE_URL", "http://127.0.0.1:8787").rstrip("/"),
            bank_connect_timeout_seconds=_env_float("BANK_CONNECT_TIMEOUT_SECONDS", 2.0),
            bank_read_timeout_seconds=_env_float("BANK_READ_TIMEOUT_SECONDS", 5.0),
            bank_max_attempts=_env_int("BANK_MAX_ATTEMPTS", 4),
            bank_backoff_base_seconds=_env_float("BANK_BACKOFF_BASE_SECONDS", 0.2),
            bank_backoff_cap_seconds=_env_float("BANK_BACKOFF_CAP_SECONDS", 3.0),
            in_flight_stale_seconds=_env_int("IN_FLIGHT_STALE_SECONDS", 30),
            idempotency_ttl_hours=_env_int("IDEMPOTENCY_TTL_HOURS", 24),
            idempotency_stale_seconds=_env_int("IDEMPOTENCY_STALE_SECONDS", 60),
            auth_expiry_hours=_env_int("AUTH_EXPIRY_HOURS", 168),
            reconcile_enabled=_env_bool("RECONCILE_ENABLED", True),
            reconcile_interval_seconds=_env_int("RECONCILE_INTERVAL_SECONDS", 60),
            reconcile_batch_size=_env_int("RECONCILE_BATCH_SIZE", 100),
            card_hash_pepper=_env("CARD_HASH_PEPPER", "dev-only-pepper"),
        )

    @property
    def bank_timeout(self):
        return self.bank_connect_timeout_seconds + self.bank_read_timeout_seconds