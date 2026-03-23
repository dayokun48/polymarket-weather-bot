"""
Telegram Bot
Sends alerts and handles button interactions
"""

import config
import logging
import requests
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class TelegramBot:
    """
    Send Telegram notifications
    Handle button callbacks
    """
    
    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
        if not self.token or not self.chat_id:
            logger.warning("⚠️ Telegram not configured - alerts disabled")
    
    def send_signal_alert(self, signal: Dict) -> bool:
        """
        Send trading signal alert to Telegram
        
        Args:
            signal: Trading signal dict
            
        Returns:
            True if sent successfully
        """
        try:
            # Format alert message
            message = self._format_signal_alert(signal)
            
            # Create inline keyboard with buttons
            keyboard = {
                'inline_keyboard': [[
                    {
                        'text': '✅ EXECUTE',
                        'callback_data': f"execute:{signal['market_id']}"
                    },
                    {
                        'text': '❌ SKIP',
                        'callback_data': f"skip:{signal['market_id']}"
                    }
                ]]
            }
            
            # Send message
            success = self._send_message(message, keyboard)
            
            if success:
                logger.info(f"✅ Alert sent for {signal['market_question'][:50]}...")
            else:
                logger.error("❌ Failed to send alert")
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending signal alert: {e}")
            return False
    
    def send_execution_confirmation(self, trade: Dict) -> bool:
        """
        Send trade execution confirmation
        
        Args:
            trade: Trade confirmation dict
            
        Returns:
            True if sent successfully
        """
        try:
            message = f"""
✅ <b>TRADE EXECUTED</b>

📝 <b>Trade ID:</b> {trade['trade_id'][:20]}...
💰 <b>Amount:</b> ${trade['bet_size']:.2f}
📊 <b>Direction:</b> {trade['direction']}
💵 <b>Entry Price:</b> {trade['entry_price']:.4f}
📈 <b>Shares:</b> {trade['shares']:.2f}

<b>Market:</b>
{trade['market_question']}

⏰ <b>Executed:</b> {trade['executed_at'].strftime('%Y-%m-%d %H:%M UTC')}
⚡ <b>Gas Fee:</b> ${trade['gas_fee']:.2f}
💳 <b>Total Cost:</b> ${trade['total_cost']:.2f}

<b>Status:</b> {trade['status']}
            """
            
            return self._send_message(message.strip())
            
        except Exception as e:
            logger.error(f"Error sending confirmation: {e}")
            return False
    
    def send_position_update(self, position: Dict) -> bool:
        """Send position update (P&L changes)"""
        try:
            pnl_emoji = "📈" if position['unrealized_pnl'] > 0 else "📉"
            
            message = f"""
{pnl_emoji} <b>POSITION UPDATE</b>

📝 <b>Position:</b> {position['position_id'][:20]}...

<b>Market:</b>
{position['market_question'][:60]}...

💰 <b>Invested:</b> ${position['amount_invested']:.2f}
📊 <b>Entry Price:</b> {position['entry_price']:.4f}
💵 <b>Current Price:</b> {position['current_price']:.4f}

<b>Unrealized P&L:</b> ${position['unrealized_pnl']:+.2f}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
            """
            
            return self._send_message(message.strip())
            
        except Exception as e:
            logger.error(f"Error sending position update: {e}")
            return False
    
    def send_settlement_alert(self, position: Dict) -> bool:
        """Send position settlement notification"""
        try:
            outcome_emoji = "🎉" if position['outcome'] == 'WIN' else "😔"
            
            message = f"""
{outcome_emoji} <b>POSITION SETTLED - {position['outcome']}</b>

<b>Market:</b>
{position['market_question']}

💰 <b>Invested:</b> ${position['amount_invested']:.2f}
💵 <b>Payout:</b> ${position['payout']:.2f}
<b>P&L:</b> ${position['realized_pnl']:+.2f}

📊 <b>Entry:</b> {position['entry_price']:.4f}
📈 <b>Shares:</b> {position['shares']:.2f}
⏰ <b>Duration:</b> {(position['closed_at'] - position['opened_at']).days} days

<b>Status:</b> CLOSED
            """
            
            return self._send_message(message.strip())
            
        except Exception as e:
            logger.error(f"Error sending settlement: {e}")
            return False
    
    def send_daily_summary(self, summary: str) -> bool:
        """Send daily performance summary"""
        try:
            message = f"""
📊 <b>DAILY SUMMARY</b>
{datetime.now().strftime('%Y-%m-%d')}

{summary}

<i>Weather Trading Bot v1.0</i>
            """
            
            return self._send_message(message.strip())
            
        except Exception as e:
            logger.error(f"Error sending summary: {e}")
            return False
    
    def send_error_alert(self, error_message: str) -> bool:
        """Send error/warning alert"""
        try:
            message = f"""
🚨 <b>BOT ALERT</b>

{error_message}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
            """
            
            return self._send_message(message.strip())
            
        except Exception as e:
            logger.error(f"Error sending error alert: {e}")
            return False
    
    def _format_signal_alert(self, signal: Dict) -> str:
        """Format trading signal as HTML message"""
        
        # Confidence emoji
        if signal['confidence'] > 90:
            conf_emoji = "🔥🔥🔥"
        elif signal['confidence'] > 80:
            conf_emoji = "🔥🔥"
        else:
            conf_emoji = "🔥"
        
        # Risk level
        if signal['edge'] > 30:
            risk = "LOW"
        elif signal['edge'] > 20:
            risk = "MEDIUM"
        else:
            risk = "MODERATE"
        
        message = f"""
{conf_emoji} <b>WEATHER ARBITRAGE SIGNAL</b>

📍 <b>Location:</b> {signal['location']}
📅 <b>Date:</b> {signal['target_date']}

<b>❓ Market:</b>
{signal['market_question']}

━━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>ANALYSIS</b>

<b>NOAA Forecast:</b> {signal['noaa_probability']:.0f}% {signal['forecast_conditions']}
<b>Market Odds:</b> {signal['market_probability']:.0f}%
<b>Arbitrage Edge:</b> +{signal['edge']:.0f}% 🎯

━━━━━━━━━━━━━━━━━━━━━━━━━
💰 <b>OPPORTUNITY</b>

<b>Direction:</b> {'✅ BUY YES' if signal['direction'] == 'YES' else '❌ BUY NO'}
<b>Current Price:</b> {signal['current_price']:.2f}¢
<b>Fair Value:</b> {signal['fair_value']:.2f}¢
<b>Expected Value:</b> +{signal['expected_value']:.1f}%

━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 <b>RECOMMENDATION</b>

<b>Confidence:</b> {signal['confidence']:.0f}%
<b>Risk Level:</b> {risk}

<b>Reasoning:</b>
{signal['reasoning']}

━━━━━━━━━━━━━━━━━━━━━━━━━
📈 <b>Market Info</b>

<b>Volume:</b> ${signal['market_volume']:,.0f}
<b>Liquidity:</b> ${signal['market_liquidity']:,.0f}
<b>Closes:</b> {signal['market_end_date'].strftime('%Y-%m-%d %H:%M UTC') if signal['market_end_date'] else 'TBD'}

🔗 <a href="{signal['market_url']}">View on Polymarket</a>

━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ <b>Execute this trade?</b>
        """
        
        return message.strip()
    
    def _send_message(self, text: str, reply_markup: Dict = None) -> bool:
        """
        Send message to Telegram
        
        Args:
            text: Message text (HTML formatted)
            reply_markup: Optional inline keyboard
            
        Returns:
            True if successful
        """
        if not self.token or not self.chat_id:
            logger.warning("Telegram not configured - skipping message")
            return False
        
        try:
            url = f"{self.base_url}/sendMessage"
            
            payload = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
            
            if reply_markup:
                payload['reply_markup'] = reply_markup
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            return response.json().get('ok', False)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram API error: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False
    
    def test_connection(self) -> bool:
        """Test Telegram connection"""
        try:
            message = """
✅ <b>BOT CONNECTED</b>

Weather Trading Bot is online and ready!

⚙️ <b>Configuration:</b>
- Mode: Semi-Auto
- Alerts: Enabled
- Risk Management: Active

🚀 Bot will scan for opportunities every 2 hours.

<i>Test message sent successfully!</i>
            """
            
            return self._send_message(message.strip())
            
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
