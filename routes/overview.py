"""
Overview/Dashboard Route — updated for volume-based strategy
"""
from flask import Blueprint, render_template
from datetime import datetime, timedelta, timezone
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
    today       = datetime.now().date()
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    today_perf              = None
    recent_signals          = []
    open_trades             = []
    total_signals_today     = 0
    fresh_signals_today     = 0
    volume_signals_today    = 0
    total_exposure          = 0.0
    total_trades            = wins = 0
    win_rate                = total_pnl = 0.0
    next_fresh_scan         = "~setiap 10 menit"
    next_pre_closing        = "06:00 & 08:00 UTC"

    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                # Today performance
                cur.execute("SELECT * FROM daily_performance WHERE date = %s", (today,))
                today_perf = cur.fetchone()

                # Recent signals 24h
                cur.execute("""
                    SELECT s.id, s.location, s.direction, s.edge, s.confidence,
                           s.signal_type, s.status, s.created_at,
                           s.reasoning, m.question as market_question
                    FROM signals s
                    LEFT JOIN markets m ON s.market_id = m.id
                    WHERE s.created_at >= %s
                    ORDER BY s.created_at DESC
                    LIMIT 10
                """, (today_start,))
                recent_signals = cur.fetchall()

                # Signal counts today
                cur.execute("SELECT COUNT(*) as cnt FROM signals WHERE created_at >= %s", (today_start,))
                total_signals_today = cur.fetchone()["cnt"]

                cur.execute("""
                    SELECT COUNT(*) as cnt FROM signals
                    WHERE created_at >= %s AND signal_type = 'fresh_market_bracket'
                """, (today_start,))
                fresh_signals_today = cur.fetchone()["cnt"]

                cur.execute("""
                    SELECT COUNT(*) as cnt FROM signals
                    WHERE created_at >= %s AND signal_type = 'volume_distribution'
                """, (today_start,))
                volume_signals_today = cur.fetchone()["cnt"]

                # Open trades
                cur.execute("""
                    SELECT t.*, m.question as market_question
                    FROM trades t LEFT JOIN markets m ON t.market_id = m.id
                    WHERE t.status = 'open'
                    ORDER BY t.executed_at DESC
                    LIMIT 10
                """)
                open_trades = cur.fetchall()

                # All-time stats
                cur.execute("""
                    SELECT COUNT(*) as total,
                           SUM(outcome = 'win') as wins,
                           COALESCE(SUM(realized_pnl), 0) as total_pnl
                    FROM trades WHERE status = 'closed'
                """)
                row = cur.fetchone()
                total_trades = int(row["total"] or 0)
                wins         = int(row["wins"] or 0)
                total_pnl    = float(row["total_pnl"] or 0)
                win_rate     = (wins / total_trades * 100) if total_trades > 0 else 0

        total_exposure = sum(float(t.get("bet_size", 0)) for t in open_trades)

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Overview DB error: {e}")

    return render_template('overview.html',
        today_perf           = today_perf,
        recent_signals       = recent_signals,
        open_trades          = open_trades,
        total_signals_today  = total_signals_today,
        fresh_signals_today  = fresh_signals_today,
        volume_signals_today = volume_signals_today,
        total_open_positions = len(open_trades),
        total_exposure       = total_exposure,
        total_trades         = total_trades,
        win_rate             = round(win_rate, 1),
        total_pnl            = round(total_pnl, 2),
        next_fresh_scan      = next_fresh_scan,
        next_pre_closing     = next_pre_closing,
        automation_mode      = config.AUTOMATION_MODE(),
        auto_threshold       = config.AUTO_TRADE_THRESHOLD(),
        auto_amount          = config.AUTO_TRADE_AMOUNT(),
        fresh_bet            = config.FRESH_MARKET_AUTO_BET(),
        pre_closing_hours    = config.PRE_CLOSING_HOURS(),
    )