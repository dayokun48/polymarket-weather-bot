"""
app.py
=======
Polymarket Weather Trading Bot — Main Application.

Perubahan dari original:
  - Hapus SQLAlchemy ORM (from database import db) — semua file pakai pymysql
  - Hapus save_market_to_db / save_forecast_to_db / save_signal_to_db yang duplikat
    → sudah ada di Polymarket_collector.py, noaa_collector.py, risk_manager.py
  - Hapus hardcode cities list → scan semua market via tag=weather
  - Fix risk_mgr.validate_signal() tambah parameter bankroll
  - Fix config.AUTOMATION_MODE → config.AUTOMATION_MODE() (function call)
  - Fix config.CHECK_INTERVAL_SECONDS → config.CHECK_INTERVAL_SECONDS()
  - Fix app.config SECRET_KEY dari config bukan hardcoded
  - Fix flow: save_markets_to_db() dulu sebelum record_signal()
  - Fix initialize_database() tidak insert settings lama yang salah
  - Fix datetime.utcnow() → datetime.now(timezone.utc)
  - Tambah bankroll dari DB (tabel bot_settings atau default $1000)
"""

import logging
import os
import sys
from datetime import datetime, date, timezone

from flask import Flask, jsonify

import config

# ── Logging setup ──────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(name)-20s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = config.FLASK_SECRET_KEY   # FIX: dari config, bukan hardcoded

# ── Import components ──────────────────────────────────────────────────────────
from collectors.noaa_collector       import NOAACollector
from collectors.polymarket_collector import PolymarketCollector
from analyzers.weather_analyzer      import WeatherAnalyzer
from analyzers.arbitrage_calculator  import ArbitrageCalculator
from analyzers.risk_manager          import RiskManager
from executors.polymarket_trader     import PolymarketTrader
from executors.position_tracker      import PositionTracker
from notifications.telegram_bot      import TelegramBot

# ── Initialize components ──────────────────────────────────────────────────────
noaa             = NOAACollector()
polymarket       = PolymarketCollector()
weather_analyzer = WeatherAnalyzer(noaa, polymarket)
arbitrage_calc   = ArbitrageCalculator()
risk_mgr         = RiskManager(arbitrage_calc)
telegram         = TelegramBot()
trader           = PolymarketTrader()
position_tracker = PositionTracker()

# ── Register routes ────────────────────────────────────────────────────────────
try:
    from routes import register_routes
    register_routes(app)
    logger.info("✅ Routes registered")
except ImportError:
    logger.warning("⚠️  routes module tidak ditemukan — skip")

# ── Global state ───────────────────────────────────────────────────────────────
bot_running = False
last_check: datetime = None


# ── Bankroll helper ────────────────────────────────────────────────────────────

def get_bankroll() -> float:
    """
    Ambil bankroll dari bot_settings.
    Kalau belum ada key 'bankroll', return default $1000.
    """
    try:
        val = config.get("bankroll", float)
        return val if val and val > 0 else 1000.0
    except Exception:
        return 1000.0


# ── DB check ───────────────────────────────────────────────────────────────────

def check_db_connection() -> bool:
    """Verifikasi koneksi database sebelum bot jalan."""
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
                cur.execute("SELECT COUNT(*) FROM bot_settings")
                count = cur.fetchone()[0]
        logger.info(f"✅ Database OK — {count} settings loaded")
        return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False


# ── Main scan loop ─────────────────────────────────────────────────────────────

