"""Overview Route — simplified"""
from flask import Blueprint, render_template
from datetime import datetime, date
import pymysql
import config

overview_bp = Blueprint('overview', __name__)

def _get_conn():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
        database=config.DB_NAME, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
    )

@overview_bp.route('/')
def index():
    today       = date.today()
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    recent_signals = []
    stats = {"total":0,"executed":0,"pending":0,"skipped":0,"avg_edge":0,"avg_conf":0}

    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, location, direction, signal_type, edge,
                           confidence, status, created_at, reasoning
                    FROM signals WHERE DATE(created_at) = %s
                    ORDER BY created_at DESC LIMIT 20
                """, (today,))
                recent_signals = cur.fetchall()

                cur.execute("""
                    SELECT COUNT(*) as total,
                           SUM(status='executed') as executed,
                           SUM(status='pending') as pending,
                           SUM(status='skipped') as skipped,
                           ROUND(AVG(edge),1) as avg_edge,
                           ROUND(AVG(confidence),1) as avg_conf
                    FROM signals WHERE DATE(created_at) = %s
                """, (today,))
                row = cur.fetchone()
                if row: stats = row
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Overview error: {e}")

    from executors.polymarket_trader import PolymarketTrader
    try:
        trader  = PolymarketTrader()
        balance = trader.get_balance()
        clob_ok = trader.is_ready()
    except:
        balance = 0.0
        clob_ok = False

    return render_template('overview.html',
        today           = today,
        recent_signals  = recent_signals,
        stats           = stats,
        balance         = balance,
        clob_ok         = clob_ok,
        automation_mode = config.AUTOMATION_MODE(),
        auto_threshold  = config.AUTO_TRADE_THRESHOLD(),
        auto_amount     = config.AUTO_TRADE_AMOUNT(),
        fresh_bet       = config.FRESH_MARKET_AUTO_BET(),
        pre_closing_h   = config.PRE_CLOSING_HOURS(),
        fresh_interval  = config.FRESH_MARKET_SCAN_INTERVAL(),
    )