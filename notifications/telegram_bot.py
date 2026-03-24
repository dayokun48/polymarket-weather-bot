"""
telegram_bot.py
================
Sends alerts and handles button interactions.

Fixes dari original:
  - signal['forecast_conditions'] tidak ada → pakai signal.get('reasoning')
  - fair_value & current_price adalah 0-1, bukan cents → tampilkan ×100
  - test_connection hardcode config → baca dari config.get()
  - Tambah cooldown check antar alert (alert_cooldown_seconds dari DB)
  - Tambah bracket market support → tampilkan bracket_label dan forecast_temp
  - Tambah send_resume_alert untuk bot auto-pause/unpause notification
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

import config

logger = logging.getLogger(__name__)


class TelegramBot:
    """
    Send Telegram notifications and handle button callbacks.
    """

    def __init__(self):
        self.token    = config.TELEGRAM_BOT_TOKEN
        self.chat_id  = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self._last_alert_time: Dict[str, float] = {}  # market_id → timestamp

        if not self.token or not self.chat_id:
            logger.warning("⚠️  Telegram tidak dikonfigurasi — alerts dinonaktifkan")

    # ── Signal alert ───────────────────────────────────────────────────────────

    def send_signal_alert(self, signal: Dict) -> bool:
        """
        Kirim trading signal alert ke Telegram dengan tombol EXECUTE / SKIP.
        Cek cooldown sebelum kirim agar tidak spam.
        """
        try:
            market_id = signal.get("market_id", "")

            # Cooldown check
            if not self._check_cooldown(market_id):
                logger.info(f"⏳ Alert skipped (cooldown aktif): {market_id}")
                return False

            message  = self._format_signal_alert(signal)
            keyboard = {
                "inline_keyboard": [[
                    {
                        "text": "✅ EXECUTE",
                        "callback_data": f"execute:{market_id}"
                    },
                    {
                        "text": "❌ SKIP",
                        "callback_data": f"skip:{market_id}"
                    }
                ]]
            }

            success = self._send_message(message, keyboard)
            if success:
                self._last_alert_time[market_id] = time.time()
                logger.info(f"✅ Alert terkirim: {signal.get('market_question','')[:50]}")
            else:
                logger.error("❌ Gagal kirim alert")

            return success

        except Exception as e:
            logger.error(f"Error send_signal_alert: {e}")
            return False

    # ── Trade confirmation ────────────────────────────────────────────────────

    def send_execution_confirmation(self, trade: Dict) -> bool:
        """Kirim konfirmasi eksekusi trade."""
        try:
            executed_at = trade.get("executed_at")
            if isinstance(executed_at, datetime):
                time_str = executed_at.strftime("%Y-%m-%d %H:%M UTC")
            else:
                time_str = str(executed_at)

            message = f"""
✅ <b>TRADE EXECUTED</b>

📝 <b>Trade ID:</b> <code>{str(trade.get('trade_id',''))[:20]}</code>
💰 <b>Amount:</b> ${trade.get('bet_size', 0):.2f}
📊 <b>Direction:</b> {trade.get('direction', '')}
💵 <b>Entry Price:</b> {trade.get('entry_price', 0):.4f}
📈 <b>Shares:</b> {trade.get('shares', 0):.2f}

<b>Market:</b>
{trade.get('market_question', '')}

⏰ <b>Executed:</b> {time_str}
💳 <b>Tx Hash:</b> <code>{str(trade.get('tx_hash','N/A'))[:20]}</code>

<b>Status:</b> {trade.get('status', 'open')}
""".strip()

            return self._send_message(message)

        except Exception as e:
            logger.error(f"Error send_execution_confirmation: {e}")
            return False

    # ── Position update ────────────────────────────────────────────────────────

    def send_position_update(self, position: Dict) -> bool:
        """Kirim update posisi (perubahan P&L)."""
        try:
            pnl       = position.get("unrealized_pnl", 0)
            pnl_emoji = "📈" if pnl > 0 else "📉"

            message = f"""
{pnl_emoji} <b>POSITION UPDATE</b>

<b>Market:</b>
{str(position.get('market_question',''))[:80]}

💰 <b>Invested:</b> ${position.get('amount_invested', 0):.2f}
📊 <b>Entry Price:</b> {position.get('entry_price', 0):.4f}
💵 <b>Current Price:</b> {position.get('current_price', 0):.4f}
<b>Unrealized P&L:</b> ${pnl:+.2f}

⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
""".strip()

            return self._send_message(message)

        except Exception as e:
            logger.error(f"Error send_position_update: {e}")
            return False

    # ── Settlement ────────────────────────────────────────────────────────────

    def send_settlement_alert(self, position: Dict) -> bool:
        """Kirim notifikasi posisi settled (menang/kalah)."""
        try:
            outcome       = (position.get("outcome") or "").lower()  # schema: 'win'/'loss'
            outcome_emoji = "🎉" if outcome == "win" else "😔"
            outcome_label = outcome.upper() if outcome else "UNKNOWN"
            pnl           = position.get("realized_pnl", 0)

            opened_at = position.get("opened_at")
            closed_at = position.get("closed_at")
            duration  = ""
            if opened_at and closed_at:
                try:
                    duration = f"{(closed_at - opened_at).days} hari"
                except Exception:
                    duration = "N/A"

            message = f"""
{outcome_emoji} <b>POSITION SETTLED — {outcome_label}</b>

<b>Market:</b>
{position.get('market_question', '')}

💰 <b>Invested:</b> ${position.get('amount_invested', 0):.2f}
💵 <b>Payout:</b> ${position.get('payout', 0):.2f}
<b>P&L:</b> ${pnl:+.2f}

📊 <b>Entry:</b> {position.get('entry_price', 0):.4f}
⏰ <b>Duration:</b> {duration}

<b>Status:</b> CLOSED
""".strip()

            return self._send_message(message)

        except Exception as e:
            logger.error(f"Error send_settlement_alert: {e}")
            return False

    # ── Daily summary ──────────────────────────────────────────────────────────

    def send_daily_summary(self, stats: Dict) -> bool:
        """Kirim ringkasan performa harian."""
        try:
            pnl       = stats.get("daily_pnl", 0)
            pnl_emoji = "📈" if pnl >= 0 else "📉"

            message = f"""
📊 <b>DAILY SUMMARY</b>
{datetime.now(timezone.utc).strftime('%Y-%m-%d')}

━━━━━━━━━━━━━━━━━━━━━━━━━
🔢 <b>Trades:</b> {stats.get('trades_today', 0)} executed
✅ <b>Remaining:</b> {stats.get('trades_remaining', 0)} today
{pnl_emoji} <b>P&L:</b> ${pnl:+.2f}
📉 <b>Total Loss:</b> ${stats.get('daily_loss', 0):.2f}
⚡ <b>Consecutive Losses:</b> {stats.get('consecutive_losses', 0)}
━━━━━━━━━━━━━━━━━━━━━━━━━

<i>Polymarket Weather Bot</i>
""".strip()

            return self._send_message(message)

        except Exception as e:
            logger.error(f"Error send_daily_summary: {e}")
            return False

    # ── Error / status alerts ─────────────────────────────────────────────────

    def send_error_alert(self, error_message: str) -> bool:
        """Kirim alert error/warning."""
        try:
            message = f"""
🚨 <b>BOT ALERT</b>

{error_message}

⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"Error send_error_alert: {e}")
            return False

    def send_pause_alert(self, reason: str) -> bool:
        """Kirim notifikasi bot di-pause."""
        try:
            message = f"""
🛑 <b>BOT PAUSED</b>

<b>Reason:</b> {reason}

⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

Gunakan <code>/unpause</code> untuk melanjutkan.
""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"Error send_pause_alert: {e}")
            return False

    def send_resume_alert(self) -> bool:
        """Kirim notifikasi bot di-unpause."""
        try:
            message = f"""
✅ <b>BOT RESUMED</b>

Bot aktif kembali dan akan scan peluang setiap {config.CHECK_INTERVAL_MINUTES()} menit.

⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"Error send_resume_alert: {e}")
            return False

    # ── Connection test ────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """Test koneksi Telegram. Baca settings dari config/DB."""
        try:
            message = f"""
✅ <b>BOT CONNECTED</b>

Weather Trading Bot online dan siap!

⚙️ <b>Konfigurasi aktif:</b>
- Mode: {config.AUTOMATION_MODE()}
- Scan interval: setiap {config.CHECK_INTERVAL_MINUTES()} menit
- Min edge: {config.MIN_EDGE_PCT()}%
- Min confidence: {config.MIN_CONFIDENCE_PCT()}%
- Max bet: {config.MAX_BET_PCT()}% bankroll
- Max trades/hari: {config.MAX_DAILY_TRADES()}

🌤️ <b>Weather sources:</b>
- US cities → NOAA
- Global → Open-Meteo
- Verifikasi → Wunderground

🚀 Bot aktif dan scanning!

<i>Test message berhasil dikirim.</i>
""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _check_cooldown(self, market_id: str) -> bool:
        """
        Cek apakah boleh kirim alert untuk market ini.
        Returns True jika boleh kirim (cooldown sudah lewat atau belum pernah alert).
        """
        cooldown = config.ALERT_COOLDOWN_SECONDS()
        last     = self._last_alert_time.get(market_id, 0)
        return (time.time() - last) >= cooldown

    def _format_signal_alert(self, signal: Dict) -> str:
        """Format signal sebagai HTML message untuk Telegram."""

        # Confidence emoji
        confidence = signal.get("confidence", 0)
        if confidence >= 90:
            conf_emoji = "🔥🔥🔥"
        elif confidence >= 80:
            conf_emoji = "🔥🔥"
        else:
            conf_emoji = "🔥"

        # Risk level berdasarkan edge
        edge = signal.get("edge", 0)
        if edge >= 30:
            risk = "LOW RISK"
        elif edge >= 20:
            risk = "MEDIUM RISK"
        else:
            risk = "MODERATE RISK"

        # FIX: fair_value & current_price adalah 0-1, tampilkan sebagai %
        fair_value    = signal.get("fair_value", 0) * 100
        current_price = signal.get("current_price", 0) * 100

        # FIX: forecast_conditions tidak ada di signal → pakai sources_used
        sources = ", ".join(signal.get("sources_used", ["N/A"]))

        # End date
        end_date = signal.get("market_end_date")
        if isinstance(end_date, datetime):
            end_str = end_date.strftime("%Y-%m-%d %H:%M UTC")
        else:
            end_str = str(end_date) if end_date else "TBD"

        # Bracket-specific info
        bracket_line = ""
        if signal.get("signal_type") == "weather_temperature_bracket":
            bracket_line = f"\n🌡️ <b>Bracket:</b> {signal.get('bracket_label', '')}"
            if signal.get("forecast_temp"):
                bracket_line += f" | Forecast: {signal.get('forecast_temp')}°C"

        message = f"""
{conf_emoji} <b>WEATHER ARBITRAGE SIGNAL</b>

📍 <b>Location:</b> {signal.get('location', '')}
📅 <b>Date:</b> {signal.get('target_date', '')}{bracket_line}

<b>❓ Market:</b>
{signal.get('market_question', '')}

━━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>ANALYSIS</b>

<b>Weather Forecast:</b> {signal.get('noaa_probability', 0):.0f}% <i>({sources})</i>
<b>Market Odds:</b> {signal.get('market_probability', 0):.0f}%
<b>Edge:</b> +{edge:.0f}% 🎯

━━━━━━━━━━━━━━━━━━━━━━━━━
💰 <b>OPPORTUNITY</b>

<b>Direction:</b> {'✅ BUY YES' if signal.get('direction') == 'YES' else '❌ BUY NO'}
<b>Current Price:</b> {current_price:.1f}%
<b>Fair Value:</b> {fair_value:.1f}%
<b>Expected Value:</b> +{signal.get('expected_value', 0):.1f}%
<b>Payout:</b> {signal.get('payout_multiplier', 0):.2f}x

━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 <b>RECOMMENDATION</b>

<b>Confidence:</b> {confidence:.0f}% | {risk}
<b>Sources:</b> {sources} ({signal.get('source_count', 1)} source)

<b>Reasoning:</b>
<i>{signal.get('reasoning', '')}</i>

━━━━━━━━━━━━━━━━━━━━━━━━━
📈 <b>Market Info</b>

<b>Volume:</b> ${signal.get('market_volume', 0):,.0f}
<b>Liquidity:</b> ${signal.get('market_liquidity', 0):,.0f}
<b>Closes:</b> {end_str}

🔗 <a href="{signal.get('market_url', '')}">View on Polymarket</a>

━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ <b>Execute this trade?</b>
""".strip()

        return message

    def _send_message(self, text: str, reply_markup: Dict = None) -> bool:
        """Kirim message ke Telegram."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram tidak dikonfigurasi — pesan dilewati")
            return False

        try:
            payload = {
                "chat_id":                  self.chat_id,
                "text":                     text,
                "parse_mode":               "HTML",
                "disable_web_page_preview": True,
            }

            if reply_markup:
                import json
                payload["reply_markup"] = json.dumps(reply_markup)

            r = requests.post(
                f"{self.base_url}/sendMessage",
                json=payload,
                timeout=10,
            )
            r.raise_for_status()
            return r.json().get("ok", False)

        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram API error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error _send_message: {e}")
            return False