"""
Overview/Dashboard Route
"""
from flask import Blueprint, render_template
from datetime import datetime, timedelta
import pymysql
import config

overview_bp = Blueprint('overview', __name__)


def _get_conn():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


@overview_bp.route('/')
def index():
    today     = datetime.now().date()
    yesterday = datetime.now() - timedelta(days=1)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    today_perf         = None
    recent_signals     = []
    open_trades        = []
    recent_trades      = []
    total_signals_today = 0
    total_exposure     = 0.0
    total_trades       = 0
    wins               = 0
    win_rate           = 0.0
    total_pnl          = 0.0

    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                # Today's performance
                cur.execute("SELECT * FROM daily_performance WHERE date = %s", (today,))
                today_perf = cur.fetchone()

                # Recent signals last 24h
                cur.execute("""
                    SELECT s.*, m.question as market_question
                    FROM signals s
                    LEFT JOIN markets m ON s.market_id = m.id
                    WHERE s.created_at >= %s
                    ORDER BY s.created_at DESC LIMIT 5
                """, (yesterday,))
                recent_signals = cur.fetchall()

                # Open trades
                cur.execute("""
                    SELECT t.*, m.question as market_question
                    FROM trades t
                    LEFT JOIN markets m ON t.market_id = m.id
                    WHERE t.status = 'open'
                """)
                open_trades = cur.fetchall()

                # Recent trades
                cur.execute("""
                    SELECT t.*, m.question as market_question
                    FROM trades t
                    LEFT JOIN markets m ON t.market_id = m.id
                    ORDER BY t.executed_at DESC LIMIT 5
                """)
                recent_trades = cur.fetchall()

                # Signals today
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM signals WHERE created_at >= %s",
                    (today_start,)
                )
                total_signals_today = cur.fetchone()["cnt"]

                # All-time closed stats — FIX: outcome 'win' lowercase
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(outcome = 'win') as wins,
                        SUM(realized_pnl) as total_pnl
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
        today_perf          = today_perf,
        recent_signals      = recent_signals,
        open_trades         = open_trades,
        recent_trades       = recent_trades,
        total_signals_today = total_signals_today,
        total_open_positions = len(open_trades),
        total_exposure      = total_exposure,
        total_trades        = total_trades,
        win_rate            = round(win_rate, 1),
        total_pnl           = round(total_pnl, 2),
    )