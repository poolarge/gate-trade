"""Unit tests for AlertManager — Phase 4.1."""

from __future__ import annotations

import pytest

from gate_trade.alert.manager import AlertChannel, AlertLevel, AlertManager


class FakeChannel(AlertChannel):
    """Test channel that records calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[AlertLevel, str, str]] = []
        self._should_fail = False

    async def send(self, level: AlertLevel, subject: str, body: str) -> bool:
        self.calls.append((level, subject, body))
        if self._should_fail:
            raise RuntimeError("simulated failure")
        return True


@pytest.fixture
def mgr() -> AlertManager:
    return AlertManager()


class TestAlertManager:
    def test_no_channels_silent(self, mgr: AlertManager) -> None:
        import asyncio
        asyncio.run(mgr.alert(AlertLevel.WARN, "test", "body"))

    def test_sends_to_all_channels(self, mgr: AlertManager) -> None:
        c1 = FakeChannel()
        c2 = FakeChannel()
        mgr.add(c1)
        mgr.add(c2)
        import asyncio
        asyncio.run(mgr.alert(AlertLevel.CRITICAL, "halt", "details"))
        assert len(c1.calls) == 1
        assert len(c2.calls) == 1
        assert c1.calls[0][0] == AlertLevel.CRITICAL
        assert c1.calls[0][1] == "halt"
        assert c1.calls[0][2] == "details"

    def test_partial_failure_does_not_crash(self, mgr: AlertManager) -> None:
        c1 = FakeChannel()
        c2 = FakeChannel()
        c2._should_fail = True
        mgr.add(c1)
        mgr.add(c2)
        import asyncio
        asyncio.run(mgr.alert(AlertLevel.WARN, "test", "body"))
        assert len(c1.calls) == 1  # first channel still received

    def test_convenience_methods(self, mgr: AlertManager) -> None:
        c = FakeChannel()
        mgr.add(c)
        import asyncio
        asyncio.run(mgr.info("info_subj", "info_body"))
        level: AlertLevel = c.calls[-1][0]
        assert level == AlertLevel.INFO
        asyncio.run(mgr.warn("warn_subj", "warn_body"))
        level = c.calls[-1][0]
        assert level == AlertLevel.WARN
        asyncio.run(mgr.critical("crit_subj", "crit_body"))
        level = c.calls[-1][0]
        assert level == AlertLevel.CRITICAL
