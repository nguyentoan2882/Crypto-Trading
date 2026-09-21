from __future__ import annotations

import os
from dataclasses import dataclass


PUBLIC_BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
FORBIDDEN_BINANCE_ENV_MARKERS = ("API_KEY", "API_SECRET", "SECRET_KEY", "PRIVATE_KEY")


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class CloudConfig:
    role: str = "web"
    environment: str = "SHADOW"
    port: int = 8080
    database_url: str = ""
    allowed_origins: tuple[str, ...] = ()
    owner_user_ids: tuple[str, ...] = ()
    owner_emails: tuple[str, ...] = ()
    jwt_issuer: str = ""
    jwt_audience: str = "authenticated"
    jwt_jwks_url: str = ""
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    health_token: str = ""
    notification_mode: str = "disabled"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    binance_klines_url: str = PUBLIC_BINANCE_KLINES_URL
    symbols: tuple[str, ...] = ("BTCUSDT", "BNBUSDT", "SOLUSDT")
    rule_version: str = "NXT-v3.5-GuardDirectional-30-10At4R-60"
    git_sha: str = "unknown"

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "CloudConfig":
        env = os.environ if environ is None else environ
        config = cls(
            role=env.get("ROLE", "web").strip().lower(),
            environment=env.get("NXT_ENVIRONMENT", "SHADOW").strip().upper(),
            port=int(env.get("PORT", "8080")),
            database_url=env.get("DATABASE_URL", "").strip(),
            allowed_origins=_csv(env.get("NXT_ALLOWED_ORIGINS", "")),
            owner_user_ids=_csv(env.get("NXT_OWNER_USER_IDS", "")),
            owner_emails=tuple(item.lower() for item in _csv(env.get("NXT_OWNER_EMAILS", ""))),
            jwt_issuer=env.get("NXT_JWT_ISSUER", "").strip(),
            jwt_audience=env.get("NXT_JWT_AUDIENCE", "authenticated").strip(),
            jwt_jwks_url=env.get("NXT_JWT_JWKS_URL", "").strip(),
            supabase_url=env.get("NXT_SUPABASE_URL", "").strip().rstrip("/"),
            supabase_publishable_key=env.get("NXT_SUPABASE_PUBLISHABLE_KEY", "").strip(),
            health_token=env.get("NXT_HEALTH_TOKEN", "").strip(),
            notification_mode=env.get("NXT_NOTIFICATION_MODE", "disabled").strip().lower(),
            telegram_bot_token=env.get("NXT_TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=env.get("NXT_TELEGRAM_CHAT_ID", "").strip(),
            binance_klines_url=env.get("NXT_USDM_KLINES_URL", PUBLIC_BINANCE_KLINES_URL).strip(),
            symbols=_csv(env.get("NXT_SYMBOLS", "BTCUSDT,BNBUSDT,SOLUSDT")),
            rule_version=env.get("NXT_RULE_VERSION", cls.rule_version).strip(),
            git_sha=env.get("NXT_GIT_SHA", "unknown").strip(),
        )
        config.validate(env)
        return config

    def validate(self, environ: dict[str, str] | None = None) -> None:
        if self.role not in {"web", "scanner"}:
            raise ValueError("ROLE must be web or scanner")
        if self.environment != "SHADOW":
            raise ValueError("Cloud MVP1 refuses to start outside SHADOW without a later cutover implementation")
        if not 1 <= self.port <= 65535:
            raise ValueError("PORT is outside the valid range")
        if self.binance_klines_url != PUBLIC_BINANCE_KLINES_URL:
            raise ValueError("Only the approved public Binance USD-M klines endpoint is allowed")
        if set(self.symbols) != {"BTCUSDT", "BNBUSDT", "SOLUSDT"}:
            raise ValueError("Shadow symbols must be exactly BTCUSDT, BNBUSDT and SOLUSDT")
        if self.notification_mode not in {"disabled", "telegram"}:
            raise ValueError("NXT_NOTIFICATION_MODE must be disabled or telegram")
        env = os.environ if environ is None else environ
        forbidden = [name for name, value in env.items() if value and name.startswith("BINANCE_") and any(marker in name for marker in FORBIDDEN_BINANCE_ENV_MARKERS)]
        if forbidden:
            raise ValueError(f"Authenticated Binance credential variables are forbidden: {', '.join(sorted(forbidden))}")

    @property
    def message_prefix(self) -> str:
        return "[NXT-CLOUD][SHADOW]"
