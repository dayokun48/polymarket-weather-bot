"""
app.py
=======
Polymarket Weather Trading Bot — Main Application.

Perubahan dari original:
  - Hapus SQLAlchemy ORM (from database import db) — semua file pakai pymysql
  - Hapus save_market_to_db / save_forecast_to_db / save_signal_to_db yang duplikat
  - Fix risk_mgr.validate_signal() tambah parameter bankroll
  - Fix config.AUTOMATION_MODE → config.AUTOMATION_MODE() (function call)
  - Fix datetime.utcnow() → datetime.now(timezone.utc)
  - Tambah TelegramHandler untuk callback tombol EXECUTE/SKIP + commands
  - Tambah auto-trade: confidence >= auto_trade_threshold → eksekusi $auto_trade_amount
"""

import logging
import os
import sys
from datetime import datetime, date, timezone, timedelta

from flask import Flask, jsonify

import config

# ── Logging ────────────────────────────────────────────────────────────────────
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

# ── Flask ──────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = config.FLASK_SECRET_KEY

# ── Components ─────────────────────────────────────────────────────────────────
from collectors.noaa_collector          import NOAACollector
from collectors.polymarket_collector    import PolymarketCollector
from analyzers.weather_analyzer         import WeatherAnalyzer
from analyzers.arbitrage_calculator     import ArbitrageCalculator
from analyzers.risk_manager             import RiskManager
from executors.polymarket_trader        import PolymarketTrader
from executors.position_tracker         import PositionTracker
from notifications.telegram_bot         import TelegramBot
from notifications.telegram_handler     import TelegramHandler

noaa             = NOAACollector()
polymarket       = PolymarketCollector()
weather_analyzer = WeatherAnalyzer(noaa, polymarket)
arbitrage_calc   = ArbitrageCalculator()
risk_mgr         = RiskManager(arbitrage_calc)
telegram         = TelegramBot()
trader           = PolymarketTrader()
position_tracker = PositionTracker()
tg_handler: TelegramHandler = None   # diinit setelah scan_for_opportunities didefinisikan

# ── Routes ─────────────────────────────────────────────────────────────────────
try:
    from routes import register_routes
    register_routes(app)
    logger.info("✅ Routes registered")
except ImportError:
    logger.warning("⚠️  routes module tidak ditemukan — skip")

# ── Global state ───────────────────────────────────────────────────────────────
bot_running       = False
last_check: datetime = None


def get_bankroll() -> float:
    try:
        val = config.get("bankroll", float)
        return val if val and val > 0 else 1000.0
    except Exception:
        return 1000.0


