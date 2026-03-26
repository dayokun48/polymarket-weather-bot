"""
new_market_monitor.py
======================
Deteksi fresh bracket market dan auto-execute BUY NO semua bracket
sebelum trader lain flood NO @ 99.9¢.

Strategi:
  Market baru buka → semua bracket masih ~50¢
  Bot detect dalam {fresh_market_window_minutes} menit pertama
  BUY NO semua bracket @ ~50¢ → payout 2x
  9 dari 10 bracket menang → profit bersih ~80%

Flow:
  1. Poll /markets setiap 60 detik
  2. Filter: age < fresh_market_window_minutes DAN semua YES ~50¢
  3. Ambil semua bracket dari event
  4. Predict bracket yang menang via weather forecast
  5. BUY NO semua bracket KECUALI yang diprediksi menang (skip YES bracket)
  6. Kirim alert Telegram dengan detail
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

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


class FreshMarketMonitor:
    """
    Monitor dan auto-execute fresh bracket markets.
    Dijalankan dari app.py sebagai bagian dari scan_for_opportunities.
    """

    def __init__(self, weather_analyzer, trader, telegram_bot):
        self.analyzer    = weather_analyzer
        self.trader      = trader
        self.telegram    = telegram_bot
        self._alerted: Set[str] = set()   # event_id yang sudah diproses

        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({"User-Agent": "PolymarketWeatherBot/2.0"})

    # ── Main entry ────────────────────────────────────────────────────────────

    def scan_fresh_markets(self) -> int:
        """
        Scan fresh bracket markets dan execute jika ada.
        Returns jumlah market yang diproses.
        """
        window_minutes = config.FRESH_MARKET_WINDOW()
        auto_bet       = config.FRESH_MARKET_AUTO_BET()
        processed      = 0

        try:
            fresh = self._fetch_fresh_bracket_markets(window_minutes)
            if not fresh:
                return 0

            logger.info(f"🆕 {len(fresh)} fresh bracket market ditemukan!")

            for event in fresh:
                event_id = event.get("id", "")
                if event_id in self._alerted:
                    continue

                result = self._process_fresh_event(event, auto_bet)
                if result:
                    self._alerted.add(event_id)
                    processed += 1

        except Exception as e:
            logger.error(f"scan_fresh_markets error: {e}")

        return processed

    # ── Fetch fresh markets ───────────────────────────────────────────────────

    def _fetch_fresh_bracket_markets(self, window_minutes: int) -> List[Dict]:
        """
        Ambil bracket markets yang dibuka dalam window_minutes terakhir.
        Cek /events DAN /markets untuk coverage lebih lengkap.
        Kriteria fresh:
          - age < window_minutes
          - bracket masih ~50¢ (avg YES antara 25-75¢)
          - ada minimal 3 bracket
        """
        fresh = []
        now    = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=window_minutes)
        seen   = set()

        # ── Source 1: /events ─────────────────────────────────────────────────
        try:
            r = self.session.get(f"{GAMMA_API}/events", params={
                "active": "true", "closed": "false",
                "limit":  100, "order": "startDate", "ascending": "false",
            }, timeout=15)
            events = r.json() if isinstance(r.json(), list) else []

            for event in events:
                title = (event.get("title") or "").lower()
                if not any(w in title for w in ["temperature", "highest temp", "°c", "°f"]):
                    continue
                event_id = event.get("id", "")
                if event_id in seen:
                    continue

                start_raw = event.get("startDate") or event.get("creationDate")
                if not start_raw:
                    continue
                try:
                    start     = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                    age_min   = (now - start).total_seconds() / 60
                    if start < cutoff:
                        continue
                    event["_age_minutes"]  = round(age_min, 1)
                    event["_source"]       = "events"
                except Exception:
                    continue

                markets = event.get("markets", [])
                if len(markets) < 3:
                    continue

                avg_yes = self._get_avg_yes_price(markets)
                if 0.25 <= avg_yes <= 0.75:
                    event["_avg_yes_price"] = round(avg_yes, 3)
                    event["_bracket_count"] = len(markets)
                    fresh.append(event)
                    seen.add(event_id)
                    logger.info(f"🆕 Fresh (events): {event.get('title','')[:50]} | age={age_min:.1f}min | avg_yes={avg_yes:.2f}")

        except Exception as e:
            logger.error(f"_fetch_fresh /events error: {e}")

        # ── Source 2: /markets (untuk market tanpa event parent) ──────────────
        try:
            r = self.session.get(f"{GAMMA_API}/markets", params={
                "active": "true", "closed": "false",
                "limit":  200, "order": "startDate", "ascending": "false",
            }, timeout=15)
            markets_list = r.json() if isinstance(r.json(), list) else []

            # Group by event/parent
            from collections import defaultdict
            groups: dict = defaultdict(list)
            for m in markets_list:
                title = (m.get("question") or "").lower()
                if not any(w in title for w in ["temperature", "highest temp", "°c", "°f"]):
                    continue
                # Group by event slug (ambil dari question tanpa suhu)
                import re
                base = re.sub(r"\d+[°]?[CcFf].*", "", m.get("question","")).strip()
                groups[base].append(m)

            for base_title, group_markets in groups.items():
                if len(group_markets) < 3:
                    continue

                # Cek age dari market pertama
                start_raw = group_markets[0].get("startDate") or group_markets[0].get("createdAt")
                if not start_raw:
                    continue
                try:
                    start   = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                    age_min = (now - start).total_seconds() / 60
                    if start < cutoff:
                        continue
                except Exception:
                    continue

                avg_yes  = self._get_avg_yes_price(group_markets)
                event_id = f"market_group_{base_title[:30]}"

                if 0.25 <= avg_yes <= 0.75 and event_id not in seen:
                    synthetic_event = {
                        "id":              event_id,
                        "title":           base_title[:60],
                        "markets":         group_markets,
                        "_age_minutes":    round(age_min, 1),
                        "_avg_yes_price":  round(avg_yes, 3),
                        "_bracket_count":  len(group_markets),
                        "_source":         "markets",
                    }
                    fresh.append(synthetic_event)
                    seen.add(event_id)
                    logger.info(f"🆕 Fresh (markets): {base_title[:50]} | age={age_min:.1f}min | avg_yes={avg_yes:.2f}")

        except Exception as e:
            logger.error(f"_fetch_fresh /markets error: {e}")

        return fresh

    def _get_avg_yes_price(self, markets: List[Dict]) -> float:
        """Hitung rata-rata YES price dari list bracket markets."""
        import json
        yes_prices = []
        for m in markets:
            outcomes = m.get("outcomes", [])
            prices   = m.get("outcomePrices", [])
            if isinstance(outcomes, str):
                try: outcomes = json.loads(outcomes)
                except: outcomes = []
            if isinstance(prices, str):
                try: prices = json.loads(prices)
                except: prices = []
            price_map = {str(o).lower(): _safe_float(p) for o, p in zip(outcomes, prices)}
            yes_p = price_map.get("yes", 0)
            if yes_p > 0:
                yes_prices.append(yes_p)
        return sum(yes_prices) / len(yes_prices) if yes_prices else 0

    # ── Process event ─────────────────────────────────────────────────────────

    def _process_fresh_event(self, event: Dict, auto_bet: float) -> bool:
        """
        Process satu fresh event:
        1. Predict bracket yang akan menang via weather analyzer
        2. BUY NO semua bracket KECUALI yang diprediksi menang
        3. BUY YES untuk bracket yang diprediksi menang
        4. Kirim alert Telegram
        """
        title    = event.get("title", "")
        markets  = event.get("markets", [])
        event_id = event.get("id", "")

        try:
            # Predict bracket yang menang
            winner_bracket = self._predict_winner(event)
            logger.info(
                f"🎯 Predicted winner: {winner_bracket.get('group_title','?') if winner_bracket else 'unknown'}"
            )

            executed_no  = []
            executed_yes = []
            total_bet    = 0.0
            simulation   = not self.trader.is_ready()

            for market in markets:
                import json
                bracket_label = market.get("group_title", market.get("question", ""))
                outcomes = market.get("outcomes", [])
                prices   = market.get("outcomePrices", [])
                if isinstance(outcomes, str):
                    try: outcomes = json.loads(outcomes)
                    except: outcomes = []
                if isinstance(prices, str):
                    try: prices = json.loads(prices)
                    except: prices = []

                price_map = {str(o).lower(): _safe_float(p) for o, p in zip(outcomes, prices)}
                yes_price = price_map.get("yes", 0.5)
                no_price  = price_map.get("no", 0.5)

                # Skip jika sudah di-flood (NO > 80¢ atau YES < 20¢)
                if yes_price < 0.20 or no_price > 0.80:
                    logger.debug(f"Skip {bracket_label} — sudah di-flood (yes={yes_price:.2f})")
                    continue

                is_winner = (winner_bracket and
                             market.get("id") == winner_bracket.get("id"))

                if is_winner:
                    # BUY YES untuk bracket yang diprediksi menang
                    signal = self._build_fresh_signal(market, "YES", yes_price, event)
                    result = self.trader.execute_trade(signal, None, auto_bet * 2)
                    if result:
                        executed_yes.append(bracket_label)
                        total_bet += auto_bet * 2
                else:
                    # BUY NO untuk semua bracket lain
                    signal = self._build_fresh_signal(market, "NO", no_price, event)
                    result = self.trader.execute_trade(signal, None, auto_bet)
                    if result:
                        executed_no.append(bracket_label)
                        total_bet += auto_bet

            if not executed_no and not executed_yes:
                logger.warning(f"Tidak ada bracket yang bisa dieksekusi untuk {title[:50]}")
                return False

            # Kirim alert Telegram
            self._send_fresh_alert(
                event        = event,
                executed_no  = executed_no,
                executed_yes = executed_yes,
                total_bet    = total_bet,
                winner       = winner_bracket,
                simulation   = simulation,
            )
            return True

        except Exception as e:
            logger.error(f"_process_fresh_event error: {e}")
            return False

    # ── Predict winner bracket ────────────────────────────────────────────────

    def _predict_winner(self, event: Dict) -> Optional[Dict]:
        """
        Predict bracket yang paling mungkin menang berdasarkan weather forecast.
        Returns bracket market dict atau None.
        """
        try:
            title    = event.get("title", "")
            location = self.analyzer.polymarket.extract_location_from_question(title)
            date_str = self.analyzer.polymarket.extract_date_from_question(title)

            if not location or not date_str:
                return None

            consensus = self.analyzer.weather.get_consensus(location, date_str)
            if not consensus or consensus.get("avg_temp_high") is None:
                return None

            forecast_temp = consensus["avg_temp_high"]
            markets       = event.get("markets", [])

            best_bracket = None
            best_prob    = 0.0

            for market in markets:
                q    = market.get("question", market.get("group_title", ""))
                prob = self.analyzer._estimate_temp_probability(
                    q, consensus
                )
                if prob and prob > best_prob:
                    best_prob    = prob
                    best_bracket = market

            logger.info(f"   Forecast: {forecast_temp}°C → best bracket prob={best_prob:.2f}")
            return best_bracket

        except Exception as e:
            logger.error(f"_predict_winner error: {e}")
            return None

    # ── Build signal ──────────────────────────────────────────────────────────

    def _build_fresh_signal(self, market: Dict, direction: str,
                             trade_price: float, event: Dict) -> Dict:
        """Build minimal signal dict untuk fresh market execution."""
        import json
        outcomes = market.get("outcomes", [])
        prices   = market.get("outcomePrices", [])
        if isinstance(outcomes, str):
            try: outcomes = json.loads(outcomes)
            except: outcomes = []
        if isinstance(prices, str):
            try: prices = json.loads(prices)
            except: prices = []
        price_map = {str(o).lower(): _safe_float(p) for o, p in zip(outcomes, prices)}

        return {
            "market_id":       market.get("id", ""),
            "market_question": market.get("question", market.get("group_title", "")),
            "market_url":      f"https://polymarket.com/event/{event.get('slug','')}",
            "direction":       direction,
            "current_price":   trade_price,
            "yes_price":       price_map.get("yes", 0.5),
            "no_price":        price_map.get("no", 0.5),
            "asset_id":        market.get("clobTokenIds", [None])[1 if direction == "NO" else 0],
            "signal_type":     "fresh_market_bracket",
            "edge":            abs(trade_price - 0.5) * 100,
            "confidence":      70,
            "noaa_probability": 50,
            "market_probability": trade_price * 100,
            "reasoning":       f"Fresh market — {direction} @ {trade_price:.2f} sebelum NO flood",
        }

    # ── Telegram alert ────────────────────────────────────────────────────────

    def _send_fresh_alert(self, event, executed_no, executed_yes,
                           total_bet, winner, simulation):
        """Kirim alert fresh market ke Telegram."""
        title      = event.get("title", "")
        age        = event.get("_age_minutes", "?")
        brackets   = event.get("_bracket_count", 0)
        mode_label = "🟡 SIMULATED" if simulation else "⚡ EXECUTED"

        winner_label = winner.get("group_title", "?") if winner else "unknown"

        msg = (
            f"🆕 {mode_label} FRESH MARKET\n\n"
            f"📊 {title[:60]}\n"
            f"⏱️ Age: {age} menit | {brackets} brackets\n\n"
            f"✅ BUY YES: {winner_label} (predicted winner)\n"
            f"❌ BUY NO : {len(executed_no)} brackets\n"
            f"💰 Total bet: ${total_bet:.2f}\n\n"
            f"🎯 Strategy: NO flood before others\n"
            f"📈 Expected: {len(executed_no)} × 2x payout"
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
            logger.error(f"Fresh market alert error: {e}")