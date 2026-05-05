"""Exception hierarchy for Gate Trade."""

from __future__ import annotations


class GateTradeError(Exception):
    """Base for all gate-trade exceptions."""


# ── Exchange errors ──────────────────────────────────────────────


class ExchangeError(GateTradeError):
    """Generic exchange API or connectivity error."""


class AuthError(ExchangeError):
    """API key / signature / permission failure."""


class RateLimitExceeded(ExchangeError):
    """Exchange-level rate limit hit (HTTP 429 or equivalent)."""


class InsufficientBalance(ExchangeError):
    """Not enough balance to place the requested order."""


class OrderNotFound(ExchangeError):
    """Order ID not found on exchange."""


# ── Protocol / contract errors ───────────────────────────────────


class ProtocolError(GateTradeError):
    """Violation of a defined contract (e.g., illegal state transition)."""


class IllegalTransition(ProtocolError):
    """State machine transition not allowed."""


# ── Safety violations ────────────────────────────────────────────


class SafetyViolation(GateTradeError):
    """Risk limit breached — trading must halt."""


class SelfTradeRisk(SafetyViolation):
    """Self-trade detected or imminent."""


class PositionLimitExceeded(SafetyViolation):
    """Notional position would exceed configured maximum."""


# ── Configuration errors ─────────────────────────────────────────


class ConfigError(GateTradeError):
    """Invalid or missing configuration."""
