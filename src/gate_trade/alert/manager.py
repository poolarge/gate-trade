"""AlertManager — multi-channel alert dispatch.

Phase 4.1: Supports Telegram webhook and email (SMTP) channels with
severity-based routing. Alerts are fire-and-forget — failures are logged
but never crash the main loop.
"""

from __future__ import annotations

import asyncio
import smtplib
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from enum import Enum

import structlog

logger = structlog.get_logger(__name__)


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class AlertChannel:
    """Abstract base for alert channels."""

    async def send(self, level: AlertLevel, subject: str, body: str) -> bool:
        raise NotImplementedError


class TelegramChannel(AlertChannel):
    """Sends alerts via a Telegram bot webhook."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._token = bot_token
        self._chat_id = chat_id

    async def send(self, level: AlertLevel, subject: str, body: str) -> bool:
        if not self._token:
            return False
        try:
            emoji = {"INFO": "ℹ️", "WARN": "⚠️", "CRITICAL": "🚨"}.get(level.value, "")
            text = f"{emoji} *{subject}*\n\n{body}"
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            payload = urllib.parse.urlencode({
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }).encode()
            req = urllib.request.Request(url, data=payload, method="POST")
            await asyncio.to_thread(urllib.request.urlopen, req, timeout=10)
            return True
        except Exception:
            logger.exception("telegram_alert_failed", subject=subject)
            return False


class EmailChannel(AlertChannel):
    """Sends alerts via SMTP email."""

    def __init__(self, smtp_host: str, smtp_port: int, username: str, password: str, to: str) -> None:
        self._host = smtp_host
        self._port = smtp_port
        self._user = username
        self._pass = password
        self._to = to

    async def send(self, level: AlertLevel, subject: str, body: str) -> bool:
        if not self._host:
            return False
        try:
            msg = MIMEText(body)
            msg["Subject"] = f"[{level.value}] {subject}"
            msg["From"] = self._user
            msg["To"] = self._to

            def _send() -> bool:
                if self._port == 465:
                    server: smtplib.SMTP = smtplib.SMTP_SSL(self._host, self._port, timeout=10)
                else:
                    server = smtplib.SMTP(self._host, self._port, timeout=10)
                    server.starttls()
                with server:
                    server.login(self._user, self._pass)
                    server.send_message(msg)
                return True

            await asyncio.to_thread(_send)
            return True
        except Exception:
            logger.exception("email_alert_failed", subject=subject)
            return False


class AlertManager:
    """Multi-channel alert dispatcher.

    Usage::

        mgr = AlertManager()
        mgr.add(TelegramChannel(bot_token, chat_id))
        mgr.add(EmailChannel(host, port, user, pw, to))
        await mgr.alert(AlertLevel.WARN, "Risk halt", "Position limit breached")
    """

    def __init__(self) -> None:
        self._channels: list[AlertChannel] = []

    def add(self, channel: AlertChannel) -> None:
        self._channels.append(channel)

    async def alert(self, level: AlertLevel, subject: str, body: str) -> None:
        """Send alert to all registered channels. Fire-and-forget per channel."""
        if not self._channels:
            logger.debug("alert_no_channels", level=level.value, subject=subject)
            return

        results = await asyncio.gather(
            *(ch.send(level, subject, body) for ch in self._channels),
            return_exceptions=True,
        )
        ok = sum(1 for r in results if r is True)
        fail = len(results) - ok
        if fail:
            logger.warning("alert_partial_failure", ok=ok, fail=fail, subject=subject)
        else:
            logger.info("alert_sent", level=level.value, subject=subject, channels=ok)

    async def info(self, subject: str, body: str) -> None:
        await self.alert(AlertLevel.INFO, subject, body)

    async def warn(self, subject: str, body: str) -> None:
        await self.alert(AlertLevel.WARN, subject, body)

    async def critical(self, subject: str, body: str) -> None:
        await self.alert(AlertLevel.CRITICAL, subject, body)