def check_db_connection() -> bool:
    try:
        import pymysql
        conn = pymysql.connect(
            host=config.DB_HOST, port=config.DB_PORT,
            user=config.DB_USER, password=config.DB_PASSWORD,
            database=config.DB_NAME, charset="utf8mb4", connect_timeout=5,
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


# ── Main scan ──────────────────────────────────────────────────────────────────

def scan_for_opportunities():
    """
    Main bot loop.

    Routing signal berdasarkan confidence + mode:
      full-auto                              → eksekusi semua signal valid
      semi-auto + conf >= auto_threshold     → auto-execute $auto_trade_amount
      semi-auto + conf < auto_threshold      → kirim alert dengan tombol EXECUTE/SKIP
      manual                                 → hanya kirim alert, tidak eksekusi
    """
    global last_check

    logger.info("=" * 60)
    logger.info("🔍 SCANNING FOR WEATHER ARBITRAGE OPPORTUNITIES")
    logger.info(f"    Mode: {config.AUTOMATION_MODE()}")
    logger.info("=" * 60)

    try:
        bankroll          = get_bankroll()
        auto_threshold    = config.AUTO_TRADE_THRESHOLD()
        total_signals     = 0
        total_auto_trades = 0

        # Step 1: Fetch + simpan markets
        logger.info("📡 Fetching weather markets...")
        markets = polymarket.search_weather_markets()
        if not markets:
            logger.info("ℹ️  Tidak ada weather market aktif")
            return

        logger.info(f"💾 Saving {len(markets)} markets ke DB...")
        polymarket.save_markets_to_db(markets)

        # Step 2: Simpan forecast
        locations = set()
        for m in markets:
            q   = m.get("title", "") if m.get("type") == "bracket" else m.get("question", "")
            loc = polymarket.extract_location_from_question(q)
            if loc:
                locations.add(loc)

        logger.info(f"🌤️  Saving forecast untuk {len(locations)} lokasi...")
        tomorrow = str(datetime.now(timezone.utc).date())
        for loc in locations:
            try:
                noaa.save_forecast_to_db(loc, tomorrow)
            except Exception as e:
                logger.warning(f"⚠️  Gagal simpan forecast {loc}: {e}")

        # Step 3: Analisa
        logger.info("🧠 Analysing opportunities...")
        signals = weather_analyzer.find_opportunities()
        if not signals:
            logger.info("ℹ️  Tidak ada signal yang memenuhi kriteria")
            last_check = datetime.now(timezone.utc)
            return

        logger.info(f"📊 {len(signals)} signal kandidat ditemukan")

        for signal in signals:
            try:
                # Step 4: Validasi
                is_valid, reason = risk_mgr.validate_signal(signal, bankroll)
                if not is_valid:
                    logger.info(f"⏭️  Skip: {reason}")
                    continue

                bet_size = risk_mgr.calculate_position_size(signal, bankroll)
                signal["recommended_bet"] = bet_size

                # Step 5: Simpan signal ke DB
                signal_id = risk_mgr.record_signal(signal, bet_size)
                if not signal_id:
                    logger.error("❌ Gagal simpan signal — skip")
                    continue

                confidence = signal.get("confidence", 0)
                mode       = config.AUTOMATION_MODE()

                # Step 6: Routing
                if mode == "full-auto":
                    # Eksekusi langsung
                    trade_result = trader.execute_trade(signal, signal_id, bet_size)
                    if trade_result:
                        risk_mgr.record_trade(
                            signal=signal, signal_id=signal_id,
                            amount=bet_size,
                            entry_price=signal.get("current_price", 0.5),
                            tx_hash=trade_result.get("tx_hash"),
                        )
                        position_tracker.add_position(trade_result)
                        telegram.send_execution_confirmation(trade_result)
                    total_auto_trades += 1

                elif mode == "semi-auto" and confidence >= auto_threshold and tg_handler:
                    # Auto-execute dengan fixed amount
                    logger.info(
                        f"⚡ Auto-trade: conf={confidence:.0f}% >= {auto_threshold:.0f}%"
                        f" → ${config.AUTO_TRADE_AMOUNT()}"
                    )
                    tg_handler.auto_execute(signal, signal_id)
                    total_auto_trades += 1

                else:
                    # Kirim alert dengan tombol EXECUTE/SKIP
                    telegram.send_signal_alert(signal)

                total_signals += 1
                logger.info(
                    f"✅ Signal #{signal_id}: {signal.get('direction')} "
                    f"conf={confidence:.0f}% edge={signal.get('edge')}% "
                    f"bet=${bet_size:.2f}"
                )

            except Exception as e:
                logger.error(f"❌ Error processing signal: {e}", exc_info=True)
                continue

        last_check = datetime.now(timezone.utc)
        position_tracker.save_daily_performance()

        logger.info("=" * 60)
        logger.info(f"✅ Scan done — {total_signals} signals | {total_auto_trades} auto-trades")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ scan_for_opportunities error: {e}", exc_info=True)
        telegram.send_error_alert(f"❌ Bot error:\n{str(e)[:200]}")


def reset_daily_at_midnight():
    logger.info("🔄 Midnight reset")
    risk_mgr.reset_daily_limits()
    position_tracker.save_daily_performance()


# ── Flask API routes ───────────────────────────────────────────────────────────

@app.route("/health")
def health():
    db_ok = check_db_connection()
    return jsonify({
        "status":      "healthy" if db_ok else "degraded",
        "bot_running": bot_running,
        "last_check":  last_check.isoformat() if last_check else None,
        "database":    "connected" if db_ok else "disconnected",
        "mode":        config.AUTOMATION_MODE(),
        "clob_ready":  config.CLOB_IS_READY(),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }), 200 if db_ok else 503


@app.route("/api/trigger-scan")
def trigger_scan():
    scan_for_opportunities()
    return jsonify({"status": "scan triggered", "timestamp": datetime.now(timezone.utc).isoformat()}), 200


@app.route("/api/status")
def api_status():
    stats = risk_mgr.get_daily_stats()
    perf  = position_tracker.get_performance_stats()
    return jsonify({
        "bot_running":    bot_running,
        "mode":           config.AUTOMATION_MODE(),
        "last_check":     last_check.isoformat() if last_check else None,
        "auto_threshold": config.AUTO_TRADE_THRESHOLD(),
        "auto_amount":    config.AUTO_TRADE_AMOUNT(),
        "clob_ready":     config.CLOB_IS_READY(),
        "daily_stats":    stats,
        "performance":    perf,
        "trader":         trader.get_status(),
    }), 200


@app.route("/api/reload-settings")
def reload_settings():
    config.load_settings_from_db()
    return jsonify({"status": "settings reloaded", "settings": config._settings}), 200


# ── Startup ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":


    logger.info("=" * 60)
    logger.info("🌧️  WEATHER TRADING BOT STARTING")
    logger.info("=" * 60)

    try:
        # 1. Database
        logger.info("🗄️  Checking database...")
        if not check_db_connection():
            logger.error("❌ Database tidak bisa diakses")
            sys.exit(1)

        # 2. Load settings
        logger.info("⚙️  Loading settings...")
        config.load_settings_from_db()

        # 3. Validate config
        config.validate_config()

        # 4. Test Telegram
        logger.info("📱 Testing Telegram...")
        if telegram.test_connection():
            logger.info("✅ Telegram connected")
        else:
            logger.warning("⚠️  Telegram gagal")

        # 5. Start Telegram handler
        logger.info("🤖 Starting Telegram handler...")
        import sys as _sys; globals()["tg_handler"] = TelegramHandler(risk_mgr, trader, scan_for_opportunities)
        tg_handler.start()
        logger.info(
            f"✅ Telegram handler started\n"
            f"   Auto-trade threshold : {config.AUTO_TRADE_THRESHOLD():.0f}%\n"
            f"   Auto-trade amount    : ${config.AUTO_TRADE_AMOUNT():.0f}\n"
            f"   CLOB ready           : {'✅ Live trading' if config.CLOB_IS_READY() else '⚠️  Simulation mode'}"
        )

        # 6. Scheduler
        logger.info("⏰ Starting scheduler...")
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            func=scan_for_opportunities, trigger="interval",
            seconds=config.CHECK_INTERVAL_SECONDS(),
            id="weather_scan", name="Weather Scanner",
        )
        scheduler.add_job(
            func=reset_daily_at_midnight, trigger="cron",
            hour=0, minute=0, id="daily_reset", name="Daily Reset",
        )
        scheduler.start()
        globals()["bot_running"] = True

        logger.info("=" * 60)
        logger.info("✅ Bot running!")
        logger.info(f"   Mode       : {config.AUTOMATION_MODE()}")
        logger.info(f"   Interval   : {config.CHECK_INTERVAL_MINUTES()} menit")
        logger.info(f"   Min edge   : {config.MIN_EDGE_PCT()}%")
        logger.info(f"   Min conf   : {config.MIN_CONFIDENCE_PCT()}%")
        logger.info(f"   Auto-trade : conf ≥ {config.AUTO_TRADE_THRESHOLD():.0f}% → ${config.AUTO_TRADE_AMOUNT():.0f}")
        logger.info(f"   Dashboard  : http://localhost:{config.FLASK_PORT}")
        logger.info("=" * 60)

        # 7. Initial scan (5 detik setelah start)
        scheduler.add_job(
            func=scan_for_opportunities, trigger="date",
            run_date=datetime.now(timezone.utc) + timedelta(seconds=5),
            id="initial_scan", name="Initial Scan",
        )
        logger.info("🚀 Initial scan in 5 seconds...")

        # 8. Flask
        logger.info("🌐 Starting Flask...")
        app.run(host="0.0.0.0", port=config.FLASK_PORT, debug=config.FLASK_DEBUG)

    except ValueError as e:
        logger.error(f"❌ Config error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Startup error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if "scheduler" in locals() and scheduler.running:
            scheduler.shutdown()
            logger.info("⏹️  Scheduler stopped")
        if tg_handler:
            tg_handler.stop()