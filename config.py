"""
config.py
=========
Credentials  → .env (DB password, Telegram token, Wallet key, Flask)
Bot settings → database bot_settings table (edge, interval, limits, dll)

Weather sources:
  - NOAA        : US cities (free, no key)
  - Open-Meteo  : Global cities (free, no key)
  - Wunderground: Scraping untuk verifikasi resolusi Polymarket (no key)
  - OpenWeather : TIDAK DIPAKAI (free tier tidak berguna untuk trading)
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Polymarket API (hardcoded, tidak perlu di .env) ────────────────────────────
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API  = "https://data-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

# ── Weather API URLs (hardcoded, semua free tanpa key) ─────────────────────────
NOAA_API         = "https://api.weather.gov"
OPEN_METEO_API   = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEO   = "https://geocoding-api.open-meteo.com/v1/search"
WUNDERGROUND_URL = "https://www.wunderground.com/history/daily"  # scraping

# ── Credentials dari .env ──────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
PRIVATE_KEY    = os.getenv("PRIVATE_KEY")

DB_HOST     = os.getenv("DB_HOST",  "127.0.0.1")
DB_PORT     = int(os.getenv("DB_PORT", 3306))
DB_USER     = os.getenv("DB_USER",  "root")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME     = os.getenv("DB_NAME",  "polymarket_weather")

FLASK_PORT       = int(os.getenv("FLASK_PORT", 5000))
FLASK_DEBUG      = os.getenv("FLASK_DEBUG", "False") == "True"
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE  = os.getenv("LOG_FILE",  "logs/weather_bot.log")

# ── Default bot settings (fallback jika key tidak ada di database) ─────────────
# Setelah migrate_bot_settings.py dijalankan, defaults ini tidak pernah dipakai.
SETTING_DEFAULTS = {
    "automation_mode":        "semi-auto",  # manual | semi-auto | full-auto
    "min_edge_pct":           "15",         # minimum edge % untuk alert/trade
    "min_confidence_pct":     "80",         # minimum confidence dari weather consensus
    "max_bet_pct":            "5",          # % maksimal bankroll per trade
    "max_daily_trades":       "10",         # batas trade per hari
    "max_daily_loss_pct":     "10",         # batas loss per hari dalam %
    "check_interval_minutes": "120",        # interval cek market
    "alert_cooldown_seconds": "300",        # jeda antar alert Telegram
    "min_market_volume":      "1000",       # minimum volume market USD
    "min_market_liquidity":   "500",        # minimum likuiditas USD
    "min_time_left_hours":    "1",          # abaikan market yang tutup < 1 jam
    "max_time_left_hours":    "72",         # abaikan market yang tutup > 72 jam
}

# Cache runtime — diisi oleh load_settings_from_db()
_settings: dict = {}


# ── Load dari database ─────────────────────────────────────────────────────────

def load_settings_from_db() -> dict:
    """
    Load semua baris dari bot_settings ke memory.
    Fallback ke SETTING_DEFAULTS untuk key yang tidak ada di DB.
    Panggil lagi kapan saja untuk hot-reload tanpa restart bot.
    """
    import pymysql

    loaded = {}
    try:
        conn = pymysql.connect(
            host=DB_HOST, port=DB_PORT,
            user=DB_USER, password=DB_PASSWORD,
            database=DB_NAME,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT setting_key, setting_value FROM bot_settings")
                for row in cur.fetchall():
                    loaded[row["setting_key"]] = row["setting_value"]
        logger.info(f"✅ Loaded {len(loaded)} settings from database")
    except Exception as e:
        logger.warning(f"⚠️  DB settings tidak bisa dibaca: {e} — pakai defaults")

    merged = {**SETTING_DEFAULTS, **loaded}
    _settings.update(merged)
    return merged


def get(key: str, cast=str):
    """
    Baca satu setting dari cache.

    Contoh:
        config.get("min_edge_pct", float)         → 15.0
        config.get("automation_mode")              → "semi-auto"
        config.get("check_interval_minutes", int)  → 120
    """
    if not _settings:
        load_settings_from_db()
    raw = _settings.get(key, SETTING_DEFAULTS.get(key, ""))
    try:
        return cast(raw)
    except (ValueError, TypeError):
        logger.error(f"Tidak bisa cast '{key}'='{raw}' ke {cast.__name__}")
        return cast(SETTING_DEFAULTS.get(key, "0"))


# ── Shortcut functions (agar kode lain tidak perlu berubah) ───────────────────

def AUTOMATION_MODE():          return get("automation_mode")
def MIN_EDGE_PCT():             return get("min_edge_pct",           float)
def MIN_CONFIDENCE_PCT():       return get("min_confidence_pct",     float)
def MAX_BET_PCT():              return get("max_bet_pct",            float)
def MAX_DAILY_TRADES():         return get("max_daily_trades",       int)
def MAX_DAILY_LOSS_PCT():       return get("max_daily_loss_pct",     float)
def CHECK_INTERVAL_MINUTES():   return get("check_interval_minutes", int)
def CHECK_INTERVAL_SECONDS():   return get("check_interval_minutes", int) * 60
def ALERT_COOLDOWN_SECONDS():   return get("alert_cooldown_seconds", int)
def MIN_MARKET_VOLUME():        return get("min_market_volume",      float)
def MIN_MARKET_LIQUIDITY():     return get("min_market_liquidity",   float)
def MIN_TIME_LEFT_HOURS():      return get("min_time_left_hours",    float)
def MAX_TIME_LEFT_HOURS():      return get("max_time_left_hours",    float)


# ── Validasi ───────────────────────────────────────────────────────────────────

VALID_AUTOMATION_MODES = {"manual", "semi-auto", "full-auto"}


def validate_config():
    """
    Validasi credentials (.env) dan settings (database).
    Tampilkan SEMUA error sekaligus.
    """
    errors   = []
    warnings = []

    # Credentials wajib
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN tidak ada di .env")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID tidak ada di .env")
    if not DB_PASSWORD:
        errors.append("DB_PASSWORD tidak ada di .env")

    # Wallet hanya wajib di full-auto
    mode = get("automation_mode")
    if mode == "full-auto":
        if not WALLET_ADDRESS or WALLET_ADDRESS == "-":
            errors.append("WALLET_ADDRESS wajib diisi di .env jika automation_mode=full-auto")
        if not PRIVATE_KEY or PRIVATE_KEY == "-":
            errors.append("PRIVATE_KEY wajib diisi di .env jika automation_mode=full-auto")

    if mode not in VALID_AUTOMATION_MODES:
        errors.append(
            f"automation_mode='{mode}' tidak valid. "
            f"Pilihan: {', '.join(sorted(VALID_AUTOMATION_MODES))}"
        )

    # Warnings
    if FLASK_SECRET_KEY == "dev-secret-key-change-in-production":
        warnings.append("FLASK_SECRET_KEY masih pakai default — ganti di .env")
    if get("max_bet_pct", float) > 25:
        warnings.append(f"max_bet_pct={get('max_bet_pct')}% terlalu tinggi")

    for w in warnings:
        logger.warning(f"⚠️  {w}")

    if errors:
        raise ValueError(
            "Konfigurasi error:\n" + "\n".join(f"  ✗ {e}" for e in errors)
        )

    print("✅ Konfigurasi valid!")


def print_config():
    """Print konfigurasi aktif untuk debugging."""
    source = "database" if _settings else "defaults saja"
    token  = (TELEGRAM_BOT_TOKEN[:10] + "...") if TELEGRAM_BOT_TOKEN else "TIDAK ADA"
    wallet = (WALLET_ADDRESS[:8] + "...") if WALLET_ADDRESS and WALLET_ADDRESS != "-" else "TIDAK DISET"

    print(f"""
