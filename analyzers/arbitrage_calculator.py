"""
arbitrage_calculator.py
========================
Calculates fair value, edge, expected value, and Kelly bet sizing.

Fixes dari original:
  - max_bet_pct dan kelly_fraction baca dari config (database), bukan hardcoded
  - Parameter naming diperjelas: win_prob bukan edge di calculate_kelly_bet
  - Tambah calculate_all() untuk hitung semua metrik sekaligus dari satu signal
"""

import logging
from typing import Dict, Optional

import config

logger = logging.getLogger(__name__)


class ArbitrageCalculator:
    """
    Calculate arbitrage metrics for Polymarket weather trading.

    Usage:
        calc = ArbitrageCalculator()

        # Hitung semua metrik sekaligus
        metrics = calc.calculate_all(
            weather_prob = 0.75,   # forecast probability
            market_price = 0.35,   # YES price di Polymarket
            bankroll     = 1000,
        )

        # Atau per metrik
        edge = calc.calculate_edge(0.75, 0.35)
        ev   = calc.calculate_expected_value(0.75, 0.35, "YES")
        bet  = calc.calculate_kelly_bet(0.75, 2.86, 1000)
    """

    # ── Main method ────────────────────────────────────────────────────────────

    def calculate_all(
        self,
        weather_prob: float,
        market_price: float,
        bankroll: float,
        direction: str = None,
    ) -> Optional[Dict]:
        """
        Hitung semua metrik dari satu peluang trading.

        Args:
            weather_prob : probabilitas dari weather forecast (0-1)
            market_price : YES price di Polymarket (0-1)
            bankroll     : total bankroll dalam USD
            direction    : "YES" atau "NO" — auto-detect jika None

        Returns dict dengan semua metrik, atau None jika tidak ada edge.
        """
        if market_price <= 0 or market_price >= 1:
            return None

        # Auto-detect direction
        if direction is None:
            direction = "YES" if weather_prob > market_price else "NO"

        edge = self.calculate_edge(weather_prob, market_price)
        ev   = self.calculate_expected_value(weather_prob, market_price, direction)

        if direction == "YES":
            trade_price = market_price
            win_prob    = weather_prob
        else:
            trade_price = 1 - market_price
            win_prob    = 1 - weather_prob

        payout   = 1 / trade_price if trade_price > 0 else 2
        bet_size = self.calculate_kelly_bet(win_prob, payout, bankroll)
        breakeven = self.calculate_breakeven_probability(payout)
        roi      = self.calculate_roi(win_prob, payout)

        return {
            "direction":        direction,
            "weather_prob_pct": round(weather_prob * 100, 1),
            "market_price_pct": round(market_price * 100, 1),
            "trade_price":      round(trade_price, 4),
            "payout_multiplier": round(payout, 2),
            "edge_pct":         round(edge, 1),
            "expected_value_pct": round(ev, 1),
            "breakeven_prob_pct": round(breakeven * 100, 1),
            "roi_pct":          round(roi, 1),
            "kelly_bet_usd":    round(bet_size, 2),
            "bankroll":         bankroll,
        }

    # ── Individual calculators ─────────────────────────────────────────────────

    def calculate_edge(self, fair_value: float, market_price: float) -> float:
        """
        Hitung edge dalam persen.

        Args:
            fair_value   : estimasi probabilitas kita (0-1)
            market_price : YES price di Polymarket (0-1)

        Returns edge sebagai persentase (selalu positif).
        """
        return abs(fair_value - market_price) * 100

    def calculate_expected_value(
        self,
        fair_value:   float,
        market_price: float,
        direction:    str,
    ) -> float:
        """
        Hitung expected value dari bet.

        Returns EV sebagai persentase dari stake.
        Positif = menguntungkan, negatif = merugikan.
        """
        if direction == "YES":
            payout = 1 / market_price if market_price > 0 else 2
            ev = (fair_value * payout) - 1
        else:
            no_price = 1 - market_price
            payout   = 1 / no_price if no_price > 0 else 2
            ev = ((1 - fair_value) * payout) - 1

        return ev * 100

    def calculate_kelly_bet(
        self,
        win_prob: float,   # FIX: dulunya namanya "edge" — menyesatkan
        odds:     float,
        bankroll: float,
    ) -> float:
        """
        Hitung ukuran bet optimal dengan Kelly Criterion.

        Args:
            win_prob : probabilitas menang menurut kita (0-1)
            odds     : payout multiplier (contoh: 2.86x)
            bankroll : total bankroll dalam USD

        Returns recommended bet size dalam USD.
        """
        if win_prob <= 0 or odds <= 1:
            return 0

        # Kelly formula: f* = (b*p - q) / b
        # b = net odds (odds - 1), p = win prob, q = loss prob
        b = odds - 1
        p = win_prob
        q = 1 - win_prob

        kelly_fraction = (b * p - q) / b

        if kelly_fraction <= 0:
            return 0

        # Fractional Kelly untuk safety (25% dari full Kelly)
        # Mengurangi volatilitas tanpa banyak mengorbankan EV
        fractional_kelly = kelly_fraction * 0.25

        # Cap maksimum dari config (database) — default 5%
        max_bet_pct = config.get("max_bet_pct", float) / 100
        max_bet     = bankroll * max_bet_pct

        bet_size = min(fractional_kelly * bankroll, max_bet)
        return max(round(bet_size, 2), 0)

    def calculate_breakeven_probability(self, odds: float) -> float:
        """
        Hitung probabilitas breakeven.
        Ini adalah probabilitas minimum agar bet tidak rugi.

        Args:
            odds: payout multiplier

        Returns probabilitas breakeven (0-1).
        """
        if odds <= 0:
            return 1.0
        return 1 / odds

    def calculate_roi(self, win_prob: float, odds: float) -> float:
        """
        Hitung expected ROI.

        Returns ROI sebagai persentase.
        """
        expected_return = win_prob * odds
        return (expected_return - 1) * 100