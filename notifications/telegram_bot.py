"""
telegram_bot.py
================
Sends alerts and handles button interactions.

Fixes:
  - Hapus referensi config functions yang sudah dihapus
    (CHECK_INTERVAL_MINUTES, MIN_EDGE_PCT, MIN_CONFIDENCE_PCT, MAX_DAILY_TRADES)
  - Update test_connection() dan send_resume_alert() pakai config baru
  - Update _format_signal_alert() untuk volume_distribution signal type
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

import config

logger = logging.getLogger(__name__)


class TelegramBot:

    def __init__(self):
        self.token    = config.TELEGRAM_BOT_TOKEN
        self.chat_id  = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self._last_alert_time: Dict[str, float] = {}

        if not self.token or not self.chat_id:
            logger.warning("⚠️  Telegram tidak dikonfigurasi")

    # ── Signal alert ───────────────────────────────────────────────────────────

    def send_signal_alert(self, signal: Dict) -> bool:
        try:
            market_id = signal.get("market_id", "")
            if not self._check_cooldown(market_id):
                logger.info(f"⏳ Alert cooldown: {market_id}")
                return False

            message  = self._format_signal_alert(signal)
            keyboard = {"inline_keyboard": [[
                {"text": "✅ EXECUTE", "callback_data": f"execute:{market_id}"},
                {"text": "❌ SKIP",    "callback_data": f"skip:{market_id}"},
            ]]}

            success = self._send_message(message, keyboard)
            if success:
                self._last_alert_time[market_id] = time.time()
                logger.info(f"✅ Alert: {signal.get('market_question','')[:50]}")
            return success
        except Exception as e:
            logger.error(f"send_signal_alert error: {e}")
            return False

    # ── Trade confirmation ────────────────────────────────────────────────────

    def send_execution_confirmation(self, trade: Dict) -> bool:
        try:
            executed_at = trade.get("executed_at")
            time_str    = executed_at.strftime("%Y-%m-%d %H:%M UTC") if isinstance(executed_at, datetime) else str(executed_at)
            message = f"""✅ <b>TRADE EXECUTED</b>

📝 Trade ID: <code>{str(trade.get('trade_id',''))[:20]}</code>
💰 Amount  : ${trade.get('bet_size', 0):.2f}
📊 Dir     : {trade.get('direction', '')}
💵 Entry   : {trade.get('entry_price', 0):.4f}
📈 Shares  : {trade.get('shares', 0):.2f}

<b>Market:</b>
{trade.get('market_question', '')}

⏰ {time_str}
💳 Tx: <code>{str(trade.get('tx_hash','N/A'))[:20]}</code>""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"send_execution_confirmation error: {e}")
            return False

    # ── Position / settlement ─────────────────────────────────────────────────

    def send_position_update(self, position: Dict) -> bool:
        try:
            pnl   = position.get("unrealized_pnl", 0)
            emoji = "📈" if pnl > 0 else "📉"
            message = f"""{emoji} <b>POSITION UPDATE</b>

<b>Market:</b> {str(position.get('market_question',''))[:80]}
💰 Invested : ${position.get('amount_invested', 0):.2f}
📊 Entry    : {position.get('entry_price', 0):.4f}
💵 Current  : {position.get('current_price', 0):.4f}
<b>Unrealized P&L:</b> ${pnl:+.2f}

⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"send_position_update error: {e}")
            return False

    def send_settlement_alert(self, position: Dict) -> bool:
        try:
            outcome = (position.get("outcome") or "").lower()
            emoji   = "🎉" if outcome == "win" else "😔"
            pnl     = position.get("realized_pnl", 0)
            message = f"""{emoji} <b>POSITION SETTLED — {outcome.upper()}</b>

<b>Market:</b> {position.get('market_question', '')}
💰 Invested : ${position.get('amount_invested', 0):.2f}
💵 Payout   : ${position.get('payout', 0):.2f}
<b>P&L:</b> ${pnl:+.2f}""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"send_settlement_alert error: {e}")
            return False

    # ── Daily summary ──────────────────────────────────────────────────────────

    def send_daily_summary(self, stats: Dict) -> bool:
        try:
            pnl   = stats.get("daily_pnl", 0)
            emoji = "📈" if pnl >= 0 else "📉"
            message = f"""📊 <b>DAILY SUMMARY</b> — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

🔢 Trades   : {stats.get('trades_today', 0)} executed
{emoji} P&L     : ${pnl:+.2f}
📉 Loss     : ${stats.get('daily_loss', 0):.2f}
⚡ Consec.  : {stats.get('consecutive_losses', 0)} losses

<i>Polymarket Weather Bot</i>""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"send_daily_summary error: {e}")
            return False

    # ── Error / pause alerts ──────────────────────────────────────────────────

    def send_error_alert(self, error_message: str) -> bool:
        try:
            message = f"""🚨 <b>BOT ALERT</b>

{error_message}

⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"send_error_alert error: {e}")
            return False

    def send_pause_alert(self, reason: str) -> bool:
        try:
            message = f"""🛑 <b>BOT PAUSED</b>

<b>Reason:</b> {reason}
⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

Gunakan /unpause untuk melanjutkan.""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"send_pause_alert error: {e}")
            return False

    def send_resume_alert(self) -> bool:
        """FIX: Pakai config functions yang masih ada."""
        try:
            message = f"""✅ <b>BOT RESUMED</b>

