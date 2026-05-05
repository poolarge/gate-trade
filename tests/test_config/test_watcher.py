"""Unit tests for ConfigWatcher — Phase 3.1."""

from __future__ import annotations

import contextlib
import os
import tempfile

import pytest
import yaml

from gate_trade.config.watcher import ConfigChange, ConfigWatcher


def _touch(path: str) -> None:
    """Advance mtime by a full second so polling detects the change."""
    stat = os.stat(path)
    os.utime(path, (stat.st_atime, stat.st_mtime + 1.0))


@pytest.fixture
def tmp_yaml() -> str:
    """Create a temp YAML file and return its path."""
    content = {
        "exchange": {"name": "gate", "api_key": "old_key"},
        "trading": {"target_pair": "BTC_USDT", "spread_tick": 5},
        "logging": {"level": "INFO"},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(content, f)
        return f.name


class TestFileWatchAndPoll:
    def test_no_changes_on_first_poll(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        changes = w.poll()
        assert changes == []

    def test_detects_change(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        # Modify file
        with open(tmp_yaml, "w") as f:
            yaml.dump({"exchange": {"name": "gate", "api_key": "new_key"}, "trading": {"target_pair": "ETH_USDT", "spread_tick": 5}, "logging": {"level": "INFO"}}, f)
        _touch(tmp_yaml)
        changes = w.poll()
        assert len(changes) == 2  # api_key + target_pair

    def test_no_changes_on_same_content(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        # Second identical poll
        changes = w.poll()
        assert changes == []

    def test_file_not_exist_returns_empty(self, tmp_yaml: str) -> None:
        os.unlink(tmp_yaml)
        w = ConfigWatcher(tmp_yaml)
        changes = w.poll()
        assert changes == []


class TestLevelClassification:
    def test_level_1_hot_reload_keys(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        with open(tmp_yaml, "w") as f:
            yaml.dump({"exchange": {"name": "gate"}, "trading": {"target_pair": "BTC_USDT", "spread_tick": 10}, "logging": {"level": "DEBUG"}}, f)
        _touch(tmp_yaml)
        changes = w.poll()
        # spread_tick and logging.level are L1
        l1 = [c for c in changes if c.level == 1]
        assert len(l1) >= 1
        for c in l1:
            assert c.key in ("trading.spread_tick", "logging.level")

    def test_level_2_confirm_keys(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        with open(tmp_yaml, "w") as f:
            yaml.dump({"exchange": {"name": "gate"}, "trading": {"target_pair": "ETH_USDT", "spread_tick": 5}, "logging": {"level": "INFO"}}, f)
        _touch(tmp_yaml)
        changes = w.poll()
        l2 = [c for c in changes if c.level == 2]
        assert any(c.key == "trading.target_pair" for c in l2)

    def test_level_3_restart_keys(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        with open(tmp_yaml, "w") as f:
            yaml.dump({"exchange": {"name": "gate", "api_key": "changed"}, "trading": {"target_pair": "BTC_USDT", "spread_tick": 5}, "logging": {"level": "INFO"}}, f)
        _touch(tmp_yaml)
        changes = w.poll()
        l3 = [c for c in changes if c.level == 3]
        assert any(c.key == "exchange.api_key" for c in l3)


class TestCallbacks:
    def test_hot_reload_callback(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        received: list[list[ConfigChange]] = []
        w.on_hot_reload = lambda changes: received.append(changes)

        with open(tmp_yaml, "w") as f:
            yaml.dump({"exchange": {"name": "gate"}, "trading": {"target_pair": "BTC_USDT", "spread_tick": 10}, "logging": {"level": "DEBUG"}}, f)
        _touch(tmp_yaml)
        w.poll()
        assert len(received) > 0

    def test_confirm_callback_queues_pending(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        with open(tmp_yaml, "w") as f:
            yaml.dump({"exchange": {"name": "gate"}, "trading": {"target_pair": "ETH_USDT", "spread_tick": 5}, "logging": {"level": "INFO"}}, f)
        _touch(tmp_yaml)
        w.poll()
        assert w.has_pending is True
        assert len(w.pending_confirmations) > 0

    def test_restart_callback(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        received: list[list[ConfigChange]] = []
        w.on_restart_required = lambda changes: received.append(changes)

        with open(tmp_yaml, "w") as f:
            yaml.dump({"exchange": {"name": "gate", "api_key": "new"}, "trading": {"target_pair": "BTC_USDT", "spread_tick": 5}, "logging": {"level": "INFO"}}, f)
        _touch(tmp_yaml)
        w.poll()
        assert len(received) > 0


class TestConfirmReject:
    def test_confirm_returns_and_clears(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        # Trigger L2 change
        with open(tmp_yaml, "w") as f:
            yaml.dump({"exchange": {"name": "gate"}, "trading": {"target_pair": "ETH_USDT", "spread_tick": 5}, "logging": {"level": "INFO"}}, f)
        _touch(tmp_yaml)
        w.poll()
        assert w.has_pending is True
        confirmed = w.confirm()
        assert len(confirmed) > 0
        assert w.has_pending is False

    def test_reject_clears(self, tmp_yaml: str) -> None:
        w = ConfigWatcher(tmp_yaml)
        with open(tmp_yaml, "w") as f:
            yaml.dump({"exchange": {"name": "gate"}, "trading": {"target_pair": "ETH_USDT", "spread_tick": 5}, "logging": {"level": "INFO"}}, f)
        _touch(tmp_yaml)
        w.poll()
        assert w.has_pending is True
        w.reject()
        assert w.has_pending is False


class TestConfigChange:
    def test_repr(self) -> None:
        c = ConfigChange("trading.spread_tick", 5, 10, 1)
        r = repr(c)
        assert "spread_tick" in r
        assert "5" in r
        assert "10" in r
        assert "L1" in r


def teardown_module() -> None:
    """Clean up temp files."""
    import glob as g
    for f in g.glob(os.path.join(tempfile.gettempdir(), "*.yaml")):
        with contextlib.suppress(OSError):
            os.unlink(f)
