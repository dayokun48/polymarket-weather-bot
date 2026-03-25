"""
weather_analyzer.py
====================
Analyzes weather forecasts vs Polymarket odds.

Fixes vs sebelumnya (sesuai schema database):
  - Field naming sesuai kolom tabel signals:
    weather_prob  → noaa_probability (tapi tetap simpan keduanya di signal dict)
    market_prob   → market_probability
  - Signal dict sekarang punya semua field yang dibutuhkan risk_manager
    untuk insert ke signals table
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)


class WeatherAnalyzer:
    """
    Analyze weather forecasts vs Polymarket odds.
    Handles both market types:
      - Binary  : "Will it rain in NYC tomorrow?" → YES/NO
      - Bracket : "Highest temp in Seoul on March 25?" → 11 sub-markets
    """

    def __init__(self, noaa_collector, polymarket_collector):
        self.weather    = noaa_collector
        self.polymarket = polymarket_collector

    # ── Main entry point ───────────────────────────────────────────────────────

    def find_opportunities(self, location: str = None) -> List[Dict]:
        """
        Scan semua weather markets dan cari peluang trading.
        Returns list of signals sorted by edge descending.
        """
        signals = []

        try:
            markets = self.polymarket.search_weather_markets(location)
            if not markets:
                logger.info("Tidak ada weather market ditemukan")
                return []

            logger.info(f"Menganalisa {len(markets)} market...")

            for market in markets:
                market_type = market.get("type", "binary")
                if market_type == "bracket":
                    result = self._analyze_bracket(market)
                    if result:
                        signals.extend(result)
                else:
                    result = self._analyze_binary(market)
                    if result:
                        signals.append(result)

            signals.sort(key=lambda x: x["edge"], reverse=True)
            logger.info(f"✅ Ditemukan {len(signals)} signal")
            return signals

        except Exception as e:
            logger.error(f"Error find_opportunities: {e}")
            return []

    # ── Binary market ──────────────────────────────────────────────────────────

    def _analyze_binary(self, market: Dict) -> Optional[Dict]:
        try:
            question    = market.get("question", "")
            location    = self.polymarket.extract_location_from_question(question)
            target_date = self.polymarket.extract_date_from_question(question)

            if not target_date and market.get("end_date"):
                target_date = market["end_date"].strftime("%Y-%m-%d")
            if not target_date or not location:
                return None
            if not self._passes_market_filter(market):
                return None

            q_lower  = question.lower()
            is_rain  = any(w in q_lower for w in ["rain", "precipitation", "shower"])
            is_temp  = any(w in q_lower for w in ["temperature", "degrees", "celsius", "fahrenheit"])
            is_snow  = any(w in q_lower for w in ["snow", "blizzard"])

            if not (is_rain or is_temp or is_snow):
                return None

            consensus = self.weather.get_consensus(location, target_date)
            if not consensus:
                return None

            if is_rain:
                weather_prob = (consensus["avg_rain_prob"] or 0) / 100
                signal_type  = "weather_rain"
            elif is_temp:
                weather_prob = self._estimate_temp_probability(question, consensus)
                signal_type  = "weather_temperature"
            else:
                weather_prob = (consensus["avg_rain_prob"] or 0) / 100
                signal_type  = "weather_snow"

            if weather_prob is None:
                return None

            return self._build_signal(
                market       = market,
                weather_prob = weather_prob,
                consensus    = consensus,
                target_date  = target_date,
                signal_type  = signal_type,
                location     = location,
            )

        except Exception as e:
            logger.error(f"Error _analyze_binary {market.get('id')}: {e}")
            return None

    # ── Bracket market ─────────────────────────────────────────────────────────

    def _analyze_bracket(self, event: Dict) -> List[Dict]:
        signals = []
        try:
            title       = event.get("title", "")
            target_date = self.polymarket.extract_date_from_question(title)
            location    = self.polymarket.extract_location_from_question(title)

            if not target_date and event.get("end_date"):
                target_date = event["end_date"].strftime("%Y-%m-%d")
            if not target_date or not location:
                return []

            consensus = self.weather.get_consensus(location, target_date)
            if not consensus:
                return []

            avg_temp    = consensus.get("avg_temp_high")
            temp_spread = consensus.get("temp_spread", 0)
            if avg_temp is None:
                return []

            logger.info(
                f"Bracket: {title} | forecast={avg_temp}°C ±{temp_spread} "
                f"| confidence={consensus['confidence']}%"
            )

            # Cari bracket yang paling cocok dengan forecast (predicted winner)
            best_bracket_id = self._find_best_bracket(event, avg_temp)

            for bracket in event.get("brackets", []):
                if not self._passes_market_filter(bracket):
                    continue

                weather_prob = self._bracket_probability(bracket, avg_temp, temp_spread)
                if weather_prob is None:
                    continue

                is_predicted_winner = (bracket.get("id") == best_bracket_id)

                # Untuk predicted winner → paksa direction YES jika confidence tinggi
                # Ini lebih profitable dari NO flooding (payout bisa 100x vs 2x)
                if is_predicted_winner and consensus.get("confidence", 0) >= 70:
                    signal = self._build_signal(
                        market       = bracket,
                        weather_prob = weather_prob,
                        consensus    = consensus,
                        target_date  = target_date,
                        signal_type  = "weather_temperature_bracket",
                        location     = location,
                        extra        = {
                            "bracket_label":     bracket.get("group_title", ""),
                            "event_title":       title,
                            "event_url":         event.get("url", ""),
                            "forecast_temp":     avg_temp,
                            "resolution_source": event.get("resolution_source", ""),
                            "is_predicted_winner": True,
                        }
                    )
                    if signal:
                        # Override direction ke YES untuk predicted winner
                        signal["direction"] = "YES"
                        signal["current_price"] = bracket.get("yes_price", 0.5)
                        signals.append(signal)
                else:
                    signal = self._build_signal(
                        market       = bracket,
                        weather_prob = weather_prob,
                        consensus    = consensus,
                        target_date  = target_date,
                        signal_type  = "weather_temperature_bracket",
                        location     = location,
                        extra        = {
                            "bracket_label":     bracket.get("group_title", ""),
                            "event_title":       title,
                            "event_url":         event.get("url", ""),
                            "forecast_temp":     avg_temp,
                            "resolution_source": event.get("resolution_source", ""),
                            "is_predicted_winner": False,
                        }
                    )
                    if signal:
                        signals.append(signal)

        except Exception as e:
            logger.error(f"Error _analyze_bracket {event.get('title')}: {e}")

        return signals

    def _find_best_bracket(self, event: Dict, forecast_temp: float) -> Optional[str]:
        """
        Cari bracket_id yang paling cocok dengan forecast temperature.
        Returns market_id dari bracket winner atau None.
        """
        import re
        best_id   = None
        best_diff = float("inf")

        for bracket in event.get("brackets", []):
            label = (bracket.get("group_title") or bracket.get("question", "")).lower()
            # Extract suhu dari label, misal "17°C", "17-18°C", "52°F"
            nums = re.findall(r"[\d.]+", label)
            if not nums:
                continue
            try:
                temp = float(nums[0])
                # Convert Fahrenheit jika perlu
                if "f" in label or "°f" in label:
                    temp = (temp - 32) * 5 / 9
                diff = abs(temp - forecast_temp)
                if diff < best_diff:
                    best_diff = diff
                    best_id   = bracket.get("id")
            except ValueError:
                continue

        return best_id

    # ── Probability helpers ────────────────────────────────────────────────────

    def _bracket_probability(
        self, bracket: Dict, forecast_temp: float, temp_spread: float
    ) -> Optional[float]:
        import math

        label   = bracket.get("group_title", "").lower()
        # FIX: pakai TEMP_STD_DEV minimum (2.5), bukan temp_spread yang bisa kecil
        std_dev = max(temp_spread, self.TEMP_STD_DEV)

        def norm_cdf(x):
            return 0.5 * (1 + math.erf(x / (std_dev * math.sqrt(2))))

        try:
            nums = re.findall(r"[\d.]+", label)
            if not nums:
                return None
            threshold = float(nums[0])

            if "or below" in label or "≤" in label:
                prob = norm_cdf(threshold + 0.5 - forecast_temp)
            elif "or higher" in label or "≥" in label or "above" in label:
                prob = 1 - norm_cdf(threshold - 0.5 - forecast_temp)
            else:
                prob = (
                    norm_cdf(threshold + 0.5 - forecast_temp) -
                    norm_cdf(threshold - 0.5 - forecast_temp)
                )
            return round(max(0.001, min(0.999, prob)), 4)
        except (ValueError, IndexError):
            return None

    # Std dev untuk kalkulasi probabilitas suhu.
    # 2.5°C lebih realistis dari 1.5°C:
    # - diff 0.2°C: std 1.5 → 99.7%, std 2.5 → 15.8%
    # - diff 1.0°C: std 1.5 → 92.3%, std 2.5 → 14.6%
    TEMP_STD_DEV = 2.5

    def _norm_cdf(self, x: float) -> float:
        import math
        return 0.5 * (1 + math.erf(x / (self.TEMP_STD_DEV * math.sqrt(2))))

    def _estimate_temp_probability(self, question: str, consensus: Dict) -> Optional[float]:
        """
        Hitung probabilitas untuk binary temperature market.
        Formula bracket dari test_analysis.py v4 (tested, lebih realistis).

        Pattern yang didukung:
          - "be 28°C on"         → bracket [27.5, 28.5]
          - "28°C or higher"     → CDF >= threshold
          - "28°C or below"      → CDF <= threshold
          - "between 27-28°C"    → bracket [27, 28]
          - Fahrenheit (semua pattern di atas)
        """
        avg_temp = consensus.get("avg_temp_high")
        if avg_temp is None:
            return None

        q = question

        def f2c(f): return (f - 32) * 5 / 9

        # ── Celsius patterns ──────────────────────────────────────────────────

        # Exact °C: "be 28°C on"  → bracket [27.5, 28.5]
        m = re.search(r"be\s+([\d.]+)°?C\s+on", q, re.IGNORECASE)
        if m:
            t = float(m.group(1))
            return round(self._norm_cdf(t + 0.5 - avg_temp) - self._norm_cdf(t - 0.5 - avg_temp), 3)

        # >= threshold °C
        m = re.search(r"([\d.]+)°?C or higher", q, re.IGNORECASE)
        if m:
            return round(1 - self._norm_cdf(float(m.group(1)) - avg_temp), 3)

        # <= threshold °C
        m = re.search(r"([\d.]+)°?C or below", q, re.IGNORECASE)
        if m:
            return round(self._norm_cdf(float(m.group(1)) - avg_temp), 3)

        # Between X-Y °C
        m = re.search(r"between\s+([\d.]+)[-–]([\d.]+)°?C", q, re.IGNORECASE)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            return round(self._norm_cdf(hi + 0.5 - avg_temp) - self._norm_cdf(lo - 0.5 - avg_temp), 3)

        # ── Fahrenheit patterns ───────────────────────────────────────────────

        # Exact °F: "be 82°F on"  → bracket [81.5, 82.5] → convert ke °C
        m = re.search(r"be\s+([\d.]+)°?F\s+on", q, re.IGNORECASE)
        if m:
            t = f2c(float(m.group(1)))
            return round(self._norm_cdf(t + 0.5 - avg_temp) - self._norm_cdf(t - 0.5 - avg_temp), 3)

        # >= threshold °F
        m = re.search(r"([\d.]+)°?F or higher", q, re.IGNORECASE)
        if m:
            t = f2c(float(m.group(1)))
            return round(1 - self._norm_cdf(t - avg_temp), 3)

        # <= threshold °F
        m = re.search(r"([\d.]+)°?F or below", q, re.IGNORECASE)
        if m:
            t = f2c(float(m.group(1)))
            return round(self._norm_cdf(t - avg_temp), 3)

        # Between X-Y °F
        m = re.search(r"between\s+([\d.]+)[-–]([\d.]+)°?F", q, re.IGNORECASE)
        if m:
            lo = f2c(float(m.group(1)))
            hi = f2c(float(m.group(2)))
            return round(self._norm_cdf(hi + 0.5 - avg_temp) - self._norm_cdf(lo - 0.5 - avg_temp), 3)

        # Fallback: exceed/above/below dari q_lower
        q_lower = q.lower()
        match = re.search(r"([\d.]+)\s*[°]?\s*(c|f|celsius|fahrenheit)", q_lower)
        if match:
            threshold = float(match.group(1))
            if match.group(2) in ("f", "fahrenheit"):
                threshold = f2c(threshold)
            if any(w in q_lower for w in ["exceed", "above", "over", "more than"]):
                return round(1 - self._norm_cdf(threshold - avg_temp), 3)
            elif any(w in q_lower for w in ["below", "under", "less than"]):
                return round(self._norm_cdf(threshold - avg_temp), 3)

        return None

    # ── Market filter ──────────────────────────────────────────────────────────

    def _passes_market_filter(self, market: Dict) -> bool:
        min_vol   = config.get("min_market_volume",    float)
        min_liq   = config.get("min_market_liquidity", float)
        min_hours = config.get("min_time_left_hours",  float)
        max_hours = config.get("max_time_left_hours",  float)

        if market.get("volume", 0) < min_vol:
            return False
        if market.get("liquidity", 0) < min_liq:
            return False
        if not market.get("active", True):
            return False
        if not market.get("accepting_orders", True):
            return False

        # FIX: filter harga ekstrem — near-certain outcome, EV tidak realistis
        # Market price 0.1% = trader lain sudah sangat yakin, signal tidak valid
        yes_price = market.get("yes_price", 0.5)
        no_price  = market.get("no_price", 0.5)
        if yes_price < 0.02 or yes_price > 0.98:
            return False
        if no_price < 0.02 or no_price > 0.98:
            return False

        end_date = market.get("end_date")
        if end_date:
            now = datetime.now(timezone.utc)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            hours_left = (end_date - now).total_seconds() / 3600
            if hours_left < min_hours or hours_left > max_hours:
                return False

        return True

    # ── Signal builder ─────────────────────────────────────────────────────────

    def _build_signal(
        self,
        market:       Dict,
        weather_prob: float,
        consensus:    Dict,
        target_date:  str,
        signal_type:  str,
        location:     str,
        extra:        Dict = None,
    ) -> Optional[Dict]:
        """
        Bangun signal dict.
        Field names sesuai kolom tabel signals:
          noaa_probability   = weather forecast prob (%)
          market_probability = YES price di market (%)
          fair_value         = harga wajar menurut kita
        """
        min_edge       = config.get("min_edge_pct",       float)
        min_confidence = config.get("min_confidence_pct", float)

        yes_price = market.get("yes_price", 0.5)
        no_price  = market.get("no_price",  0.5)

        if yes_price <= 0 or yes_price >= 1:
            return None

        market_prob = yes_price
        edge        = (weather_prob - market_prob) * 100

        if edge > 0:
            direction     = "YES"
            current_price = yes_price
            payout_mult   = 1 / yes_price
            ev            = (weather_prob * payout_mult - 1) * 100
        else:
            direction     = "NO"
            current_price = no_price
            payout_mult   = 1 / no_price if no_price > 0 else 2
            ev            = ((1 - weather_prob) * payout_mult - 1) * 100

        abs_edge = abs(edge)

        if abs_edge < min_edge:
            return None

        confidence = self._calculate_confidence(abs_edge, consensus, market)

        if confidence < min_confidence:
            return None

        signal = {
            # ── Kolom tabel signals ───────────────────────────────────────────
            "market_id":          market.get("id", ""),
            "location":           location,
            "target_date":        target_date,
            "signal_type":        signal_type,
            "direction":          direction,
            "noaa_probability":   round(weather_prob * 100, 1),   # ← nama kolom DB
            "market_probability": round(market_prob  * 100, 1),   # ← nama kolom DB
            "edge":               round(abs_edge, 1),
            "confidence":         confidence,
            "fair_value":         round(weather_prob, 4),          # ← nama kolom DB
            "expected_value":     round(ev, 1),
            "recommended_bet":    0,   # diisi oleh risk_manager
            "reasoning":          self._generate_reasoning(
                                      weather_prob, market_prob, consensus,
                                      direction, signal_type
                                  ),
            # ── Extra fields untuk tampilan / Telegram ─────────────────────
            "market_question":    market.get("question", ""),
            "market_url":         market.get("url", ""),
            "market_volume":      market.get("volume", 0),
            "market_liquidity":   market.get("liquidity", 0),
            "market_end_date":    market.get("end_date"),
            "current_price":      current_price,
            "payout_multiplier":  round(payout_mult, 2),
            "edge_direction":     "YES underpriced" if edge > 0 else "NO underpriced",
            "sources_used":       consensus.get("sources_used", []),
            "source_count":       consensus.get("source_count", 1),
            "temp_spread":        consensus.get("temp_spread", 0),
            "created_at":         datetime.now(timezone.utc),
        }

        if extra:
            signal.update(extra)

        return signal

    # ── Confidence ────────────────────────────────────────────────────────────

    def _calculate_confidence(self, edge: float, consensus: Dict, market: Dict) -> float:
        score = 0

        if edge >= 30:   score += 25
        elif edge >= 20: score += 18
        elif edge >= 15: score += 12
        else:            score += 6

        source_count = consensus.get("source_count", 1)
        temp_spread  = consensus.get("temp_spread", 99)
        if source_count >= 2 and temp_spread < 2.0:   score += 25
        elif source_count >= 2 and temp_spread < 4.0: score += 15
        elif source_count >= 2:                        score += 8

        avg_rain = consensus.get("avg_rain_prob")
        if avg_rain is not None:
            if avg_rain > 80 or avg_rain < 20:   score += 20
            elif avg_rain > 70 or avg_rain < 30: score += 12
            elif avg_rain > 60 or avg_rain < 40: score += 6

        liquidity = market.get("liquidity", 0)
        if liquidity > 10000:   score += 15
        elif liquidity > 5000:  score += 10
        elif liquidity > 1000:  score += 5

        end_date = market.get("end_date")
        if end_date:
            now = datetime.now(timezone.utc)
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            hours_left = (end_date - now).total_seconds() / 3600
            if hours_left <= 6:    score += 15
            elif hours_left <= 24: score += 10
            elif hours_left <= 48: score += 5

        return min(round(score, 1), 95)

    # ── Reasoning ─────────────────────────────────────────────────────────────

    def _generate_reasoning(
        self, weather_prob, market_prob, consensus, direction, signal_type
    ) -> str:
        w_pct   = weather_prob * 100
        m_pct   = market_prob  * 100
        edge    = abs(w_pct - m_pct)
        sources = ", ".join(consensus.get("sources_used", ["Unknown"]))

        if "bracket" in signal_type:
            temp   = consensus.get("avg_temp_high", "?")
            spread = consensus.get("temp_spread", 0)
            return (
                f"Forecast suhu {temp}°C (±{spread}°C) dari {sources}. "
                f"Model: {w_pct:.1f}% vs market: {m_pct:.1f}%. "
                f"Edge {edge:.1f}% → {direction}."
            )

        suffix = "Market underpricing." if direction == "YES" else "Market overpricing."
        return (
            f"{sources} forecast {w_pct:.0f}% vs market {m_pct:.0f}%. "
            f"Edge {edge:.0f}% → {direction}. {suffix}"
        )