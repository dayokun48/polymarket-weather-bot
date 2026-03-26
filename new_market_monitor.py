"""
new_market_monitor.py
======================
Deteksi fresh bracket market dan auto-execute BUY NO semua bracket
sebelum trader lain flood NO @ 99.9¢.

Berdasarkan data JSON yang sudah dikonfirmasi:
  - Event Seoul Mar 29: startDate=2026-03-25T10:12 UTC (17:12 WIB)
  - Event Wellington Mar 29: startDate=2026-03-25T10:46 UTC (17:46 WIB)
  - Market buka sekitar 17:00-18:00 WIB setiap hari
  - createdAt tersedia di /events endpoint

Strategi:
  Market baru buka → semua bracket masih ~50¢
  Bot BUY NO semua bracket @ ~50¢ sebelum flood
  9/10 menang @ 2x → profit bersih ~80%
"""

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

import requests
import urllib3
urllib3.disable_warnings()

import config

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"

WEATHER_RE = re.compile(
    r"highest temp|lowest temp|temperature|°[CF]",
    re.IGNORECASE
)

KNOWN_SERIES = [
    "seoul-daily-weather", "london-daily-weather",
    "wellington-daily-weather", "tokyo-daily-weather",
    "shanghai-daily-weather", "new-york-daily-weather",
    "chicago-daily-weather", "los-angeles-daily-weather",
    "paris-daily-weather", "toronto-daily-weather",
    "miami-daily-weather", "houston-daily-weather",
    "dallas-daily-weather", "denver-daily-weather",
    "seattle-daily-weather", "buenos-aires-daily-weather",
    "beijing-daily-weather", "singapore-daily-weather",
]


def _safe_float(v, default=0.0) -> float:
    try: return float(v)
    except: return default


