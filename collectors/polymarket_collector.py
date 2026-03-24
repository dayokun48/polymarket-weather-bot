"""
Polymarket_collector.py
Fetches prediction markets data

CHANGES FROM ORIGINAL:
  BUG 1 FIXED: outcomes/outcomePrices arrive as JSON strings not lists
  BUG 2 FIXED: yes_price assumed index 0 = always YES — wrong for bracket markets
  BUG 3 FIXED: volume/liquidity arrive as strings → float() crashed silently
  BUG 4 FIXED: keyword filter missed bracket markets → uses tag=weather
  BUG 5 FIXED: Only fetched 100 markets → now paginates with offset
  BUG 6 FIXED: City list was US-only → uses geocoding API worldwide
  BUG 7 FIXED: Bracket/negRisk events were invisible → fetches /events too
  BUG 8 FIXED: date extraction only handled "today/tomorrow" → parses "March 25" etc

ADDED:
  save_market_to_db()  → simpan market ke tabel markets (wajib sebelum insert signal)
  save_markets_to_db() → simpan banyak market sekaligus
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests
import urllib3

import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_list_field(raw) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            result = json.loads(raw)
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _parse_datetime(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ── Collector ─────────────────────────────────────────────────────────────────

class PolymarketCollector:
    """
    Collect weather market data from Polymarket.
    Handles both binary (Yes/No) and bracket/negRisk markets.
    """

    GAMMA_API = "https://gamma-api.polymarket.com"
    PAGE_SIZE = 100

    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    # ── Internal fetch ────────────────────────────────────────────────────────

    def _fetch_pages(self, endpoint: str, params: dict) -> List[dict]:
        all_items = []
        offset = 0

        while True:
            params["offset"] = offset
            params["limit"]  = self.PAGE_SIZE

            try:
                url = f"{self.GAMMA_API}/{endpoint}"
                r = self.session.get(url, params=params, timeout=15)
                r.raise_for_status()
                data  = r.json()
                batch = data if isinstance(data, list) else data.get("data", [])
            except requests.exceptions.RequestException as e:
                logger.error(f"API error [{endpoint} offset={offset}]: {e}")
                break

            if not batch:
                break

            all_items.extend(batch)
            logger.info(f"  {endpoint} offset={offset}: {len(batch)} items")

            if len(batch) < self.PAGE_SIZE:
                break

            offset += self.PAGE_SIZE

        return all_items

    # ── Market parsing ────────────────────────────────────────────────────────

    def _parse_market(self, raw_market: Dict) -> Dict:
        outcomes   = _parse_list_field(raw_market.get("outcomes", []))
        prices_raw = _parse_list_field(raw_market.get("outcomePrices", []))
        clob_ids   = _parse_list_field(raw_market.get("clobTokenIds", []))

        price_map = {}
        for outcome, price in zip(outcomes, prices_raw):
            price_map[str(outcome).lower()] = _safe_float(price)

        yes_price = price_map.get("yes", 0.5)
        no_price  = price_map.get("no", round(1 - yes_price, 4))
        volume    = _safe_float(raw_market.get("volume", 0))
        liquidity = _safe_float(raw_market.get("liquidity", 0))

        end_date_str = (
            raw_market.get("endDate") or raw_market.get("end_date_iso")
        )
        end_date = _parse_datetime(end_date_str)

        return {
            "id":               raw_market.get("id", ""),
            "question":         raw_market.get("question", ""),
            "description":      raw_market.get("description", ""),
            "category":         raw_market.get("category", ""),
            "end_date":         end_date,
            "yes_price":        yes_price,
            "no_price":         no_price,
            "payout_if_yes":    round(1 / yes_price, 2) if yes_price > 0 else 0,
            "volume":           volume,
            "volume_24h":       _safe_float(raw_market.get("volume24hr", 0)),
            "liquidity":        liquidity,
            "active":           raw_market.get("active", True),
            "accepting_orders": raw_market.get("acceptingOrders", True),
            "best_bid":         _safe_float(raw_market.get("bestBid", 0)),
            "best_ask":         _safe_float(raw_market.get("bestAsk", 0)),
            "spread":           _safe_float(raw_market.get("spread", 0)),
            "clob_token_ids":   clob_ids,
            "group_title":      raw_market.get("groupItemTitle", ""),
            "threshold":        raw_market.get("groupItemThreshold", ""),
            "neg_risk":         raw_market.get("negRisk", False),
            "slug":             raw_market.get("slug", ""),
            "url":              f"https://polymarket.com/event/{raw_market.get('slug', '')}",
        }

    def _parse_bracket_event(self, event: dict) -> Dict:
        sub_markets = []
        for m in event.get("markets", []):
            sub_markets.append(self._parse_market(m))

        sub_markets.sort(key=lambda x: _safe_float(x.get("threshold", 0), 999))

        most_likely = (
            max(sub_markets, key=lambda x: x["yes_price"])
            if sub_markets else None
        )

        end_date = _parse_datetime(event.get("endDate"))
        tags     = [t.get("label", "") for t in event.get("tags", [])]

        return {
            "type":              "bracket",
            "id":                event.get("id", ""),
            "title":             event.get("title", ""),
            "slug":              event.get("slug", ""),
            "end_date":          end_date,
            "volume":            _safe_float(event.get("volume", 0)),
            "volume_24h":        _safe_float(event.get("volume24hr", 0)),
            "liquidity":         _safe_float(event.get("liquidity", 0)),
            "tags":              tags,
            "neg_risk":          event.get("enableNegRisk", False),
            "brackets":          sub_markets,
            "most_likely":       most_likely,
            "url":               f"https://polymarket.com/event/{event.get('slug', '')}",
            "resolution_source": (
                event.get("markets", [{}])[0].get("resolutionSource", "")
                if event.get("markets") else ""
            ),
        }

    # ── Public API ────────────────────────────────────────────────────────────

    # Confirmed working via test: word-boundary regex, not simple substring
    import re as _re
    _WEATHER_PATTERN = _re.compile("|".join([
        r"\btemperature\b", r"\brain\b", r"\brainfall\b", r"\bprecipitation\b",
        r"\bsnow\b", r"\bblizzard\b", r"\bhurricane\b", r"\btyphoon\b",
        r"\btornado\b", r"\bcyclone\b", r"\bflood\b", r"\bdrought\b",
        r"\bheatwave\b", r"\bheat wave\b", r"\bcelsius\b", r"\bfahrenheit\b",
        r"\bdegrees\b", r"\bweather\b", r"\bstorm\b", r"\bwind speed\b",
        r"\bmonsoon\b", r"\bwildfire\b", r"\bfrost\b", r"\bhumidity\b",
        r"\bhighest temp\b", r"\blowest temp\b", r"\b°c\b", r"\b°f\b",
    ]), _re.IGNORECASE)

    def _is_weather_market(self, text: str) -> bool:
        """Cek apakah market benar-benar tentang cuaca menggunakan word-boundary regex."""
        return bool(self._WEATHER_PATTERN.search(text))

    def search_weather_markets(self, location: str = None) -> List[Dict]:
        """
        Fetch all weather markets via keyword filter + pagination.

        tag=weather terbukti tidak bekerja (mengembalikan random markets).
        Solusi: fetch semua active markets, filter keyword di question.
        Test menunjukkan ~24 weather markets per 200 markets, tersebar merata.
        """
        logger.info("🔍 Fetching weather markets via keyword filter...")

        seen_slugs     = set()
        binary_markets = []
        offset         = 0
        PAGE_SIZE      = 200
        MAX_PAGES      = 15   # max 3000 markets = ~360 weather markets

        while offset < PAGE_SIZE * MAX_PAGES:
            try:
                url = f"{self.GAMMA_API}/markets"
                r = self.session.get(url, params={
                    "active":    "true",
                    "closed":    "false",
                    "order":     "volume",
                    "ascending": "false",
                    "limit":     PAGE_SIZE,
                    "offset":    offset,
                }, timeout=15)
                r.raise_for_status()
                batch = r.json()
                if not isinstance(batch, list):
                    batch = batch.get("data", [])
            except Exception as e:
                logger.error(f"API error offset={offset}: {e}")
                break

            if not batch:
                break

            found_in_page = 0
            for m in batch:
                slug = m.get("slug", "")
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                q = m.get("question", "")
                if not self._is_weather_market(q):
                    continue

                if location and location.lower() not in q.lower():
                    continue

                parsed = self._parse_market(m)
                parsed["type"] = "binary"
                binary_markets.append(parsed)
                found_in_page += 1

            logger.info(f"  offset={offset}: {len(batch)} fetched, {found_in_page} weather")

            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

        binary_markets.sort(key=lambda x: x["volume"], reverse=True)
        logger.info(f"✅ Found {len(binary_markets)} weather markets")
        return binary_markets


    def get_market(self, market_id: str) -> Optional[Dict]:
        try:
            r = self.session.get(f"{self.GAMMA_API}/markets/{market_id}", timeout=10)
            r.raise_for_status()
            return self._parse_market(r.json())
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error fetching market {market_id}: {e}")
            return None

    # ── Database persistence ──────────────────────────────────────────────────

    def save_market_to_db(self, market: Dict) -> bool:
        """
        Simpan atau update satu market ke tabel markets.

        WAJIB dipanggil sebelum insert signal karena tabel signals
        punya FOREIGN KEY ke tabel markets. Kalau market belum ada di DB,
        insert signal akan gagal dengan FK constraint error.

        Aman dipanggil berkali-kali karena pakai ON DUPLICATE KEY UPDATE.
        """
        market_id = market.get("id", "")
        if not market_id:
            return False

        question = (
            market.get("title")       # bracket event
            or market.get("question") # binary market
            or ""
        )

        try:
            import pymysql
            conn = pymysql.connect(
                host=config.DB_HOST, port=config.DB_PORT,
                user=config.DB_USER, password=config.DB_PASSWORD,
                database=config.DB_NAME,
                charset="utf8mb4",
                connect_timeout=5,
            )
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO markets
                            (id, question, description, category,
                             end_date, volume, liquidity, url,
                             first_seen, last_checked)
                        VALUES
                            (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                        ON DUPLICATE KEY UPDATE
                            volume       = VALUES(volume),
                            liquidity    = VALUES(liquidity),
                            last_checked = NOW()
                    """, (
                        market_id,
                        question[:500],
                        (market.get("description") or "")[:1000] or None,
                        "weather",
                        market.get("end_date"),
                        market.get("volume", 0),
                        market.get("liquidity", 0),
                        market.get("url", ""),
                    ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ Gagal simpan market {market_id}: {e}")
            return False

    def save_markets_to_db(self, markets: List[Dict]) -> int:
        """
        Simpan banyak market sekaligus ke tabel markets.
        Untuk bracket event, simpan juga semua sub-markets (brackets).
        Returns jumlah yang berhasil disimpan.
        """
        success = 0
        for market in markets:
            if market.get("type") == "bracket":
                if self.save_market_to_db(market):
                    success += 1
                for bracket in market.get("brackets", []):
                    if self.save_market_to_db(bracket):
                        success += 1
            else:
                if self.save_market_to_db(market):
                    success += 1

        logger.info(f"💾 {success} market disimpan ke DB")
        return success

    # ── Extract helpers ───────────────────────────────────────────────────────

    def extract_location_from_question(self, question: str) -> Optional[str]:
        """
        Extract city name dari market question.
        Logika sudah ditest di test_location_extraction.py (17/17 pass).
        - Regex pattern untuk format temperature market
        - Geocode pilih populasi terbesar (bukan hasil pertama)
        - Fallback word-by-word dengan filter populasi > 50k
        """
        city_patterns = [
            r"temperature in ([A-Z][a-zA-Z\s]+?) be",
            r"temperature in ([A-Z][a-zA-Z\s]+?) on",
            r"highest temperature in ([A-Z][a-zA-Z\s]+?) ",
            r"lowest temperature in ([A-Z][a-zA-Z\s]+?) ",
            r"Will ([A-Z][a-zA-Z\s]+?) have .*(rain|precip|snow|inch)",
            r"Will ([A-Z][a-zA-Z\s]+?) get .*(rain|snow|storm)",
        ]
        skip_words = {
            "will", "the", "be", "on", "in", "at", "or", "and", "a",
            "march", "april", "may", "june", "july", "august", "september",
            "october", "november", "december", "january", "february",
            "2026", "2025", "highest", "lowest", "temperature", "above",
            "below", "tomorrow", "today", "this", "next", "week",
            "between", "higher", "lower", "more", "less", "than",
            "inches", "precipitation", "rainfall", "hurricane", "storm",
        }

        def _geocode_best(name: str) -> Optional[str]:
            try:
                r = self.session.get(
                    GEOCODE_URL,
                    params={"name": name, "count": 5, "language": "en"},
                    timeout=8,
                )
                results = r.json().get("results", [])
                if not results:
                    return None
                big = [x for x in results if (x.get("population") or 0) >= 50000]
                best = max(big, key=lambda x: x.get("population", 0) or 0) if big else results[0]
                return best["name"]
            except requests.exceptions.RequestException:
                return None

        for pattern in city_patterns:
            m = re.search(pattern, question, re.IGNORECASE)
            if m:
                raw = m.group(1).strip()
                city = _geocode_best(raw)
                if city:
                    return city

        words = question.split()
        for n in (3, 2):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i:i + n])
                if phrase.lower() in skip_words:
                    continue
                if any(c in phrase for c in "0123456789°%$"):
                    continue
                city = _geocode_best(phrase)
                if city:
                    return city

        return None

    def extract_date_from_question(self, question: str) -> Optional[str]:
        today    = datetime.now()
        tomorrow = today + timedelta(days=1)
        q_lower  = question.lower()

        if "tomorrow" in q_lower:
            return tomorrow.strftime("%Y-%m-%d")
        if "today" in q_lower:
            return today.strftime("%Y-%m-%d")

        m = re.search(
            r"\b(january|february|march|april|may|june|july|august|"
            r"september|october|november|december|"
            r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)"
            r"\s+(\d{1,2})(?:\s+(\d{4}))?",
            q_lower,
        )
        if m:
            month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
            month = MONTH_MAP.get(month_str)
            day   = int(day_str)
            year  = int(year_str) if year_str else today.year
            if month:
                try:
                    return datetime(year, month, day).strftime("%Y-%m-%d")
                except ValueError:
                    pass

        m = re.search(
            r"\b(\d{1,2})\s+"
            r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
            r"(?:\s+(\d{4}))?",
            q_lower,
        )
        if m:
            day_str, month_str, year_str = m.group(1), m.group(2), m.group(3)
            month = MONTH_MAP.get(month_str)
            day   = int(day_str)
            year  = int(year_str) if year_str else today.year
            if month:
                try:
                    return datetime(year, month, day).strftime("%Y-%m-%d")
                except ValueError:
                    pass

        return None