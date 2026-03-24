"""
Performance Route
"""
from flask import Blueprint, render_template
from datetime import datetime, timedelta
import pymysql
import config

performance_bp = Blueprint('performance', __name__)


def _get_conn():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


@performance_bp.route('/performance')
def show_performance():
    thirty_days_ago = datetime.now().date() - timedelta(days=30)

    daily_stats    = []
    all_trades     = []
    total_trades   = 0
    wins = losses  = 0
    win_rate       = 0.0
    total_invested = total_returned = total_pnl = roi = 0.0
    best_trade = worst_trade = None
    avg_trade_size = 0.0
    chart_dates = chart_pnl = chart_winrate = []

    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                # Last 30 days daily performance
                cur.execute("""
                    SELECT * FROM daily_performance
                    WHERE date >= %s
                    ORDER BY date DESC
                """, (thirty_days_ago,))
                daily_stats = cur.fetchall()

                # All closed trades — FIX: outcome 'win'/'loss' lowercase
                cur.execute("""
                    SELECT t.*, m.question as market_question
                    FROM trades t
                    LEFT JOIN markets m ON t.market_id = m.id
                    WHERE t.status = 'closed'
                    ORDER BY t.executed_at DESC
                """)
                all_trades = cur.fetchall()

        total_trades   = len(all_trades)
        wins           = sum(1 for t in all_trades if t.get("outcome") == "win")
        losses         = sum(1 for t in all_trades if t.get("outcome") == "loss")
        win_rate       = (wins / total_trades * 100) if total_trades > 0 else 0
        total_invested = sum(float(t.get("bet_size", 0)) for t in all_trades)
        total_returned = sum(float(t.get("payout", 0) or 0) for t in all_trades)
        total_pnl      = sum(float(t.get("realized_pnl", 0) or 0) for t in all_trades)
        roi            = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        avg_trade_size = total_invested / total_trades if total_trades > 0 else 0

        if all_trades:
            best_trade  = max(all_trades, key=lambda t: float(t.get("realized_pnl", 0) or 0))
            worst_trade = min(all_trades, key=lambda t: float(t.get("realized_pnl", 0) or 0))

        chart_dates   = [str(d["date"]) for d in reversed(daily_stats)]
        chart_pnl     = [float(d.get("realized_pnl", 0) or 0) for d in reversed(daily_stats)]
        chart_winrate = [float(d.get("win_rate", 0) or 0) for d in reversed(daily_stats)]

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Performance DB error: {e}")

    return render_template('performance.html',
        daily_stats    = daily_stats,
        total_trades   = total_trades,
        wins           = wins,
        losses         = losses,
        win_rate       = round(win_rate, 1),
        total_invested = round(total_invested, 2),
        total_returned = round(total_returned, 2),
        total_pnl      = round(total_pnl, 2),
        roi            = round(roi, 1),
        best_trade     = best_trade,
        worst_trade    = worst_trade,
        avg_trade_size = round(avg_trade_size, 2),
        chart_dates    = chart_dates,
        chart_pnl      = chart_pnl,
        chart_winrate  = chart_winrate,
    )