class FreshMarketMonitor:

    def __init__(self, weather_analyzer, trader, telegram_bot):
        self.analyzer = weather_analyzer
        self.trader   = trader
        self.telegram = telegram_bot
        self._alerted: Set[str] = set()

        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({"User-Agent": "PolymarketWeatherBot/2.0"})

    # ── Main entry ────────────────────────────────────────────────────────────

    def scan_fresh_markets(self) -> int:
        """Scan fresh bracket markets dan execute jika ada. Returns count."""
        window_minutes = config.FRESH_MARKET_WINDOW()
        auto_bet       = config.FRESH_MARKET_AUTO_BET()
        processed      = 0

        try:
            fresh = self._fetch_fresh_events(window_minutes)
            if not fresh:
                return 0

            logger.info(f"🆕 {len(fresh)} fresh bracket market ditemukan!")

            for event in fresh:
                event_id = event.get("id", "")
                if event_id in self._alerted:
                    continue

                if self._process_event(event, auto_bet):
                    self._alerted.add(event_id)
                    processed += 1

        except Exception as e:
            logger.error(f"scan_fresh_markets error: {e}")

        return processed

    # ── Fetch fresh events ────────────────────────────────────────────────────

    def _fetch_fresh_events(self, window_minutes: int) -> List[Dict]:
        """
        Fetch events yang dibuka dalam window_minutes terakhir.
        Pakai createdAt dari /events endpoint (terbukti ada dari JSON).
        """
        fresh  = []
        now    = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=window_minutes)

        # Method 1: Scan known series untuk event terbaru
        for series_slug in KNOWN_SERIES:
            try:
                r = self.session.get(f"{GAMMA_API}/events", params={
                    "series_slug": series_slug,
                    "active": "true", "closed": "false",
                    "limit": 3, "order": "startDate", "ascending": "false",
                }, timeout=10)
                events = r.json() if isinstance(r.json(), list) else []

                for ev in events:
                    ev_id = ev.get("id", "")
                    if ev_id in self._alerted:
                        continue

                    # Pakai startDate (terbukti ada dari JSON Seoul/Wellington)
                    start_raw = ev.get("startDate") or ev.get("createdAt")
                    if not start_raw:
                        continue

                    try:
                        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                        if start < cutoff:
                            continue
                        age_min = (now - start).total_seconds() / 60
                    except Exception:
                        continue

                    markets = ev.get("markets", [])
                    if len(markets) < 3:
                        continue

                    avg_yes = self._get_avg_yes_price(markets)
                    if 0.25 <= avg_yes <= 0.75:
                        ev["_age_minutes"]  = round(age_min, 1)
                        ev["_avg_yes_price"] = round(avg_yes, 3)
                        ev["_bracket_count"] = len(markets)
                        fresh.append(ev)
                        logger.info(
                            f"🆕 Fresh: {ev.get('title','')[:50]} "
                            f"| age={age_min:.1f}min | avg_yes={avg_yes:.2f}"
                        )

            except Exception as e:
                logger.debug(f"Series {series_slug} error: {e}")
                continue

        # Method 2: Fallback generic scan jika series tidak return
        if not fresh:
            try:
                r = self.session.get(f"{GAMMA_API}/events", params={
                    "active": "true", "closed": "false",
                    "limit": 100, "order": "startDate", "ascending": "false",
                }, timeout=15)
                events = r.json() if isinstance(r.json(), list) else []

                for ev in events:
                    title = (ev.get("title") or "").lower()
                    if not WEATHER_RE.search(title):
                        continue

                    ev_id = ev.get("id", "")
                    if ev_id in self._alerted:
                        continue

                    start_raw = ev.get("startDate") or ev.get("createdAt")
                    if not start_raw:
                        continue

                    try:
                        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                        if start < cutoff:
                            continue
                        age_min = (now - start).total_seconds() / 60
                    except Exception:
                        continue

                    markets = ev.get("markets", [])
                    if len(markets) < 3:
                        continue

                    avg_yes = self._get_avg_yes_price(markets)
                    if 0.25 <= avg_yes <= 0.75:
                        ev["_age_minutes"]   = round(age_min, 1)
                        ev["_avg_yes_price"] = round(avg_yes, 3)
                        ev["_bracket_count"] = len(markets)
                        fresh.append(ev)

            except Exception as e:
                logger.error(f"Generic scan error: {e}")

        return fresh

    # ── Process event ─────────────────────────────────────────────────────────

    def _process_event(self, event: Dict, auto_bet: float) -> bool:
        """BUY NO semua bracket (kecuali predicted winner) untuk fresh event."""
        title    = event.get("title", "")
        markets  = event.get("markets", [])
        event_id = event.get("id", "")

        try:
            # Predict bracket winner via weather forecast (sebagai hint)
            winner_id = self._predict_winner_id(event)
            logger.info(f"🎯 Winner hint market_id={winner_id}")

            executed_no  = []
            executed_yes = []
            total_bet    = 0.0
            simulation   = not self.trader.is_ready()

            for m in markets:
                label  = m.get("groupItemTitle") or m.get("question", "")
                prices = m.get("outcomePrices", "[]")
                if isinstance(prices, str):
                    try: prices = json.loads(prices)
                    except: prices = []

                yes_p = _safe_float(prices[0]) if prices else 0.5
                no_p  = _safe_float(prices[1]) if len(prices) > 1 else 0.5

                # Skip bracket yang sudah di-flood
                if yes_p < 0.20 or no_p > 0.80:
                    continue

                is_winner = (m.get("id") == winner_id)

                if is_winner:
                    # BUY YES predicted winner @ 2x bet
                    signal = self._build_signal(m, "YES", yes_p, event)
                    result = self.trader.execute_trade(signal, None, auto_bet * 2)
                    if result:
                        executed_yes.append(label)
                        total_bet += auto_bet * 2
                else:
                    # BUY NO semua bracket lain
                    signal = self._build_signal(m, "NO", no_p, event)
                    result = self.trader.execute_trade(signal, None, auto_bet)
                    if result:
                        executed_no.append(label)
                        total_bet += auto_bet

            if not executed_no and not executed_yes:
                logger.warning(f"Tidak ada bracket fresh untuk {title[:50]}")
                return False

            self._send_alert(event, executed_no, executed_yes, total_bet, simulation)
            return True

        except Exception as e:
            logger.error(f"_process_event error: {e}")
            return False

    # ── Predict winner ────────────────────────────────────────────────────────

    def _predict_winner_id(self, event: Dict) -> Optional[str]:
        """
        Cari bracket yang paling mungkin menang.
        Prioritas: volume terbesar (market intelligence > forecast).
        """
        markets = event.get("markets", [])
        if not markets:
            return None

        # Kalau volume sudah ada → pakai volume terbesar
        best_id  = None
        best_vol = 0.0
        for m in markets:
            vol = _safe_float(m.get("volumeNum") or m.get("volume", 0))
            if vol > best_vol:
                best_vol = vol
                best_id  = m.get("id")

        if best_id and best_vol > 10:
            return best_id

        # Fallback: tengah bracket list (heuristik)
        mid = len(markets) // 2
        return markets[mid].get("id")

    # ── Build signal ──────────────────────────────────────────────────────────

    def _build_signal(self, market: Dict, direction: str,
                      trade_price: float, event: Dict) -> Dict:
        token_ids = market.get("clobTokenIds", "[]")
        if isinstance(token_ids, str):
            try: token_ids = json.loads(token_ids)
            except: token_ids = []

        asset_id = token_ids[0] if direction == "YES" else (
                   token_ids[1] if len(token_ids) > 1 else None)

        return {
            "market_id":       market.get("id", ""),
            "market_question": market.get("question", market.get("groupItemTitle", "")),
            "market_url":      f"https://polymarket.com/event/{event.get('slug','')}",
            "direction":       direction,
            "current_price":   trade_price,
            "yes_price":       trade_price if direction == "YES" else 0,
            "no_price":        trade_price if direction == "NO"  else 0,
            "asset_id":        asset_id,
            "signal_type":     "fresh_market_bracket",
            "edge":            abs(trade_price - 0.5) * 100,
            "confidence":      70,
            "noaa_probability": 50,
            "market_probability": trade_price * 100,
            "reasoning": f"Fresh market — {direction} @ {trade_price:.2f} sebelum NO flood",
        }

    # ── Alert ─────────────────────────────────────────────────────────────────

    def _send_alert(self, event, executed_no, executed_yes,
                    total_bet, simulation):
        title      = event.get("title", "")
        age        = event.get("_age_minutes", "?")
        brackets   = event.get("_bracket_count", 0)
        mode_label = "🟡 SIMULATED" if simulation else "⚡ EXECUTED"

        msg = (
            f"🆕 {mode_label} FRESH MARKET\n\n"
            f"📊 {title[:60]}\n"
            f"⏱️ Age: {age} menit | {brackets} brackets\n\n"
            f"✅ BUY YES: {', '.join(executed_yes) or '-'}\n"
            f"❌ BUY NO : {len(executed_no)} brackets\n"
            f"💰 Total bet: ${total_bet:.2f}\n\n"
            f"📈 Est. profit jika 1 menang:\n"
            f"   ({len(executed_no)} × $1 × 2x) - $1 ≈ ${(len(executed_no)-1)*1:.0f}"
        )

        try:
            import requests as req
            req.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Fresh alert error: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_avg_yes_price(self, markets: List[Dict]) -> float:
        yes_prices = []
        for m in markets:
            prices = m.get("outcomePrices", "[]")
            if isinstance(prices, str):
                try: prices = json.loads(prices)
                except: prices = []
            outcomes = m.get("outcomes", "[]")
            if isinstance(outcomes, str):
                try: outcomes = json.loads(outcomes)
                except: outcomes = []
            price_map = {str(o).lower(): _safe_float(p) for o, p in zip(outcomes, prices)}
            yes_p = price_map.get("yes", _safe_float(prices[0]) if prices else 0)
            if yes_p > 0:
                yes_prices.append(yes_p)
        return sum(yes_prices) / len(yes_prices) if yes_prices else 0