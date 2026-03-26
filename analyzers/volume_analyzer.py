"""
volume_analyzer.py
===================
Strategi baru: Volume Distribution Analysis.

Menggantikan forecast-based analysis yang error ±3-5°C.

Logic:
  1. 4 jam sebelum market closing → ambil volume tiap bracket
  2. Bracket dengan volume terbesar = market consensus
  3. Hitung YES price bracket tersebut
  4. Jika YES masih underpriced (ada edge) → generate signal
  5. Kirim alert Telegram dengan tombol EXECUTE/SKIP

Kenapa ini lebih akurat dari forecast:
  - Ribuan trader dengan berbagai sumber sudah price-in info
  - Volume distribution mencerminkan collective intelligence
  - Tidak bergantung pada API forecast yang error ±3-5°C

Data dari Gamma API (terbukti bekerja):
  - event.startDate, event.endDate
  - market.outcomePrices
  - market.volumeNum
  - market.groupItemTitle
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
import urllib3
urllib3.disable_warnings()

import config

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"


def _safe_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class VolumeAnalyzer:
    """
    Analisa distribusi volume bracket market untuk generate trading signal.
    Dijalankan 4 jam sebelum market closing.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({"User-Agent": "PolymarketWeatherBot/2.0"})
        self._alerted: set = set()   # event_id yang sudah dikirim alert hari ini

    # ── Main entry ────────────────────────────────────────────────────────────

    def scan_pre_closing(self) -> List[Dict]:
        """
        Scan semua weather bracket markets yang akan closing dalam pre_closing_hours.
        Returns list of signals.
        """
        pre_closing_h    = config.PRE_CLOSING_HOURS()
        min_vol          = config.MIN_VOLUME_SIGNAL()
        edge_threshold   = config.VOLUME_EDGE_THRESHOLD()
        signals          = []

        logger.info(f"📊 Pre-closing scan — window {pre_closing_h}h sebelum closing")

        try:
            events = self._fetch_closing_events(pre_closing_h)
            logger.info(f"   {len(events)} event mendekati closing")

            for event in events:
                event_id = event.get("id", "")
                if event_id in self._alerted:
                    continue

                signal = self._analyze_event(event, min_vol, edge_threshold)
                if signal:
                    signals.append(signal)
                    self._alerted.add(event_id)
                    logger.info(
                        f"✅ Signal: {signal['location']} "
                        f"bracket={signal['bracket_label']} "
                        f"YES={signal['yes_price']*100:.1f}% "
                        f"edge={signal['edge']:.0f}%"
                    )

        except Exception as e:
            logger.error(f"scan_pre_closing error: {e}")

        return signals

    def reset_daily(self):
        """Reset alerted set setiap hari."""
        self._alerted.clear()
        logger.info("🔄 VolumeAnalyzer daily reset")

    # ── Fetch events ──────────────────────────────────────────────────────────

    def _fetch_closing_events(self, pre_closing_h: float) -> List[Dict]:
        """
        Ambil weather bracket events yang closing dalam pre_closing_h jam ke depan.
        """
        from datetime import timedelta
        now    = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=pre_closing_h)
        events = []

        WEATHER_RE = re.compile(
            r"highest temp|lowest temp|temperature|°[CF]",
            re.IGNORECASE
        )

        try:
            # Ambil events via /events endpoint dengan slug pattern
            for series_slug in [
                "seoul-daily-weather", "london-daily-weather",
                "wellington-daily-weather", "tokyo-daily-weather",
                "shanghai-daily-weather", "new-york-daily-weather",
                "chicago-daily-weather", "los-angeles-daily-weather",
                "paris-daily-weather", "toronto-daily-weather",
                "sydney-daily-weather", "miami-daily-weather",
                "houston-daily-weather", "dallas-daily-weather",
                "denver-daily-weather", "seattle-daily-weather",
                "buenos-aires-daily-weather", "beijing-daily-weather",
                "singapore-daily-weather", "istanbul-daily-weather",
            ]:
                try:
                    r = self.session.get(f"{GAMMA_API}/events", params={
                        "series_slug": series_slug,
                        "active": "true", "closed": "false",
                        "limit": 5,
                    }, timeout=10)
                    batch = r.json() if isinstance(r.json(), list) else []
                    for ev in batch:
                        end_raw = ev.get("endDate")
                        if not end_raw:
                            continue
                        try:
                            end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                            if now < end <= cutoff:
                                ev["_hours_left"] = round((end - now).total_seconds() / 3600, 1)
                                events.append(ev)
                        except Exception:
                            continue
                except Exception:
                    continue

            # Fallback: ambil events yang closing soon via generic query
            if not events:
                r = self.session.get(f"{GAMMA_API}/events", params={
                    "active": "true", "closed": "false",
                    "limit": 100, "order": "endDate", "ascending": "true",
                }, timeout=15)
                batch = r.json() if isinstance(r.json(), list) else []
                for ev in batch:
                    title = (ev.get("title") or "").lower()
                    if not WEATHER_RE.search(title):
                        continue
                    end_raw = ev.get("endDate")
                    if not end_raw:
                        continue
                    try:
                        end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                        if now < end <= cutoff:
                            ev["_hours_left"] = round((end - now).total_seconds() / 3600, 1)
                            events.append(ev)
                    except Exception:
                        continue

        except Exception as e:
            logger.error(f"_fetch_closing_events error: {e}")

        return events

    # ── Analyze event ─────────────────────────────────────────────────────────

    def _analyze_event(self, event: Dict, min_vol: float,
                       edge_threshold: float) -> Optional[Dict]:
        """
        Analisa satu event bracket:
        1. Ambil volume per bracket
        2. Cari bracket consensus (volume tertinggi)
        3. Hitung edge
        4. Return signal jika ada edge
        """
        markets    = event.get("markets", [])
        title      = event.get("title", "")
        end_date   = event.get("endDate", "")
        hours_left = event.get("_hours_left", 0)

        if len(markets) < 3:
            return None

        # Hitung volume + YES price per bracket
        bracket_data = []
        total_volume = 0.0

        for m in markets:
            prices = m.get("outcomePrices", "[]")
            if isinstance(prices, str):
                try: prices = json.loads(prices)
                except: prices = []

            yes_p  = _safe_float(prices[0]) if prices else 0
            no_p   = _safe_float(prices[1]) if len(prices) > 1 else 0
            vol    = _safe_float(m.get("volumeNum") or m.get("volume", 0))
            label  = m.get("groupItemTitle") or m.get("question", "")

            # Skip bracket yang sudah di-flood atau belum ada activity
            if yes_p < 0.01 or yes_p > 0.99:
                continue
            if vol < 1:
                continue

            bracket_data.append({
                "market_id":   m.get("id", ""),
                "label":       label,
                "yes_price":   yes_p,
                "no_price":    no_p,
                "volume":      vol,
                "question":    m.get("question", ""),
                "token_ids":   m.get("clobTokenIds", "[]"),
                "liquidity":   _safe_float(m.get("liquidityNum") or m.get("liquidity", 0)),
                "end_date":    end_date,
            })
            total_volume += vol

        if not bracket_data or total_volume < min_vol:
            return None

        # Sort by volume descending
        bracket_data.sort(key=lambda x: x["volume"], reverse=True)

        # Bracket consensus = volume terbesar
        consensus = bracket_data[0]
        vol_share = consensus["volume"] / total_volume * 100  # % of total volume

        # Hitung edge: fair value dari volume distribution
        # Volume share = market's collective probability estimate
        fair_value = vol_share / 100
        yes_price  = consensus["yes_price"]
        edge       = (fair_value - yes_price) * 100

        logger.debug(
            f"   {title[:40]} | consensus={consensus['label']} "
            f"vol={vol_share:.0f}% fair={fair_value:.2f} yes={yes_price:.2f} edge={edge:.0f}%"
        )

        # Filter: edge harus cukup signifikan
        if abs(edge) < edge_threshold:
            return None

        # Extract location
        location = self._extract_location(title)

        # Build signal
        direction = "YES" if edge > 0 else "NO"

        # Parse token IDs
        token_ids = consensus.get("token_ids", "[]")
        if isinstance(token_ids, str):
            try: token_ids = json.loads(token_ids)
            except: token_ids = []
        asset_id = token_ids[0] if direction == "YES" and token_ids else (
                   token_ids[1] if len(token_ids) > 1 else None)

        return {
            # ── Kolom tabel signals ───────────────────────────────────────
            "market_id":          consensus["market_id"],
            "location":           location,
            "target_date":        end_date[:10] if end_date else "",
            "signal_type":        "volume_distribution",
            "direction":          direction,
            "noaa_probability":   round(fair_value * 100, 1),
            "market_probability": round(yes_price * 100, 1),
            "edge":               round(abs(edge), 1),
            "confidence":         self._calc_confidence(vol_share, len(bracket_data), hours_left),
            "fair_value":         round(fair_value, 4),
            "expected_value":     round((fair_value / yes_price - 1) * 100, 1) if yes_price > 0 else 0,
            "recommended_bet":    0,
            "reasoning":          (
                f"Volume distribution: {consensus['label']} mendapat "
                f"{vol_share:.0f}% dari total volume ${total_volume:,.0f}. "
                f"YES price {yes_price*100:.1f}% vs fair value {fair_value*100:.1f}%. "
                f"Edge {abs(edge):.0f}% → {direction}."
            ),
            # ── Extra untuk Telegram ──────────────────────────────────────
            "market_question":    consensus["question"],
            "market_url":         f"https://polymarket.com/event/{event.get('slug','')}",
            "market_volume":      total_volume,
            "market_liquidity":   consensus["liquidity"],
            "market_end_date":    end_date,
            "current_price":      yes_price if direction == "YES" else consensus["no_price"],
            "yes_price":          yes_price,
            "no_price":           consensus["no_price"],
            "asset_id":           asset_id,
            "bracket_label":      consensus["label"],
            "vol_share":          round(vol_share, 1),
            "total_volume":       round(total_volume, 2),
            "hours_left":         hours_left,
            "bracket_count":      len(bracket_data),
            "event_title":        title,
            "created_at":         datetime.now(timezone.utc),
        }

    # ── Confidence ────────────────────────────────────────────────────────────

    def _calc_confidence(self, vol_share: float, bracket_count: int,
                         hours_left: float) -> float:
        """
        Hitung confidence dari volume distribution signal.
        Semakin besar vol_share dan semakin dekat closing → semakin confident.
        """
        score = 0

        # Volume concentration
        if vol_share >= 50:   score += 35
        elif vol_share >= 35: score += 25
        elif vol_share >= 25: score += 15
        else:                 score += 5

        # Time to closing (semakin dekat → lebih akurat)
        if hours_left <= 1:   score += 35
        elif hours_left <= 2: score += 25
        elif hours_left <= 4: score += 15
        else:                 score += 5

        # Bracket count (lebih banyak bracket → lebih signifikan)
        if bracket_count >= 10: score += 20
        elif bracket_count >= 7: score += 15
        elif bracket_count >= 5: score += 10
        else:                    score += 5

        return min(round(score, 1), 95)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_location(self, title: str) -> str:
        """Extract city name dari event title."""
        m = re.search(r"(?:in|at)\s+([A-Z][a-zA-Z\s]+?)(?:\s+on|\s+for|\?|$)", title)
        return m.group(1).strip() if m else title[:20]