Bot aktif kembali!

⚙️ Mode         : {config.AUTOMATION_MODE()}
🆕 Fresh scan   : setiap {config.FRESH_MARKET_SCAN_INTERVAL()} menit
📊 Pre-closing  : {config.PRE_CLOSING_HOURS():.0f}h sebelum close
⚡ Auto-trade   : conf ≥ {config.AUTO_TRADE_THRESHOLD():.0f}% → ${config.AUTO_TRADE_AMOUNT():.0f}

⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"send_resume_alert error: {e}")
            return False

    # ── Connection test ────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """FIX: Pakai config functions yang masih ada."""
        try:
            message = f"""✅ <b>BOT CONNECTED</b>

Polymarket Weather Trading Bot online!

⚙️ <b>Strategy: Volume Distribution</b>
- Mode         : {config.AUTOMATION_MODE()}
- Fresh market : ${config.FRESH_MARKET_AUTO_BET()}/bracket, setiap {config.FRESH_MARKET_SCAN_INTERVAL()} menit
- Pre-closing  : {config.PRE_CLOSING_HOURS():.0f}h sebelum closing
- Auto-trade   : conf ≥ {config.AUTO_TRADE_THRESHOLD():.0f}% → ${config.AUTO_TRADE_AMOUNT():.0f}
- Max bet      : {config.MAX_BET_PCT()}% bankroll

🚀 Bot aktif dan monitoring!
Gunakan /help untuk daftar commands.

<i>Test message berhasil dikirim.</i>""".strip()
            return self._send_message(message)
        except Exception as e:
            logger.error(f"test_connection error: {e}")
            return False

    # ── Format signal ─────────────────────────────────────────────────────────

    def _format_signal_alert(self, signal: Dict) -> str:
        """Format signal alert — support volume_distribution dan fresh_market."""
        confidence = signal.get("confidence", 0)
        edge       = signal.get("edge", 0)
        sig_type   = signal.get("signal_type", "")

        conf_emoji = "🔥🔥🔥" if confidence >= 90 else "🔥🔥" if confidence >= 80 else "🔥"
        risk       = "LOW RISK" if edge >= 30 else "MEDIUM RISK" if edge >= 20 else "MODERATE RISK"

        fair_value    = signal.get("fair_value", 0) * 100
        current_price = signal.get("current_price", 0) * 100

        end_date = signal.get("market_end_date")
        end_str  = end_date.strftime("%Y-%m-%d %H:%M UTC") if isinstance(end_date, datetime) else str(end_date or "TBD")

        # Signal type header
        if sig_type == "fresh_market_bracket":
            type_header = "🆕 FRESH MARKET SIGNAL"
            extra_info  = f"\n🆕 <b>Fresh market</b> — sebelum NO flood"
        elif sig_type == "volume_distribution":
            vol_share = signal.get("vol_share", 0)
            total_vol = signal.get("total_volume", 0)
            hrs_left  = signal.get("hours_left", 0)
            type_header = "📊 VOLUME DISTRIBUTION SIGNAL"
            extra_info  = (
                f"\n📊 <b>Vol Share:</b> {vol_share:.0f}% dari ${total_vol:,.0f}"
                f"\n⏱️ <b>Hours left:</b> {hrs_left:.1f}h"
            )
        else:
            type_header = "🌤️ WEATHER SIGNAL"
            extra_info  = ""

        message = f"""{conf_emoji} <b>{type_header}</b>

📍 <b>Location:</b> {signal.get('location', '')}
📅 <b>Date:</b> {signal.get('target_date', '')}

<b>❓ Market:</b>
{signal.get('market_question', '')}
{extra_info}

━━━━━━━━━━━━━━━━━━━━━━━━━
💰 <b>OPPORTUNITY</b>

<b>Direction:</b> {'✅ BUY YES' if signal.get('direction') == 'YES' else '❌ BUY NO'}
<b>Current Price:</b> {current_price:.1f}%
<b>Fair Value:</b> {fair_value:.1f}%
<b>Edge:</b> +{edge:.0f}% 🎯
<b>Expected Value:</b> +{signal.get('expected_value', 0):.1f}%
<b>Payout:</b> {signal.get('payout_multiplier', 1/signal.get('current_price',1)*100/100 if signal.get('current_price',0) > 0 else 0):.2f}x

━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 <b>CONFIDENCE: {confidence:.0f}%</b> | {risk}

<b>Reasoning:</b>
<i>{signal.get('reasoning', '')[:200]}</i>

━━━━━━━━━━━━━━━━━━━━━━━━━
📈 Volume  : ${signal.get('market_volume', 0):,.0f}
💧 Liq     : ${signal.get('market_liquidity', 0):,.0f}
⏰ Closes  : {end_str}

🔗 <a href="{signal.get('market_url', '')}">View on Polymarket</a>

⚠️ <b>Execute this trade?</b>""".strip()

        return message

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check_cooldown(self, market_id: str) -> bool:
        cooldown = config.ALERT_COOLDOWN_SECONDS()
        return (time.time() - self._last_alert_time.get(market_id, 0)) >= cooldown

    def _send_message(self, text: str, reply_markup: Dict = None) -> bool:
        if not self.token or not self.chat_id:
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
            r = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            r.raise_for_status()
            return r.json().get("ok", False)
        except Exception as e:
            logger.error(f"_send_message error: {e}")
            return False