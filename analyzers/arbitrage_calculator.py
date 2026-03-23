"""
Arbitrage Calculator
Calculates fair value, edge, expected value
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

class ArbitrageCalculator:
    """
    Calculate arbitrage metrics
    """
    
    def calculate_edge(self, fair_value: float, market_price: float) -> float:
        """
        Calculate edge percentage
        
        Args:
            fair_value: Your estimated probability (0-1)
            market_price: Market's current price (0-1)
            
        Returns:
            Edge as percentage
        """
        edge = abs(fair_value - market_price)
        return edge * 100
    
    def calculate_expected_value(self, fair_value: float, market_price: float,
                                direction: str) -> float:
        """
        Calculate expected value of bet
        
        Returns:
            Expected value as percentage
        """
        if direction == 'YES':
            payout = 1 / market_price if market_price > 0 else 2
            ev = (fair_value * payout) - 1
        else:
            payout = 1 / (1 - market_price) if market_price < 1 else 2
            ev = ((1 - fair_value) * payout) - 1
        
        return ev * 100
    
    def calculate_kelly_bet(self, edge: float, odds: float, bankroll: float) -> float:
        """
        Calculate optimal bet size using Kelly Criterion
        
        Args:
            edge: Your edge (0-1)
            odds: Payout multiplier
            bankroll: Total bankroll
            
        Returns:
            Recommended bet size
        """
        if edge <= 0 or odds <= 1:
            return 0
        
        # Kelly formula: (edge * odds - 1) / (odds - 1)
        kelly_fraction = (edge * odds - 1) / (odds - 1)
        
        # Use fractional Kelly (25%) for safety
        fractional_kelly = kelly_fraction * 0.25
        
        # Cap at 5% of bankroll
        bet_size = min(fractional_kelly * bankroll, bankroll * 0.05)
        
        return max(bet_size, 0)
    
    def calculate_breakeven_probability(self, odds: float) -> float:
        """
        Calculate breakeven win probability
        
        Args:
            odds: Payout multiplier
            
        Returns:
            Breakeven probability (0-1)
        """
        return 1 / odds
    
    def calculate_roi(self, win_prob: float, odds: float) -> float:
        """
        Calculate expected ROI
        
        Returns:
            ROI as percentage
        """
        expected_return = win_prob * odds
        roi = (expected_return - 1) * 100
        
        return roi
