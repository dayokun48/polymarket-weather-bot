"""
new_market_monitor.py
======================
FreshMarketMonitor v3 — Slug-based detection.

Dari hasil testing:
  - Semua weather markets dibuka jam 10:xx UTC (17:xx WIB)
  - Slug pattern: highest-temperature-in-{city}-on-{month}-{day}-{year}
  - Market dibuat H-4 dari event date (Mar 30 dibuat Mar 26 jam 17:xx)
  - avg_yes ~50¢ saat fresh, turun ke ~10¢ setelah di-flood (~30 menit)

Strategy:
  Setiap 5 menit (terutama 16:50-17:30 WIB):
    1. Generate slug untuk H+3, H+4, H+5 dari sekarang
    2. Hit Gamma API via /events?slug= untuk 30 kota
    3. Kalau ada yang startDate < fresh_window_minutes lalu
       DAN avg_yes 25-75% → EXECUTE BUY NO semua bracket
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

import requests
import urllib3
urllib3.disable_warnings()

import config

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"

# 30 kota yang terbukti punya daily weather market
CITIES = [
    "seoul", "london", "wellington", "tokyo", "shanghai",
    "new-york", "chicago", "los-angeles", "paris", "toronto",
    "miami", "houston", "dallas", "denver", "seattle",
    "buenos-aires", "beijing", "singapore", "istanbul", "taipei",
    "ankara", "lucknow", "milan", "madrid", "munich",
    "san-francisco", "atlanta", "wuhan", "shenzhen", "chengdu",
]


def _safe_float(v, default=0.0) -> float:
    try: return float(v)
    except: return default


def _generate_slug(city: str, target_date) -> str:
    """Generate slug: highest-temperature-in-{city}-on-{month}-{day}-{year}"""
    month = target_date.strftime("%B").lower()
    day   = target_date.day
    year  = target_date.year
    return f"highest-temperature-in-{city}-on-{month}-{day}-{year}"


class FreshMarketMonitor:

    def __init__(self, weather_analyzer, trader, telegram_bot):
        self.analyzer = weather_analyzer
        self.trader   = trader
        self.telegram = telegram_bot
        self._alerted: Set[str] = set()   # event_id yang sudah diproses

        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({"User-Agent": "PolymarketWeatherBot/2.0"})

    # ── Main entry ────────────────────────────────────────────────────────────

    def scan_fresh_markets(self) -> int:
        """
        Scan fresh bracket markets via slug-based detection.
        Returns jumlah market yang berhasil diproses.
        """
        window_minutes = config.FRESH_MARKET_WINDOW()
        auto_bet       = config.FRESH_MARKET_AUTO_BET()
        processed      = 0
        now            = datetime.now(timezone.utc)

        # Cek untuk H+3 sampai H+5 (market dibuat ~H-4 dari event date)
        target_dates = [
            (now + timedelta(days=d)).date()
            for d in range(3, 6)
        ]

        fresh_events = []

        for target_date in target_dates:
            for city in CITIES:
                slug = _generate_slug(city, target_date)
                event = self._fetch_event_by_slug(slug)

                if not event:
                    continue

                event_id  = event.get("id", "")
                if event_id in self._alerted:
                    continue

                start_raw = event.get("startDate") or event.get("createdAt")
                if not start_raw:
                    continue

                try:
                    start   = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                    age_min = (now - start).total_seconds() / 60
                except Exception:
                    continue

                # Hanya proses jika masih dalam window fresh
                if age_min > window_minutes:
                    continue

                markets = event.get("markets", [])
                if len(markets) < 3:
                    continue

                avg_yes = self._get_avg_yes_price(markets)

                # Fresh: YES masih ~50¢ (25-75%)
                if not (0.25 <= avg_yes <= 0.75):
                    continue

                event["_age_minutes"]   = round(age_min, 1)
                event["_avg_yes_price"] = round(avg_yes, 3)
                event["_bracket_count"] = len(markets)
                fresh_events.append(event)

                logger.info(
                    f"🆕 Fresh: {event.get('title','')[:55]} "
                    f"| age={age_min:.1f}min | avg_yes={avg_yes:.2f} "
                    f"| brackets={len(markets)}"
                )

        if not fresh_events:
            return 0

        logger.info(f"🆕 {len(fresh_events)} fresh weather market ditemukan!")

        for event in fresh_events:
            event_id = event.get("id", "")
            if event_id in self._alerted:
                continue
            if self._process_event(event, auto_bet):
                self._alerted.add(event_id)
                processed += 1

        return processed

    # ── Fetch event by slug ───────────────────────────────────────────────────

    def _fetch_event_by_slug(self, slug: str) -> Optional[Dict]:
        """Fetch event dari Gamma API via slug. Returns None jika tidak ada."""
        try:
            r = self.session.get(
                f"{GAMMA_API}/events",
                params={"slug": slug},
                timeout=8,
            )
            data   = r.json()
            events = data if isinstance(data, list) else (
                     [data] if isinstance(data, dict) and data.get("id") else []
            )
            return events[0] if events else None
        except Exception as e:
            logger.debug(f"Slug {slug}: {e}")
            return None

    # ── Process event ─────────────────────────────────────────────────────────

    def _process_event(self, event: Dict, auto_bet: float) -> bool:
        """
        BUY NO semua bracket kecuali predicted winner.
        BUY YES untuk predicted winner @ 2x bet.
        """
        title   = event.get("title", "")
        markets = event.get("markets", [])

        try:
            winner_id    = self._predict_winner_id(event)
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

                # Skip yang sudah di-flood
                if yes_p < 0.20 or no_p > 0.80:
                    continue

                is_winner = (m.get("id") == winner_id)

                if is_winner:
                    signal = self._build_signal(m, "YES", yes_p, event)
                    result = self.trader.execute_trade(signal, None, auto_bet * 2)
                    if result:
                        executed_yes.append(label)
                        total_bet += auto_bet * 2
                else:
                    signal = self._build_signal(m, "NO", no_p, event)
                    result = self.trader.execute_trade(signal, None, auto_bet)
                    if result:
                        executed_no.append(label)
                        total_bet += auto_bet

            if not executed_no and not executed_yes:
                logger.warning(f"Tidak ada bracket yang bisa dieksekusi: {title[:50]}")
                return False

            self._send_alert(event, executed_no, executed_yes, total_bet, simulation)
            logger.info(
                f"✅ Processed: {title[:50]} | "
                f"NO={len(executed_no)} YES={len(executed_yes)} "
                f"total=${total_bet:.2f}"
            )
            return True

        except Exception as e:
            logger.error(f"_process_event error: {e}")
            return False

    # ── Predict winner ────────────────────────────────────────────────────────

    def _predict_winner_id(self, event: Dict) -> Optional[str]:
        """
        Predict bracket yang paling mungkin menang.
        Prioritas: bracket dengan volume terbesar.
        Fallback: bracket tengah.
        """
        markets  = event.get("markets", [])
        best_id  = None
        best_vol = 0.0

        for m in markets:
            vol = _safe_float(m.get("volumeNum") or m.get("volume", 0))
            if vol > best_vol:
                best_vol = vol
                best_id  = m.get("id")

        # Kalau belum ada volume (market baru) → ambil bracket tengah
        if not best_id or best_vol < 1:
            mid     = len(markets) // 2
            best_id = markets[mid].get("id") if markets else None

        return best_id

    # ── Build signal ──────────────────────────────────────────────────────────

    def _build_signal(self, market: Dict, direction: str,
                      trade_price: float, event: Dict) -> Dict:
        token_ids = market.get("clobTokenIds", "[]")
        if isinstance(token_ids, str):
            try: token_ids = json.loads(token_ids)
            except: token_ids = []

        # YES token = index 0, NO token = index 1
        asset_id = token_ids[0] if direction == "YES" else (
                   token_ids[1] if len(token_ids) > 1 else None)

        return {
            "market_id":          market.get("id", ""),
            "market_question":    market.get("question", market.get("groupItemTitle", "")),
            "market_url":         f"https://polymarket.com/event/{event.get('slug','')}",
            "direction":          direction,
            "current_price":      trade_price,
            "yes_price":          trade_price if direction == "YES" else 0,
            "no_price":           trade_price if direction == "NO" else 0,
            "asset_id":           asset_id,
            "signal_type":        "fresh_market_bracket",
            "edge":               round(abs(trade_price - 0.5) * 100, 1),
            "confidence":         70,
            "noaa_probability":   50,
            "market_probability": round(trade_price * 100, 1),
            "reasoning":          f"Fresh market — {direction} @ {trade_price:.2f} sebelum NO flood",
            "location":           event.get("title", "")[:30],
            "target_date":        event.get("eventDate", ""),
        }

    # ── Alert ─────────────────────────────────────────────────────────────────

    def _send_alert(self, event: Dict, executed_no: List, executed_yes: List,
                    total_bet: float, simulation: bool):
        title      = event.get("title", "")
        age        = event.get("_age_minutes", "?")
        brackets   = event.get("_bracket_count", 0)
        mode_label = "🟡 SIMULATED" if simulation else "⚡ EXECUTED"
        winner     = executed_yes[0] if executed_yes else "—"

        est_profit = (len(executed_no) - 1) * config.FRESH_MARKET_AUTO_BET()

        msg = (
            f"{mode_label} FRESH MARKET\n\n"
            f"📊 {title}\n"
            f"⏱️ Age: {age} menit | {brackets} brackets\n\n"
            f"✅ BUY YES: {winner}\n"
            f"❌ BUY NO : {len(executed_no)} brackets\n"
            f"💰 Total bet: ${total_bet:.2f}\n\n"
            f"📈 Est. profit jika 1 menang: ~${est_profit:.0f}"
        )

        try:
            import requests as req
            req.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id":    config.TELEGRAM_CHAT_ID,
                    "text":       msg,
                    "parse_mode": "HTML",
                },
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
            # Ambil YES price
            if outcomes and prices:
                price_map = {str(o).lower(): _safe_float(p)
                             for o, p in zip(outcomes, prices)}
                yes_p = price_map.get("yes", _safe_float(prices[0]) if prices else 0)
            else:
                yes_p = _safe_float(prices[0]) if prices else 0
            if yes_p > 0:
                yes_prices.append(yes_p)
        return sum(yes_prices) / len(yes_prices) if yes_prices else 0