"""ConfigGuard — two-step confirmation for dangerous config changes.

Phase 3.2: Queues Level-2 changes from the ConfigWatcher and requires
explicit confirmation before they are applied. Supports token-based
confirmation and rejection via CLI or other admin channels.
"""

from __future__ import annotations

import secrets

import structlog

from gate_trade.config.watcher import ConfigChange

logger = structlog.get_logger(__name__)


class PendingConfirmation:
    """A batch of dangerous changes awaiting confirmation."""

    __slots__ = ("token", "changes", "created_at")

    def __init__(self, changes: list[ConfigChange]) -> None:
        self.token: str = secrets.token_hex(6)
        self.changes: list[ConfigChange] = changes
        self.created_at: float = __import__("time").monotonic()


class ConfigGuard:
    """Two-step confirmation gate for dangerous config changes.

    Level-2 changes from the ConfigWatcher are held in a pending batch.
    The operator confirms via a short token (shown in logs / CLI).

    Usage::

        guard = ConfigGuard()
        guard.submit(changes)          # queues changes, logs token
        # ... operator sees token ...
        guard.confirm(token)           # returns confirmed changes
    """

    def __init__(self, auto_expire_sec: float = 300.0) -> None:
        self._auto_expire = auto_expire_sec
        self._pending: PendingConfirmation | None = None
        self._confirmed: list[ConfigChange] = []
        self._last_applied: float = 0.0

    # ── Public API ───────────────────────────────────────────────

    @property
    def has_pending(self) -> bool:
        self._expire_if_needed()
        return self._pending is not None

    @property
    def pending_token(self) -> str | None:
        if self._pending is None:
            return None
        return self._pending.token

    @property
    def pending_changes(self) -> list[ConfigChange]:
        if self._pending is None:
            return []
        return list(self._pending.changes)

    def submit(self, changes: list[ConfigChange]) -> str | None:
        """Queue *changes* for confirmation. Returns token string.

        Replaces any existing unconfirmed batch (only one batch at a time).
        Returns None if changes is empty.
        """
        if not changes:
            return None

        self._pending = PendingConfirmation(changes)
        logger.warning(
            "config_confirm_required",
            token=self._pending.token,
            keys=[c.key for c in changes],
            expires_in_s=self._auto_expire,
        )
        return self._pending.token

    def confirm(self, token: str) -> list[ConfigChange] | None:
        """Confirm a pending batch by token. Returns the changes or None if
        the token is wrong or no batch is pending.
        """
        self._expire_if_needed()
        if self._pending is None:
            logger.info("config_confirm_no_pending")
            return None
        if self._pending.token != token:
            logger.warning("config_confirm_wrong_token", provided=token)
            return None

        confirmed = list(self._pending.changes)
        self._confirmed = confirmed
        self._last_applied = __import__("time").monotonic()
        self._pending = None
        logger.info("config_confirmed", keys=[c.key for c in confirmed])
        return confirmed

    def reject(self, token: str) -> bool:
        """Reject a pending batch by token. Returns True if rejected."""
        self._expire_if_needed()
        if self._pending is None:
            logger.info("config_reject_no_pending")
            return False
        if self._pending.token != token:
            logger.warning("config_reject_wrong_token", provided=token)
            return False

        count = len(self._pending.changes)
        self._pending = None
        logger.info("config_rejected", count=count)
        return True

    # ── Internal ─────────────────────────────────────────────────

    def _expire_if_needed(self) -> None:
        if self._pending is None:
            return
        age = __import__("time").monotonic() - self._pending.created_at
        if age >= self._auto_expire:
            logger.info("config_pending_expired",
                       token=self._pending.token, age_s=age)
            self._pending = None
