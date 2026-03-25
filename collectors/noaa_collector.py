"""
noaa_collector.py
==================
Weather data collector dengan multiple sources:

  US cities    → NOAA (api.weather.gov) — resmi, akurat, free
  Global       → Open-Meteo ECMWF — lebih akurat dari GFS, free
  Global       → Tomorrow.io — spesialis hourly, free 500/hari
  Verifikasi   → Wunderground scraping — sama dengan sumber resolusi Polymarket

Tambahan vs sebelumnya:
  - Open-Meteo ECMWF model (lebih akurat dari GFS default)
  - Tomorrow.io sebagai source ke-3
  - get_consensus() gabungkan 3 sources → confidence lebih tinggi
  - save_forecast_to_db() untuk simpan forecast ke tabel weather_forecasts
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

import config

logger = logging.getLogger(__name__)

WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm + hail", 99: "Thunderstorm + heavy hail",
}

US_REGIONS = [
    (24.0, 50.0, -125.0, -66.5),   # Continental US (lon -66.5 excludes eastern Canada)
    (18.0, 23.0, -161.0, -154.0),  # Hawaii
    (51.0, 72.0, -168.0, -130.0),  # Alaska
]

# Known non-US cities that fall inside US bounding box due to proximity
NON_US_CITIES = {"toronto", "montreal", "ottawa", "vancouver", "calgary",
                 "havana", "nassau", "kingston", "santo domingo"}


def _is_us_location(lat: float, lon: float, city_name: str = "") -> bool:
    """Cek apakah koordinat berada di wilayah US.
    Exclude kota Canada/Caribbean yang koordinatnya mirip US.
    """
    if city_name.lower() in NON_US_CITIES:
        return False
    return any(
        lat_min <= lat <= lat_max and lon_min <= lon <= lon_max
        for lat_min, lat_max, lon_min, lon_max in US_REGIONS
    )


def _safe_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# NOAA SOURCE (US only)
# ─────────────────────────────────────────────────────────────────────────────

class _NOAASource:
    def __init__(self, session: requests.Session):
        self.session = session

    def get_forecast(self, lat: float, lon: float) -> Optional[List[Dict]]:
        try:
            r = self.session.get(
                f"{config.NOAA_API}/points/{lat:.4f},{lon:.4f}",
                timeout=10,
            )
            r.raise_for_status()
            forecast_url = r.json()["properties"]["forecast"]
            r2 = self.session.get(forecast_url, timeout=10)
            r2.raise_for_status()
            return self._parse(r2.json()["properties"]["periods"])
        except Exception as e:
            logger.error(f"NOAA fetch error ({lat},{lon}): {e}")
            return None

    def _parse(self, periods: list) -> List[Dict]:
        forecasts = []
        for i in range(0, min(len(periods), 14), 2):
            day   = periods[i]
            night = periods[i + 1] if i + 1 < len(periods) else {}
            date  = day["startTime"][:10]

            rain_prob   = day.get("probabilityOfPrecipitation", {}).get("value") or 0
            temp_f_high = _safe_float(day.get("temperature", 0))
            temp_f_low  = _safe_float(night.get("temperature", 0))
            temp_c_high = round((temp_f_high - 32) * 5 / 9, 1)
            temp_c_low  = round((temp_f_low  - 32) * 5 / 9, 1)

            forecasts.append({
                "date":              date,
                "rain_probability":  rain_prob,
                "temperature_high":  temp_c_high,
                "temperature_low":   temp_c_low,
                "temp_high_celsius": temp_c_high,
                "temp_low_celsius":  temp_c_low,
                "hourly_max":        temp_c_high,
                "peak_hour":         "N/A",
                "precip_mm":         0.0,
                "wind_speed_max":    0.0,
                "wmo_code":          None,
                "conditions":        day.get("shortForecast", ""),
                "hourly_temps":      [],
                "source":            "NOAA",
            })
        return forecasts


# ─────────────────────────────────────────────────────────────────────────────
# OPEN-METEO SOURCE (Global)
# ─────────────────────────────────────────────────────────────────────────────

class _OpenMeteoSource:
    def __init__(self, session: requests.Session):
        self.session = session

    def get_forecast(self, lat: float, lon: float, tz: str = "auto", model: str = None) -> Optional[List[Dict]]:
        params = {
            "latitude":   lat, "longitude":  lon, "timezone":   tz,
            "forecast_days": 7,
            "daily": ",".join([
                "temperature_2m_max", "temperature_2m_min",
                "precipitation_probability_max", "precipitation_sum",
                "wind_speed_10m_max", "weather_code",
            ]),
            "hourly":             "temperature_2m,precipitation_probability",
            "temperature_unit":   "celsius",
            "wind_speed_unit":    "kmh",
            "precipitation_unit": "mm",
        }
        # ECMWF model lebih akurat dari GFS default
        if model:
            params["models"] = model
        try:
            r = self.session.get(config.OPEN_METEO_API, params=params, timeout=15)
            r.raise_for_status()
            return self._parse(r.json())
        except Exception as e:
            logger.error(f"Open-Meteo fetch error ({lat},{lon}): {e}")
            return None

    def _parse(self, raw: dict) -> List[Dict]:
        daily  = raw.get("daily", {})
        hourly = raw.get("hourly", {})

        dates      = daily.get("time", [])
        temp_maxes = daily.get("temperature_2m_max", [])
        temp_mins  = daily.get("temperature_2m_min", [])
        precip_p   = daily.get("precipitation_probability_max", [])
        precip_mm  = daily.get("precipitation_sum", [])
        wind_max   = daily.get("wind_speed_10m_max", [])
        wmo_codes  = daily.get("weather_code", [])
        h_times    = hourly.get("time", [])
        h_temps    = hourly.get("temperature_2m", [])

        forecasts = []
        for i, date in enumerate(dates):
            day_hours  = [(t[11:16], temp) for t, temp in zip(h_times, h_temps)
                          if t.startswith(date) and temp is not None]
            hourly_max = max((t for _, t in day_hours), default=None)
            peak_hour  = max(day_hours, key=lambda x: x[1])[0] if day_hours else "N/A"
            wmo        = wmo_codes[i] if i < len(wmo_codes) else None

            forecasts.append({
                "date":              date,
                "rain_probability":  precip_p[i]   if i < len(precip_p)   else 0,
                "temperature_high":  temp_maxes[i] if i < len(temp_maxes) else None,
                "temperature_low":   temp_mins[i]  if i < len(temp_mins)  else None,
                "temp_high_celsius": temp_maxes[i] if i < len(temp_maxes) else None,
                "temp_low_celsius":  temp_mins[i]  if i < len(temp_mins)  else None,
                "hourly_max":        hourly_max,
                "peak_hour":         peak_hour,
                "precip_mm":         precip_mm[i]  if i < len(precip_mm)  else 0,
                "wind_speed_max":    wind_max[i]   if i < len(wind_max)   else 0,
                "wmo_code":          wmo,
                "conditions":        WMO_CODES.get(wmo, f"Code {wmo}"),
                "hourly_temps":      day_hours,
                "source":            "Open-Meteo",
            })
        return forecasts


# ─────────────────────────────────────────────────────────────────────────────
# TOMORROW.IO SOURCE (Global, 500 calls/day free)
# ─────────────────────────────────────────────────────────────────────────────

class _TomorrowIOSource:
    """
    Tomorrow.io weather API — spesialis hourly forecast, akurat untuk Asia.
    Free tier: 500 calls/hari, cukup untuk bot.
    Daftar di: tomorrow.io/try-the-api
    """

    BASE_URL = "https://api.tomorrow.io/v4/weather/forecast"

    def __init__(self, session: requests.Session):
        self.session = session

    def get_forecast(self, lat: float, lon: float) -> Optional[List[Dict]]:
        api_key = config.TOMORROW_IO_API_KEY
        if not api_key or api_key == "-":
            return None

        try:
            r = self.session.get(
                self.BASE_URL,
                params={
                    "location":  f"{lat},{lon}",
                    "apikey":    api_key,
                    "units":     "metric",
                    "fields":    "temperatureMax,temperatureMin,precipitationProbability",
                    "timesteps": "1d",
                },
                timeout=10,
            )
            r.raise_for_status()
            return self._parse(r.json())
        except Exception as e:
            logger.error(f"Tomorrow.io fetch error ({lat},{lon}): {e}")
            return None

    def _parse(self, raw: dict) -> List[Dict]:
        forecasts = []
        try:
            timelines = raw.get("timelines", {}).get("daily", [])
            for item in timelines:
                date    = item["time"][:10]
                values  = item.get("values", {})
                temp_max = values.get("temperatureMax")
                temp_min = values.get("temperatureMin")
                rain_p   = values.get("precipitationProbability", 0)

                forecasts.append({
                    "date":              date,
                    "rain_probability":  rain_p,
                    "temperature_high":  temp_max,
                    "temperature_low":   temp_min,
                    "temp_high_celsius": temp_max,
                    "temp_low_celsius":  temp_min,
                    "hourly_max":        temp_max,
                    "peak_hour":         "N/A",
                    "precip_mm":         0.0,
                    "wind_speed_max":    0.0,
                    "wmo_code":          None,
                    "conditions":        "Tomorrow.io",
                    "hourly_temps":      [],
                    "source":            "Tomorrow.io",
                })
        except Exception as e:
            logger.error(f"Tomorrow.io parse error: {e}")
        return forecasts


# ─────────────────────────────────────────────────────────────────────────────
# WUNDERGROUND SCRAPER
# ─────────────────────────────────────────────────────────────────────────────

class _WundergroundScraper:
    def __init__(self, session: requests.Session):
        self.session = session

    def get_actual_temp_by_url(self, wunderground_url: str, date: str) -> Optional[Dict]:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            r = self.session.get(wunderground_url, headers=headers, timeout=15)
            r.raise_for_status()
            return self._parse_html(r.text, date)
        except Exception as e:
            logger.error(f"Wunderground scrape error: {e}")
            return None

    def _parse_html(self, html: str, date: str) -> Optional[Dict]:
        patterns = [
            r'Max\s*Temp[^>]*>\s*([\d.]+)',
            r'High\s*Temp[^>]*>\s*([\d.]+)',
            r'"tempHigh"[^>]*>([\d.]+)',
            r'class="high-temp[^"]*"[^>]*>([\d.]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return {
                    "date":         date,
                    "actual_high":  float(match.group(1)),
                    "source":       "Wunderground",
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
        logger.warning(f"Tidak bisa parse suhu Wunderground untuk {date}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN COLLECTOR
# ─────────────────────────────────────────────────────────────────────────────

class NOAACollector:
    """
    Weather collector dengan multi-source, consensus, dan DB persistence.

    Routing:
      US coordinates  → NOAA + Open-Meteo ECMWF + Tomorrow.io
      Non-US          → Open-Meteo ECMWF + Tomorrow.io
      Verifikasi      → Wunderground scraping

    3 sources → confidence lebih tinggi dan lebih konsisten.
    """

    def __init__(self):
        self.session       = requests.Session()
        self.session.headers.update({"User-Agent": "PolymarketWeatherBot/2.0"})
        self._noaa         = _NOAASource(self.session)
        self._openmeteo    = _OpenMeteoSource(self.session)
        self._tomorrowio   = _TomorrowIOSource(self.session)
        self._wunderground = _WundergroundScraper(self.session)

    # ── Geocoding ──────────────────────────────────────────────────────────────

    def get_coordinates(self, location: str) -> Tuple[float, float, str]:
        try:
            r = self.session.get(
                config.OPEN_METEO_GEO,
                params={"name": location, "count": 1, "language": "en"},
                timeout=10,
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                logger.warning(f"Kota tidak ditemukan: '{location}'")
                return (0.0, 0.0, "UTC")
            hit = results[0]
            lat, lon, tz = hit["latitude"], hit["longitude"], hit.get("timezone", "UTC")
            logger.info(f"Geocoded '{location}' → {hit['name']}, {hit.get('country','')} ({lat},{lon})")
            return (lat, lon, tz)
        except Exception as e:
            logger.error(f"Geocoding gagal '{location}': {e}")
            return (0.0, 0.0, "UTC")

    # ── Forecast ───────────────────────────────────────────────────────────────

    def get_forecast(self, location: str) -> Optional[Dict]:
        lat, lon, tz = self.get_coordinates(location)
        if lat == 0.0 and lon == 0.0:
            return None
        return self.get_forecast_by_coords(lat, lon, tz, location_name=location)

    def get_forecast_by_coords(
        self, lat: float, lon: float, tz: str = "auto", location_name: str = ""
    ) -> Optional[Dict]:
        is_us = _is_us_location(lat, lon, location_name)
        forecasts, source_used = None, ""

        if is_us:
            noaa_data = self._noaa.get_forecast(lat, lon)
            if noaa_data:
                forecasts, source_used = noaa_data, "NOAA"
            else:
                logger.warning("NOAA gagal → fallback ke Open-Meteo")

        if not forecasts:
            forecasts = self._openmeteo.get_forecast(lat, lon, tz)
            source_used = "Open-Meteo"

        if not forecasts:
            return None

        return {
            "location":     location_name or f"{lat},{lon}",
            "latitude":     lat,
            "longitude":    lon,
            "timezone":     tz,
            "is_us":        is_us,
            "source":       source_used,
            "forecasts":    forecasts,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Consensus ──────────────────────────────────────────────────────────────

    def get_consensus(self, location: str, target_date: str) -> Optional[Dict]:
        """
        Ambil consensus dari semua sources yang tersedia.
        Semakin banyak source sepakat → confidence lebih tinggi.

        Sources:
          US:     NOAA + Open-Meteo ECMWF + Tomorrow.io (max 3)
          Global: Open-Meteo ECMWF + Tomorrow.io (max 2)
        """
        lat, lon, tz = self.get_coordinates(location)
        if lat == 0.0 and lon == 0.0:
            return None

        sources  = []
        is_us    = _is_us_location(lat, lon, location)

        # Source 1: NOAA (US only)
        if is_us:
            noaa = self._noaa.get_forecast(lat, lon)
            if noaa:
                day = next((d for d in noaa if d["date"] == target_date), None)
                if day:
                    sources.append(day)

        # Source 2: Open-Meteo ECMWF (lebih akurat dari GFS default)
        om = self._openmeteo.get_forecast(lat, lon, tz, model="ecmwf_ifs025")
        if om:
            day = next((d for d in om if d["date"] == target_date), None)
            if day:
                day["source"] = "Open-Meteo ECMWF"
                sources.append(day)
        else:
            # Fallback ke GFS kalau ECMWF tidak tersedia
            om_gfs = self._openmeteo.get_forecast(lat, lon, tz)
            if om_gfs:
                day = next((d for d in om_gfs if d["date"] == target_date), None)
                if day:
                    sources.append(day)

        # Source 3: Tomorrow.io (kalau API key tersedia)
        if config.TOMORROW_IO_API_KEY and config.TOMORROW_IO_API_KEY != "-":
            tio = self._tomorrowio.get_forecast(lat, lon)
            if tio:
                day = next((d for d in tio if d["date"] == target_date), None)
                if day:
                    sources.append(day)

        if not sources:
            return None

        temps = [
            s["hourly_max"] or s["temperature_high"]
            for s in sources
            if (s.get("hourly_max") or s.get("temperature_high")) is not None
        ]
        rains = [s["rain_probability"] for s in sources if s.get("rain_probability") is not None]

        avg_temp    = round(sum(temps) / len(temps), 1) if temps else None
        avg_rain    = round(sum(rains) / len(rains), 1) if rains else None
        temp_spread = round(max(temps) - min(temps), 1) if len(temps) > 1 else 0.0

        # Confidence scoring: lebih banyak source + lebih sepakat = lebih tinggi
        n = len(sources)
        if n >= 3 and temp_spread < 1.5:   confidence = 90
        elif n >= 3 and temp_spread < 3.0: confidence = 80
        elif n >= 3:                        confidence = 70
        elif n >= 2 and temp_spread < 2.0: confidence = 75
        elif n >= 2 and temp_spread < 4.0: confidence = 65
        elif n >= 2:                        confidence = 55
        else:                               confidence = 50

        return {
            "location":      location,
            "date":          target_date,
            "avg_temp_high": avg_temp,
            "avg_rain_prob": avg_rain,
            "temp_spread":   temp_spread,
            "confidence":    confidence,
            "sources_used":  [s["source"] for s in sources],
            "source_count":  len(sources),
            "detail":        sources,
            "retrieved_at":  datetime.now(timezone.utc).isoformat(),
        }

    # ── Simpan forecast ke database ────────────────────────────────────────────

    def save_forecast_to_db(self, location: str, target_date: str) -> bool:
        """
        Ambil forecast dan simpan ke tabel weather_forecasts.
        Dipanggil setelah get_consensus() untuk persistence.

        Returns True jika berhasil.
        """
        forecast = self.get_forecast(location)
        if not forecast:
            return False

        day = next(
            (d for d in forecast["forecasts"] if d["date"] == target_date),
            None
        )
        if not day:
            return False

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
                    # Upsert: kalau sudah ada untuk lokasi+tanggal+source, update
                    cur.execute("""
                        INSERT INTO weather_forecasts
                            (location, target_date, rain_probability,
                             temperature_high, temperature_low,
                             conditions, detailed, source, retrieved_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            rain_probability = VALUES(rain_probability),
                            temperature_high = VALUES(temperature_high),
                            temperature_low  = VALUES(temperature_low),
                            conditions       = VALUES(conditions),
                            retrieved_at     = VALUES(retrieved_at)
                    """, (
                        location,
                        target_date,
                        day.get("rain_probability"),
                        day.get("hourly_max") or day.get("temperature_high"),
                        day.get("temperature_low"),
                        day.get("conditions", ""),
                        str(day.get("hourly_temps", "")),
                        day.get("source", "Unknown"),
                        datetime.now(timezone.utc),
                    ))
                conn.commit()
            logger.info(f"💾 Forecast {location} {target_date} disimpan ke DB")
            return True
        except Exception as e:
            logger.error(f"❌ Gagal simpan forecast ke DB: {e}")
            return False

    # ── Verifikasi resolusi ────────────────────────────────────────────────────

    def verify_resolution(self, wunderground_url: str, date: str) -> Optional[Dict]:
        logger.info(f"🔍 Verifikasi via Wunderground: {wunderground_url}")
        return self._wunderground.get_actual_temp_by_url(wunderground_url, date)

    # ── Convenience methods ────────────────────────────────────────────────────

    def get_rain_probability(self, location: str, target_date: str) -> Optional[float]:
        forecast = self.get_forecast(location)
        if not forecast:
            return None
        for p in forecast["forecasts"]:
            if p["date"] == target_date:
                return p["rain_probability"]
        return None

    def get_max_temperature(self, location: str, target_date: str) -> Optional[float]:
        forecast = self.get_forecast(location)
        if not forecast:
            return None
        for p in forecast["forecasts"]:
            if p["date"] == target_date:
                return p["hourly_max"] or p["temperature_high"]
        return None

    def get_forecast_for_date(self, location: str, target_date: str) -> Optional[Dict]:
        forecast = self.get_forecast(location)
        if not forecast:
            return None
        for p in forecast["forecasts"]:
            if p["date"] == target_date:
                return p
        return None