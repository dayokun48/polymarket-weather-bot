"""
weather_analyzer.py
====================
ROMBAK TOTAL — strategi baru: Volume Distribution Analysis.

Forecast-based strategy (ECMWF/GFS) dihapus karena error ±3-5°C,
tidak cukup akurat untuk bracket 1°C precision.

Strategi baru:
  1. Fresh market (opening) → FreshMarketMonitor handle
  2. Pre-closing (4h before) → VolumeAnalyzer handle
  3. weather_analyzer sekarang hanya wrapper/coordinator

find_opportunities() sekarang delegate ke VolumeAnalyzer.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)


class WeatherAnalyzer:
    """
    Coordinator untuk weather market analysis.
    Delegate ke VolumeAnalyzer untuk signal generation.
    """

    def __init__(self, noaa_collector=None, polymarket_collector=None):
        # Collectors masih disimpan untuk backward compatibility
        # tapi tidak dipakai untuk signal generation
        self.weather    = noaa_collector
        self.polymarket = polymarket_collector

        # Volume analyzer sebagai primary signal source
        from analyzers.volume_analyzer import VolumeAnalyzer
        self._volume_analyzer = VolumeAnalyzer()

    # ── Main entry ────────────────────────────────────────────────────────────

    def find_opportunities(self, location: str = None) -> List[Dict]:
        """
        Scan weather markets dan cari peluang trading.
        Delegate ke VolumeAnalyzer.scan_pre_closing().

        Args:
            location: tidak dipakai lagi (kept for backward compatibility)

        Returns list of signals dari volume distribution analysis.
        """
        logger.info("📊 WeatherAnalyzer → VolumeAnalyzer.scan_pre_closing()")
        return self._volume_analyzer.scan_pre_closing()

    def reset_daily(self):
        """Reset state harian."""
        self._volume_analyzer.reset_daily()

    # ── Kept for FreshMarketMonitor compatibility ─────────────────────────────

    def _estimate_temp_probability(self, question: str, consensus: Dict) -> Optional[float]:
        """
        Kept for FreshMarketMonitor._predict_winner() compatibility.
        Tapi untuk strategi baru tidak dipakai untuk signal generation.
        """
        import re, math

        avg_temp = consensus.get("avg_temp_high") if consensus else None
        if avg_temp is None:
            return None

        TEMP_STD_DEV = 2.5

        def norm_cdf(x):
            return 0.5 * (1 + math.erf(x / (TEMP_STD_DEV * math.sqrt(2))))

        q = question

        def f2c(f): return (f - 32) * 5 / 9

        m = re.search(r"be\s+([\d.]+)°?C\s+on", q, re.IGNORECASE)
        if m:
            t = float(m.group(1))
            return round(norm_cdf(t + 0.5 - avg_temp) - norm_cdf(t - 0.5 - avg_temp), 3)

        m = re.search(r"([\d.]+)°?C or higher", q, re.IGNORECASE)
        if m:
            return round(1 - norm_cdf(float(m.group(1)) - avg_temp), 3)

        m = re.search(r"([\d.]+)°?C or below", q, re.IGNORECASE)
        if m:
            return round(norm_cdf(float(m.group(1)) - avg_temp), 3)

        m = re.search(r"be\s+([\d.]+)°?C\b", q, re.IGNORECASE)
        if m:
            t = float(m.group(1))
            return round(norm_cdf(t + 0.5 - avg_temp) - norm_cdf(t - 0.5 - avg_temp), 3)

        return None