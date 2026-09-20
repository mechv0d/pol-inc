from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "dev"
    log_level: str = "INFO"

    bot_token: str
    telegram_webhook_base_url: str
    telegram_webhook_path: str = "/telegram/webhook"
    telegram_webhook_secret: str
    telegram_webhook_enabled: bool = True
    telegram_admin_ids: list[int] = Field(default_factory=list)

    supabase_url: str
    supabase_service_role_key: str

    packs_bucket: str = "game-packs"
    packs_index_object: str = "index.json"
    images_bucket: str = "pack-images"
    party_bucket: str = "parties"

    session_ttl_hours: int = 4
    max_players: int = 4
    min_players: int = 2
    default_pack_id: str = "base"

    @field_validator("bot_token", "supabase_service_role_key", "telegram_webhook_secret")
    @classmethod
    def strip_secrets(cls, value: str) -> str:
        return value.strip()

    @field_validator("telegram_webhook_base_url")
    @classmethod
    def strip_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("telegram_webhook_path")
    @classmethod
    def ensure_path_starts_with_slash(cls, value: str) -> str:
        return value if value.startswith("/") else f"/{value}"

    @field_validator("session_ttl_hours")
    @classmethod
    def validate_session_ttl_hours(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("SESSION_TTL_HOURS должен быть больше нуля.")
        return value

    @field_validator("max_players")
    @classmethod
    def validate_max_players(cls, value: int) -> int:
        if value < 2 or value > 4:
            raise ValueError("MAX_PLAYERS должен быть от 2 до 4.")
        return value

    @field_validator("min_players")
    @classmethod
    def validate_min_players(cls, value: int) -> int:
        if value < 2:
            raise ValueError("MIN_PLAYERS должен быть не меньше 2.")
        return value

    @model_validator(mode="after")
    def validate_players_limits(self) -> "Settings":
        if self.min_players > self.max_players:
            raise ValueError("MIN_PLAYERS не может быть больше MAX_PLAYERS.")
        return self

    @property
    def webhook_url(self) -> str:
        return f"{self.telegram_webhook_base_url}{self.telegram_webhook_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()