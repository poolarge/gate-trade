"""ConfigWatcher — file watcher with diff-based three-level dispatch.

Phase 3.1: Polls config YAML for changes, computes diff, and dispatches
to the appropriate level handler:
  Level 1 — hot-reload: applied immediately (e.g. log level, rate limits)
  Level 2 — confirm: queued for two-step confirmation (e.g. max position)
  Level 3 — restart: logged, requires manual restart (e.g. API credentials)
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from typing import ClassVar

import structlog
import yaml

logger = structlog.get_logger(__name__)

# Classification of config keys by reload level
_LEVEL_MAP: dict[str, int] = {
    "exchange.api_key": 3,
    "exchange.api_secret": 3,
    "exchange.base_url": 3,
    "exchange.ws_url": 3,
    "exchange.name": 3,

    "trading.target_pair": 2,
    "trading.base_inventory": 2,
    "trading.quote_inventory": 2,
    "trading.min_order_size": 2,

    "trading.spread_tick": 1,
    "trading.order_size_step": 1,

    "risk.max_position_notional": 2,
    "risk.max_order_size_notional": 2,
    "risk.max_open_orders": 2,
    "risk.cooldown_fill_ms": 1,
    "risk.cooldown_cancel_ms": 1,
    "risk.cooldown_self_trade_ms": 1,
    "risk.flash_crash_threshold_pct": 1,

    "rate_limit.burst": 1,
    "rate_limit.rate": 1,
    "rate_limit.max_wait_sec": 1,

    "ws.ping_interval_sec": 1,
    "ws.reconnect_delay_sec": 1,
    "ws.max_reconnect_attempts": 1,

    "logging.level": 1,
    "logging.json_format": 1,

    "monitoring.alert_webhook_url": 1,
    "monitoring.daily_report": 1,
}


class ConfigChange:
    """Records a single config key change with old and new values."""
    __slots__ = ("key", "old_value", "new_value", "level")

    def __init__(self, key: str, old_value: object, new_value: object, level: int) -> None:
        self.key = key
        self.old_value = old_value
        self.new_value = new_value
        self.level = level

    def __repr__(self) -> str:
        return f"ConfigChange({self.key}: {self.old_value!r} -> {self.new_value!r}, L{self.level})"


class ConfigWatcher:
    """Polls a YAML config file and dispatches changes by severity level.

    Usage::

        watcher = ConfigWatcher("/path/to/local.yaml")
        watcher.on_hot_reload = lambda changes: apply_hot(changes)
        await watcher.poll()   # call each main-loop tick or via background task
    """

    LEVEL_HOT: ClassVar[int] = 1
    LEVEL_CONFIRM: ClassVar[int] = 2
    LEVEL_RESTART: ClassVar[int] = 3

    def __init__(self, file_path: str, poll_interval_sec: float = 2.0) -> None:
        self._path = file_path
        self._poll_interval = poll_interval_sec
        self._last_mtime: float = 0.0
        self._last_snapshot: dict[str, object] = {}
        self._pending_confirm: list[ConfigChange] = []

        # Callbacks
        self.on_hot_reload: Callable[[list[ConfigChange]], None] | None = None
        self.on_confirm_required: Callable[[list[ConfigChange]], None] | None = None
        self.on_restart_required: Callable[[list[ConfigChange]], None] | None = None

        # Load initial snapshot
        self._load_snapshot()

    # ── Public API ───────────────────────────────────────────────

    @property
    def pending_confirmations(self) -> list[ConfigChange]:
        return list(self._pending_confirm)

    @property
    def has_pending(self) -> bool:
        return len(self._pending_confirm) > 0

    def confirm(self) -> list[ConfigChange]:
        """Accept all pending Level-2 changes and return them.

        Caller should apply the returned changes to the live config.
        """
        confirmed = list(self._pending_confirm)
        self._pending_confirm.clear()
        logger.info("config_changes_confirmed", count=len(confirmed))
        return confirmed

    def reject(self) -> None:
        """Reject all pending Level-2 changes."""
        count = len(self._pending_confirm)
        self._pending_confirm.clear()
        logger.info("config_changes_rejected", count=count)

    def poll(self) -> list[ConfigChange]:
        """Check for file changes. Returns all detected changes.

        Safe to call from sync or async context — uses only os.stat and yaml.
        """
        if not os.path.exists(self._path):
            return []

        try:
            mtime = os.stat(self._path).st_mtime
        except OSError:
            return []

        if mtime <= self._last_mtime:
            return []

        self._last_mtime = mtime
        raw = self._load_raw()
        if raw is None:
            return []

        flat = self._flatten(raw)
        changes = self._diff(flat)

        if changes:
            self._dispatch(changes)

        return changes

    # ── Internal ─────────────────────────────────────────────────

    def _load_raw(self) -> dict[str, object] | None:
        try:
            with open(self._path) as fh:
                raw = yaml.safe_load(fh.read())
            return raw if isinstance(raw, dict) else None
        except Exception:
            logger.warning("config_watcher_read_error", path=self._path)
            return None

    def _load_snapshot(self) -> None:
        raw = self._load_raw()
        if raw:
            self._last_snapshot = self._flatten(raw)
            if self._last_mtime == 0 and os.path.exists(self._path):
                with contextlib.suppress(OSError):
                    self._last_mtime = os.stat(self._path).st_mtime

    @staticmethod
    def _flatten(d: dict[str, object], prefix: str = "") -> dict[str, object]:
        result: dict[str, object] = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and not isinstance(v, list):
                result.update(ConfigWatcher._flatten(v, key))
            else:
                result[key] = v
        return result

    def _diff(self, new_flat: dict[str, object]) -> list[ConfigChange]:
        changes: list[ConfigChange] = []
        all_keys = set(self._last_snapshot.keys()) | set(new_flat.keys())
        for key in sorted(all_keys):
            old = self._last_snapshot.get(key)
            new = new_flat.get(key)
            if old != new:
                level = _LEVEL_MAP.get(key, 2)  # default to confirm for unknown keys
                changes.append(ConfigChange(key, old, new, level))
        self._last_snapshot = new_flat
        return changes

    def _dispatch(self, changes: list[ConfigChange]) -> None:
        hot: list[ConfigChange] = []
        confirm: list[ConfigChange] = []
        restart: list[ConfigChange] = []

        for c in changes:
            if c.level == self.LEVEL_HOT:
                hot.append(c)
            elif c.level == self.LEVEL_CONFIRM:
                confirm.append(c)
            else:
                restart.append(c)

        if hot:
            logger.info("config_hot_reload", keys=[c.key for c in hot])
            if self.on_hot_reload:
                self.on_hot_reload(hot)

        if confirm:
            self._pending_confirm.extend(confirm)
            logger.info("config_confirm_required", keys=[c.key for c in confirm])
            if self.on_confirm_required:
                self.on_confirm_required(confirm)

        if restart:
            logger.info("config_restart_required", keys=[c.key for c in restart])
            if self.on_restart_required:
                self.on_restart_required(restart)
