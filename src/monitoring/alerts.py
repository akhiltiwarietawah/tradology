"""Production Monitoring Alert Service with Deduplication, Structured Logging, and Optional Telegram."""

import logging
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from collections import deque

from src.config.settings import Settings


class AlertSeverity:
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"
    SUCCESS = "SUCCESS"


class AlertService:
    """Delivers operational alerts with cooldown deduplication and strict failure isolation."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.settings = settings
        self.logger = logger or logging.getLogger("alert_service")
        self.cooldown_seconds = settings.alert_cooldown_seconds if settings else 300
        self.telegram_enabled = bool(settings and settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id)
        self.bot_token = settings.telegram_bot_token if settings else None
        self.chat_id = settings.telegram_chat_id if settings else None

        # Deduplication tracker: key -> (timestamp, state_hash)
        self._last_alert_time: Dict[str, datetime] = {}
        self._last_alert_message: Dict[str, str] = {}

        # In-memory recent alert history (last 50 alerts)
        self._recent_alerts: deque = deque(maxlen=50)

    async def send(
        self,
        severity: str,
        event: str,
        message: str,
        trade_id: Optional[str] = None,
        force: bool = False,
    ) -> bool:
        """
        Send an operational alert across channels.
        Deduplicates repeated alerts within cooldown window unless state changes or forced.
        """
        now = datetime.now(timezone.utc)
        dedup_key = f"{event}:{trade_id or 'global'}"

        # Check deduplication
        if not force and dedup_key in self._last_alert_time:
            last_time = self._last_alert_time[dedup_key]
            last_msg = self._last_alert_message.get(dedup_key, "")
            elapsed = (now - last_time).total_seconds()

            if elapsed < self.cooldown_seconds and last_msg == message:
                self.logger.debug(f"Alert suppressed (cooldown {elapsed:.1f}s < {self.cooldown_seconds}s): {event}")
                return False

        # Record alert tracking
        self._last_alert_time[dedup_key] = now
        self._last_alert_message[dedup_key] = message

        record = {
            "timestamp": now.isoformat(),
            "severity": severity.upper(),
            "event": event,
            "message": message,
            "trade_id": trade_id,
        }
        self._recent_alerts.append(record)

        # 1. Structured Logging
        self._log_alert(severity=severity, event=event, message=message)

        # 2. Telegram Delivery (Optional & Isolated)
        if self.telegram_enabled:
            await self._send_telegram(severity=severity, event=event, message=message)

        return True

    def _log_alert(self, severity: str, event: str, message: str) -> None:
        """Emit structured log with severity emoji."""
        sev = severity.upper()
        if sev == AlertSeverity.CRITICAL:
            self.logger.error(f"🚨 [CRITICAL] {event}: {message}")
        elif sev == AlertSeverity.WARNING:
            self.logger.warning(f"⚠️ [WARNING] {event}: {message}")
        elif sev == AlertSeverity.SUCCESS:
            self.logger.info(f"✅ [SUCCESS] {event}: {message}")
        else:
            self.logger.info(f"ℹ️ [INFO] {event}: {message}")

    async def _send_telegram(self, severity: str, event: str, message: str) -> None:
        """Send notification via Telegram Bot API with strict failure isolation."""
        if not self.bot_token or not self.chat_id:
            return

        # Formatting
        sev = severity.upper()
        icon = "🚨" if sev == AlertSeverity.CRITICAL else ("⚠️" if sev == AlertSeverity.WARNING else "✅")
        text = f"<b>{icon} [{sev}] {event}</b>\n\n{message}\n\n<i>Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    self.logger.warning(f"⚠️ [AlertService] Telegram API error HTTP {resp.status_code}")
        except Exception as e:
            # Failure is caught cleanly - NEVER crash or block trading
            self.logger.warning(f"⚠️ [AlertService] Telegram delivery failed: {type(e).__name__}")

    def get_recent_alerts(self) -> List[Dict[str, Any]]:
        """Return list of recently emitted alerts."""
        return list(self._recent_alerts)
