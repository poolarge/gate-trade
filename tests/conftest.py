import pytest


@pytest.fixture
def default_config():
    from gate_trade.config.schema import AppConfig
    return AppConfig()