def scan_for_opportunities():
    """
    Main bot loop — scan semua weather markets dan kirim alert.

    Flow yang benar:
      1. Fetch semua weather markets dari Polymarket
      2. Simpan markets ke DB (wajib, FK constraint)
      3. Simpan forecast ke DB
      4. Analisa opportunities
      5. Validasi dengan risk manager
      6. Simpan signal ke DB
      7. Kirim Telegram alert
      8. Eksekusi trade (jika full-auto)
    """
    global last_check

    logger.info("=" * 60)
    logger.info("🔍 SCANNING FOR WEATHER ARBITRAGE OPPORTUNITIES")
    logger.info(f"    Mode: {config.AUTOMATION_MODE()}")
    logger.info("=" * 60)

    try:
        bankroll      = get_bankroll()
        total_signals = 0

        # ── Step 1 & 2: Fetch + simpan semua weather markets ─────────────────
        logger.info("📡 Fetching weather markets dari Polymarket...")
        markets = polymarket.search_weather_markets()

        if not markets:
            logger.info("ℹ️  Tidak ada weather market aktif saat ini")
            return

        logger.info(f"💾 Menyimpan {len(markets)} markets ke DB...")
        polymarket.save_markets_to_db(markets)   # FIX: wajib sebelum insert signal

        # ── Step 3: Simpan forecast untuk semua lokasi unik ───────────────────
        locations = set()
        for m in markets:
            loc = None
            if m.get("type") == "bracket":
                loc = polymarket.extract_location_from_question(m.get("title", ""))
            else:
                loc = polymarket.extract_location_from_question(m.get("question", ""))
            if loc:
                locations.add(loc)

        logger.info(f"🌤️  Menyimpan forecast untuk {len(locations)} lokasi...")
        tomorrow = (datetime.now(timezone.utc).date())
        for loc in locations:
            try:
                noaa.save_forecast_to_db(loc, str(tomorrow))
            except Exception as e:
                logger.warning(f"⚠️  Gagal simpan forecast {loc}: {e}")

        # ── Step 4: Analisa opportunities ─────────────────────────────────────
        logger.info("🧠 Menganalisa opportunities...")
        signals = weather_analyzer.find_opportunities()

        if not signals:
            logger.info("ℹ️  Tidak ada signal yang memenuhi kriteria")
            last_check = datetime.now(timezone.utc)
            return

        logger.info(f"📊 Ditemukan {len(signals)} signal kandidat")

        for signal in signals:
            try:
                # ── Step 5: Validasi ─────────────────────────────────────────
                is_valid, reason = risk_mgr.validate_signal(signal, bankroll)  # FIX: tambah bankroll

                if not is_valid:
                    logger.info(f"⏭️  Skip: {reason} — {signal.get('market_question','')[:50]}")
                    continue

                # Hitung bet size
                bet_size = risk_mgr.calculate_position_size(signal, bankroll)
                signal["recommended_bet"] = bet_size

                # ── Step 6: Simpan signal ke DB ───────────────────────────────
                signal_id = risk_mgr.record_signal(signal, bet_size)
                if not signal_id:
                    logger.error("❌ Gagal simpan signal ke DB — skip")
                    continue

                # ── Step 7: Kirim Telegram alert ──────────────────────────────
                telegram.send_signal_alert(signal)
                total_signals += 1

                logger.info(
                    f"✅ Signal #{signal_id}: {signal.get('direction')} "
                    f"edge={signal.get('edge')}% "
                    f"bet=${bet_size:.2f} "
                    f"— {signal.get('market_question','')[:50]}"
                )

                # ── Step 8: Eksekusi trade (full-auto saja) ───────────────────
                if config.AUTOMATION_MODE() == "full-auto":
                    trade_result = trader.execute_trade(signal, signal_id, bet_size)
                    if trade_result:
                        risk_mgr.record_trade(
                            signal      = signal,
                            signal_id   = signal_id,
                            amount      = bet_size,
                            entry_price = signal.get("current_price", 0.5),
                            tx_hash     = trade_result.get("tx_hash"),
                        )
                        position_tracker.add_position(trade_result)
                        telegram.send_execution_confirmation(trade_result)

            except Exception as e:
                logger.error(f"❌ Error processing signal: {e}", exc_info=True)
                continue

        last_check = datetime.now(timezone.utc)

        # Update daily performance di akhir scan
        position_tracker.save_daily_performance()

        logger.info("=" * 60)
        logger.info(f"✅ Scan selesai — {total_signals} signal dikirim")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ Error scan_for_opportunities: {e}", exc_info=True)
        telegram.send_error_alert(f"❌ Bot error saat scanning:\n{str(e)[:200]}")


def reset_daily_at_midnight():
    """Reset daily limits di tengah malam."""
    logger.info("🔄 Midnight reset: daily limits direset")
    risk_mgr.reset_daily_limits()
    position_tracker.save_daily_performance()


