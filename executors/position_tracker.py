"""
Position Tracker
Tracks open positions and calculates P&L
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class PositionTracker:
    """
    Track open trading positions
    Calculate unrealized and realized P&L
    """
    
    def __init__(self):
        self.open_positions = []
        self.closed_positions = []
        self.total_invested = 0.0
        self.total_returned = 0.0
    
    def add_position(self, trade: Dict):
        """
        Add new open position
        
        Args:
            trade: Trade confirmation dict
        """
        position = {
            'position_id': trade['trade_id'],
            'market_id': trade['market_id'],
            'market_question': trade['market_question'],
            'direction': trade['direction'],
            'entry_price': trade['entry_price'],
            'shares': trade['shares'],
            'amount_invested': trade['bet_size'],
            'opened_at': trade['executed_at'],
            'status': 'OPEN',
            'current_price': trade['entry_price'],
            'unrealized_pnl': 0.0
        }
        
        self.open_positions.append(position)
        self.total_invested += trade['bet_size']
        
        logger.info(f"📊 Position added: {position['position_id'][:20]}...")
        logger.info(f"   Market: {position['market_question'][:50]}...")
        logger.info(f"   Invested: ${position['amount_invested']:.2f}")
    
    def update_position_price(self, position_id: str, current_price: float):
        """
        Update current market price for position
        
        Args:
            position_id: Position identifier
            current_price: Current market price
        """
        for position in self.open_positions:
            if position['position_id'] == position_id:
                position['current_price'] = current_price
                
                # Calculate unrealized P&L
                current_value = position['shares'] * current_price
                position['unrealized_pnl'] = current_value - position['amount_invested']
                
                logger.debug(f"Updated position {position_id[:10]}: "
                           f"Price ${current_price:.4f}, "
                           f"P&L ${position['unrealized_pnl']:.2f}")
                break
    
    def close_position(self, position_id: str, outcome: str, 
                      final_price: float = None) -> Optional[Dict]:
        """
        Close position and calculate realized P&L
        
        Args:
            position_id: Position identifier
            outcome: 'WIN' or 'LOSS'
            final_price: Final settlement price
            
        Returns:
            Closed position dict
        """
        position = None
        for i, pos in enumerate(self.open_positions):
            if pos['position_id'] == position_id:
                position = self.open_positions.pop(i)
                break
        
        if not position:
            logger.error(f"Position {position_id} not found")
            return None
        
        # Calculate payout
        if outcome == 'WIN':
            # Winning shares pay $1 each
            payout = position['shares'] * 1.0
        else:
            # Losing shares pay $0
            payout = 0.0
        
        realized_pnl = payout - position['amount_invested']
        
        # Update position
        position['status'] = 'CLOSED'
        position['outcome'] = outcome
        position['closed_at'] = datetime.utcnow()
        position['payout'] = payout
        position['realized_pnl'] = realized_pnl
        
        self.closed_positions.append(position)
        self.total_returned += payout
        
        logger.info("=" * 60)
        logger.info(f"🔒 POSITION CLOSED")
        logger.info(f"Market: {position['market_question'][:50]}...")
        logger.info(f"Outcome: {outcome}")
        logger.info(f"Invested: ${position['amount_invested']:.2f}")
        logger.info(f"Payout: ${payout:.2f}")
        logger.info(f"P&L: ${realized_pnl:+.2f}")
        logger.info("=" * 60)
        
        return position
    
    def get_open_positions(self) -> List[Dict]:
        """Get all open positions"""
        return self.open_positions.copy()
    
    def get_position_by_id(self, position_id: str) -> Optional[Dict]:
        """Get specific position by ID"""
        for position in self.open_positions:
            if position['position_id'] == position_id:
                return position.copy()
        return None
    
    def get_total_exposure(self) -> float:
        """Get total amount in open positions"""
        return sum(p['amount_invested'] for p in self.open_positions)
    
    def get_unrealized_pnl(self) -> float:
        """Get total unrealized P&L"""
        return sum(p['unrealized_pnl'] for p in self.open_positions)
    
    def get_realized_pnl(self) -> float:
        """Get total realized P&L from closed positions"""
        return sum(p['realized_pnl'] for p in self.closed_positions)
    
    def get_total_pnl(self) -> float:
        """Get total P&L (realized + unrealized)"""
        return self.get_realized_pnl() + self.get_unrealized_pnl()
    
    def get_performance_stats(self) -> Dict:
        """
        Get performance statistics
        
        Returns:
            Dict with win rate, ROI, etc.
        """
        total_closed = len(self.closed_positions)
        
        if total_closed == 0:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_invested': self.total_invested,
                'total_returned': self.total_returned,
                'realized_pnl': 0.0,
                'unrealized_pnl': self.get_unrealized_pnl(),
                'total_pnl': self.get_unrealized_pnl(),
                'roi': 0.0
            }
        
        wins = sum(1 for p in self.closed_positions if p['outcome'] == 'WIN')
        losses = total_closed - wins
        win_rate = (wins / total_closed) * 100 if total_closed > 0 else 0
        
        realized_pnl = self.get_realized_pnl()
        unrealized_pnl = self.get_unrealized_pnl()
        total_pnl = realized_pnl + unrealized_pnl
        
        roi = (total_pnl / self.total_invested * 100) if self.total_invested > 0 else 0
        
        return {
            'total_trades': total_closed,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'total_invested': self.total_invested,
            'total_returned': self.total_returned,
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'total_pnl': total_pnl,
            'roi': roi,
            'open_positions': len(self.open_positions),
            'total_exposure': self.get_total_exposure()
        }
    
    def get_summary(self) -> str:
        """
        Get text summary of performance
        
        Returns:
            Formatted summary string
        """
        stats = self.get_performance_stats()
        
        summary = f"""
📊 POSITION TRACKER SUMMARY

Open Positions: {stats['open_positions']}
Total Exposure: ${stats['total_exposure']:.2f}
Unrealized P&L: ${stats['unrealized_pnl']:+.2f}

Closed Trades: {stats['total_trades']}
Wins: {stats['wins']} | Losses: {stats['losses']}
Win Rate: {stats['win_rate']:.1f}%

Total Invested: ${stats['total_invested']:.2f}
Total Returned: ${stats['total_returned']:.2f}
Realized P&L: ${stats['realized_pnl']:+.2f}

TOTAL P&L: ${stats['total_pnl']:+.2f}
ROI: {stats['roi']:+.1f}%
        """
        
        return summary.strip()
