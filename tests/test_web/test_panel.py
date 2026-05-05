"""Tests for Web Panel — Phase 8.1."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gate_trade.web.panel import app

client = TestClient(app)


class TestHealth:
    def test_health_returns_ok(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestDashboard:
    def test_dashboard_returns_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Gate Trade Panel" in resp.text

    def test_dashboard_contains_auto_refresh(self):
        resp = client.get("/")
        assert "setInterval(pollSnapshot, 3000)" in resp.text


class TestStatusEndpoint:
    def test_missing_db_returns_503(self):
        resp = client.get("/api/status?db=nonexistent.db")
        assert resp.status_code == 503

    def test_status_error_json(self):
        resp = client.get("/api/status?db=nonexistent.db")
        data = resp.json()
        assert "error" in data


class TestFillsEndpoint:
    def test_missing_db_returns_503(self):
        resp = client.get("/api/fills?db=nonexistent.db")
        assert resp.status_code == 503


class TestSummaryEndpoint:
    def test_missing_db_returns_503(self):
        resp = client.get("/api/summary?db=nonexistent.db")
        assert resp.status_code == 503
