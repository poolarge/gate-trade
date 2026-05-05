"""Unit tests for ConfigGuard — Phase 3.2."""

from __future__ import annotations

import time

from gate_trade.config.guard import ConfigGuard, PendingConfirmation
from gate_trade.config.watcher import ConfigChange


def _change(key: str, old: str = "old", new: str = "new", level: int = 2) -> ConfigChange:
    return ConfigChange(key, old, new, level)


class TestPendingConfirmation:
    def test_has_token(self) -> None:
        pc = PendingConfirmation([_change("a")])
        assert len(pc.token) == 12
        assert pc.token != ""

    def test_tokens_are_unique(self) -> None:
        t1 = PendingConfirmation([_change("a")]).token
        t2 = PendingConfirmation([_change("b")]).token
        assert t1 != t2


class TestSubmit:
    def test_submit_returns_token(self) -> None:
        g = ConfigGuard()
        token = g.submit([_change("trading.target_pair")])
        assert token is not None
        assert len(token) > 0
        assert g.has_pending is True

    def test_submit_empty_returns_none(self) -> None:
        g = ConfigGuard()
        assert g.submit([]) is None
        assert g.has_pending is False

    def test_second_submit_replaces_first(self) -> None:
        g = ConfigGuard()
        t1 = g.submit([_change("a")])
        t2 = g.submit([_change("b")])
        assert t1 is not None
        assert t2 is not None
        assert t1 != t2
        # Old token should no longer work
        assert g.confirm(t1) is None


class TestConfirm:
    def test_confirm_returns_changes(self) -> None:
        g = ConfigGuard()
        changes = [_change("trading.target_pair")]
        token = g.submit(changes)
        assert token is not None
        result = g.confirm(token)
        assert result is not None
        assert len(result) == 1
        assert result[0].key == "trading.target_pair"

    def test_confirm_wrong_token(self) -> None:
        g = ConfigGuard()
        g.submit([_change("a")])
        assert g.confirm("wrong") is None
        assert g.has_pending is True  # still pending

    def test_confirm_no_pending(self) -> None:
        g = ConfigGuard()
        assert g.confirm("abc123") is None

    def test_confirm_clears_pending(self) -> None:
        g = ConfigGuard()
        token = g.submit([_change("a")])
        assert token is not None
        g.confirm(token)
        assert g.has_pending is False
        assert g.pending_token is None


class TestReject:
    def test_reject_removes_pending(self) -> None:
        g = ConfigGuard()
        token = g.submit([_change("a")])
        assert token is not None
        assert g.reject(token) is True
        assert g.has_pending is False

    def test_reject_wrong_token(self) -> None:
        g = ConfigGuard()
        g.submit([_change("a")])
        assert g.reject("wrong") is False
        assert g.has_pending is True  # still pending

    def test_reject_no_pending(self) -> None:
        g = ConfigGuard()
        assert g.reject("abc") is False


class TestExpire:
    def test_pending_expires(self) -> None:
        g = ConfigGuard(auto_expire_sec=0.01)
        g.submit([_change("a")])
        assert g.has_pending is True
        time.sleep(0.02)
        assert g.has_pending is False
