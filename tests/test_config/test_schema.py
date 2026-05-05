import os
import tempfile
from pathlib import Path

from gate_trade.config.schema import AppConfig


class TestAppConfig:
    def test_defaults_are_valid(self):
        cfg = AppConfig()
        assert cfg.trading.target_pair == "TARGET_USDT"
        assert cfg.risk.max_position_notional == 100.0

    def test_from_yaml(self):
        yaml_content = """
trading:
  target_pair: BTC_USDT
  spread_tick: 3
risk:
  max_position_notional: 500.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            cfg = AppConfig.from_yaml(f.name)
        Path(f.name).unlink()

        assert cfg.trading.target_pair == "BTC_USDT"
        assert cfg.trading.spread_tick == 3
        assert cfg.risk.max_position_notional == 500.0
        # untouched defaults remain
        assert cfg.ws.ping_interval_sec == 15

    def test_from_yaml_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            cfg = AppConfig.from_yaml(f.name)
        Path(f.name).unlink()
        assert cfg.trading.target_pair == "TARGET_USDT"

    def test_env_overlay(self):
        yaml_content = """
exchange:
  api_key: ""
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                os.environ["GATE_EXCHANGE__API_KEY"] = "test-key-123"
                os.environ["GATE_TRADING__TARGET_PAIR"] = "ETH_USDT"
                cfg = AppConfig.from_env_overlay(f.name)

                assert cfg.exchange.api_key == "test-key-123"
                assert cfg.trading.target_pair == "ETH_USDT"
            finally:
                del os.environ["GATE_EXCHANGE__API_KEY"]
                del os.environ["GATE_TRADING__TARGET_PAIR"]
                Path(f.name).unlink()
