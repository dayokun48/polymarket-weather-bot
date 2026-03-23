"""
Risk Manager
Validates trades and manages risk limits
"""

import config
import logging
from datetime import datetime, timedelta
from typing import Tuple, Dict

logger = logging.getLogger(__name__)

class RiskManager:
    """
    Manage trading risks and limits
    """
    
    def __init__(self):
        self.daily_trades = []
        self.consecutive_losses = 0
        self.paused = False
    
    def validate_signal(self, signal: Dict) -> Tuple[bool, str]:
        """
        Validate if signal should be traded
        
        Returns:
            (is_valid, reason)
        """
        
        # Check if bot is paused
        if self.paused:
            return False, "Bot is paused"
        
        # Check edge threshold
        if signal['edge'] < config.MIN_EDGE_PCT:
            return False, f"Edge {signal['edge']:.1f}% below threshold {config.MIN_EDGE_PCT}%"
        
        # Check confidence threshold
        if signal['confidence'] < config.MIN_CONFIDENCE_PCT:
            return False, f"Confidence {signal['confidence']:.1f}% below threshold {config.MIN_CONFIDENCE_PCT}%"
        
        # Check daily trade limit
        today = datetime.now().date()
        today_trades = [t for t in self.daily_trades if t['date'] == today]
        
        if len(today_trades) >= config.MAX_DAILY_TRADES:
            return False, f"Daily trade limit reached ({config.MAX_DAILY_TRADES})"
        
        # Check market liquidity (min $1000)
        if signal['market_liquidity'] < 1000:
            return False, f"Liquidity too low (${signal['market_liquidity']:.0f})"
        
        # Check consecutive losses
        if self.consecutive_losses >= 3:
            return False, "3 consecutive losses - auto-pause"
        
        # All checks passed
        return True, "OK"
    
    def calculate_position_size(self, signal: Dict, bankroll: float) -> float:
        """
        Calculate recommended bet size
        
        Args:
            signal: Trading signal
            bankroll: Current bankroll
            
        Returns:
            Bet size in dollars
        """
        # Base position size (2-5% of bankroll)
        base_pct = config.MAX_BET_PCT
        
        # Adjust based on confidence
        if signal['confidence'] > 90:
            multiplier = 1.0  # 5% max
        elif signal['confidence'] > 80:
            multiplier = 0.8  # 4%
        else:
            multiplier = 0.6  # 3%
        
        position_pct = base_pct * multiplier
        bet_size = bankroll * position_pct
        
        # Round to nearest dollar
        return round(bet_size, 0)
    
    def record_trade(self, signal: Dict, amount: float):
        """Record trade for tracking"""
        self.daily_trades.append({
            'date': datetime.now().date(),
            'signal_id': signal.get('market_id'),
            'amount': amount,
            'timestamp': datetime.now()
        })
    
    def record_outcome(self, won: bool):
        """Record trade outcome for risk tracking"""
        if won:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            
            # Auto-pause after 3 losses
            if self.consecutive_losses >= 3:
                self.paused = True
                logger.warning("🛑 Auto-paused after 3 consecutive losses")
    
    def get_daily_stats(self) -> Dict:
        """Get today's trading statistics"""
        today = datetime.now().date()
        today_trades = [t for t in self.daily_trades if t['date'] == today]
        
        return {
            'trades_today': len(today_trades),
            'trades_remaining': config.MAX_DAILY_TRADES - len(today_trades),
            'total_exposure': sum(t['amount'] for t in today_trades),
            'consecutive_losses': self.consecutive_losses,
            'paused': self.paused
        }
    
    def reset_daily_limits(self):
        """Reset daily limits (called at midnight)"""
        today = datetime.now().date()
        self.daily_trades = [t for t in self.daily_trades 
                            if t['date'] >= today - timedelta(days=7)]
    
    def unpause(self):
        """Manually unpause bot"""
        self.paused = False
        self.consecutive_losses = 0
        logger.info("✅ Bot unpaused")