# ── Flask routes ───────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    """Health check endpoint untuk monitoring."""
    db_ok = check_db_connection()
    return jsonify({
        "status":       "healthy" if db_ok else "degraded",
        "bot_running":  bot_running,
        "last_check":   last_check.isoformat() if last_check else None,
        "database":     "connected" if db_ok else "disconnected",
        "mode":         config.AUTOMATION_MODE(),
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }), 200 if db_ok else 503


@app.route("/api/trigger-scan")
def trigger_scan():
    """Manual trigger scan untuk testing."""
    scan_for_opportunities()
    return jsonify({"status": "scan triggered", "timestamp": datetime.now(timezone.utc).isoformat()}), 200


@app.route("/api/status")
def status():
    """Status bot dan statistik hari ini."""
    stats = risk_mgr.get_daily_stats()
    perf  = position_tracker.get_performance_stats()
    return jsonify({
        "bot_running":  bot_running,
        "mode":         config.AUTOMATION_MODE(),
        "last_check":   last_check.isoformat() if last_check else None,
        "daily_stats":  stats,
        "performance":  perf,
        "trader":       trader.get_status(),
    }), 200


@app.route("/api/reload-settings")
def reload_settings():
    """Hot-reload settings dari database tanpa restart bot."""
    config.load_settings_from_db()
    return jsonify({"status": "settings reloaded", "settings": config._settings}), 200


# ── Startup ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("🌧️  WEATHER TRADING BOT STARTING")
    logger.info("=" * 60)

    try:
        # 1. Cek database
        logger.info("🗄️  Checking database connection...")
        if not check_db_connection():
            logger.error("❌ Database tidak bisa diakses — pastikan MySQL running")
            sys.exit(1)

        # 2. Load settings dari DB
        logger.info("⚙️  Loading settings from database...")
        config.load_settings_from_db()

        # 3. Validasi config
        config.validate_config()

        # 4. Test Telegram
        logger.info("📱 Testing Telegram connection...")
        if telegram.test_connection():
            logger.info("✅ Telegram connected")
        else:
            logger.warning("⚠️  Telegram gagal — alerts dinonaktifkan")

        # 5. Start scheduler
        logger.info("⏰ Starting scheduler...")
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler()

        # Scan berkala
        scheduler.add_job(
            func      = scan_for_opportunities,
            trigger   = "interval",
            seconds   = config.CHECK_INTERVAL_SECONDS(),   # FIX: function call
            id        = "weather_scan",
            name      = "Weather Arbitrage Scanner",
        )

        # Reset harian jam 00:00
        scheduler.add_job(
            func    = reset_daily_at_midnight,
            trigger = "cron",
            hour    = 0,
            minute  = 0,
            id      = "daily_reset",
            name    = "Daily Reset",
        )

        scheduler.start()
        bot_running = True

        logger.info("=" * 60)
        logger.info(f"✅ Bot running!")
        logger.info(f"   Mode          : {config.AUTOMATION_MODE()}")         # FIX: ()
        logger.info(f"   Scan interval : setiap {config.CHECK_INTERVAL_MINUTES()} menit")
        logger.info(f"   Min edge      : {config.MIN_EDGE_PCT()}%")
        logger.info(f"   Dashboard     : http://localhost:{config.FLASK_PORT}")
        logger.info(f"   Database      : {config.DB_NAME}@{config.DB_HOST}")
        logger.info("=" * 60)

        # 6. Scan pertama di background (non-blocking agar Flask start dulu)
        from datetime import timedelta
        scheduler.add_job(
            func     = scan_for_opportunities,
            trigger  = "date",
            run_date = datetime.now(timezone.utc) + timedelta(seconds=5),
            id       = "initial_scan",
            name     = "Initial Scan",
        )
        logger.info("🚀 Initial scan dijadwalkan 5 detik setelah Flask start")

        # 7. Start Flask
        logger.info("🌐 Starting Flask web server...")
        app.run(
            host  = "0.0.0.0",
            port  = config.FLASK_PORT,
            debug = config.FLASK_DEBUG,
        )

    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Startup error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if "scheduler" in locals() and scheduler.running:
            scheduler.shutdown()
            logger.info("⏹️  Scheduler stopped")