Konfigurasi Aktif  (sumber setting: {source})
─────────────────────────────────────────────
Mode              : {get('automation_mode')}
Check interval    : setiap {get('check_interval_minutes')} menit
Alert cooldown    : {get('alert_cooldown_seconds')} detik

Risk limits (dari DB)
  Min edge        : {get('min_edge_pct')}%
  Min confidence  : {get('min_confidence_pct')}%
  Max bet         : {get('max_bet_pct')}% dari bankroll
  Max trades/hari : {get('max_daily_trades')}
  Max loss/hari   : {get('max_daily_loss_pct')}%

Market filters (dari DB)
  Min volume      : ${float(get('min_market_volume')):,.0f}
  Min liquidity   : ${float(get('min_market_liquidity')):,.0f}
  Time window     : {get('min_time_left_hours')}h – {get('max_time_left_hours')}h

Weather sources
  US cities       : NOAA (free, no key)
  Global cities   : Open-Meteo (free, no key)
  Resolusi check  : Wunderground scraping (no key)

Credentials (dari .env)
  Database        : {DB_NAME}@{DB_HOST}:{DB_PORT}
  Telegram        : {token}
  Wallet          : {wallet}
  Flask           : port {FLASK_PORT}  debug={FLASK_DEBUG}
─────────────────────────────────────────────""")


# ── Auto-load saat diimport ────────────────────────────────────────────────────
load_settings_from_db()


if __name__ == "__main__":
    validate_config()
    print_config()