"""Pydantic configuration schema — single source of truth for all settings."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ExchangeConfig(BaseModel):
    name: str = "gate"
    base_url: str = "https://api.gateio.ws/api/v4"
    ws_url: str = "wss://ws.gateio.ws/v4/"
    api_key: str = ""
    api_secret: str = ""


class TradingConfig(BaseModel):
    target_pair: str = "TARGET_USDT"
    base_inventory: float = 0.0
    quote_inventory: float = 0.0
    spread_tick: int = Field(default=5, ge=1, description="Half-spread in price ticks")
    min_order_size: float = Field(default=1.0, ge=0.0)
    order_size_step: float = Field(default=1.0, ge=0.0)


class RiskConfig(BaseModel):
    max_position_notional: float = Field(default=100.0, gt=0)
    max_order_size_notional: float = Field(default=50.0, gt=0)
    max_open_orders: int = Field(default=10, ge=1)
    cooldown_fill_ms: int = Field(default=2000, ge=0)
    cooldown_cancel_ms: int = Field(default=1000, ge=0)
    cooldown_self_trade_ms: int = Field(default=5000, ge=0)
    flash_crash_threshold_pct: float = Field(default=5.0, ge=0.1, le=50.0)


class RateLimitConfig(BaseModel):
    burst: int = Field(default=10, ge=1)
    rate: float = Field(default=8.0, gt=0.0)
    max_wait_sec: float = Field(default=5.0, ge=0.0)


class WsConfig(BaseModel):
    ping_interval_sec: int = Field(default=15, ge=5)
    reconnect_delay_sec: float = Field(default=2.0, ge=0.1)
    max_reconnect_attempts: int = Field(default=0, ge=0)


class LoggingConfig(BaseModel):
    level: str = "INFO"
    json_format: bool = True


class MonitoringConfig(BaseModel):
    alert_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    daily_report: bool = True


class AppConfig(BaseModel):
    """Top-level configuration model."""

    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    ws: WsConfig = Field(default_factory=WsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> AppConfig:
        """Load config from a YAML file."""
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)

    @classmethod
    def from_yaml_merged(cls, base: str | Path, local: str | Path | None = None) -> AppConfig:
        """Load base YAML, optionally merge a local override file on top."""
        cfg = cls.from_yaml(base)
        if local is not None and Path(local).exists():
            cfg = cfg.model_validate(cls._apply_overrides(
                cfg.model_dump(),
                cls._flatten(yaml.safe_load(Path(local).read_text()) or {}, ""),
            ))
        return cfg

    @classmethod
    def from_env_overlay(cls, path: str | Path) -> AppConfig:
        """Load YAML, then override with environment variables prefixed ``GATE_``.

        Environment variable names map to nested fields via double-underscore:
        ``GATE_EXCHANGE__API_KEY=xxx`` → ``config.exchange.api_key = "xxx"``.
        """
        import os

        config = cls.from_yaml(path)
        overrides: dict[str, Any] = {}

        for key, value in os.environ.items():
            if not key.startswith("GATE_"):
                continue
            field_path = key[5:].lower().replace("__", ".")
            if field_path:
                overrides[field_path] = value

        if overrides:
            config = config.model_validate(
                cls._apply_overrides(config.model_dump(), overrides)
            )
        return config

    @staticmethod
    def _flatten(d: dict[str, Any], prefix: str) -> dict[str, Any]:
        """Flatten nested dict to dotted-path keys."""
        result: dict[str, Any] = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and not isinstance(v, list):
                result.update(AppConfig._flatten(v, key))
            else:
                result[key] = v
        return result

    @staticmethod
    def _apply_overrides(data: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Apply dotted-path overrides to a nested dict (mutates *data*)."""
        for path, value in overrides.items():
            parts = path.split(".")
            d = data
            for part in parts[:-1]:
                if part not in d:
                    d[part] = {}
                d = d[part]
            leaf = parts[-1]
            # coerce to the existing type if possible
            if leaf in d and value is not None:
                with contextlib.suppress(TypeError, ValueError):
                    value = type(d[leaf])(value)
            d[leaf] = value
        return data
