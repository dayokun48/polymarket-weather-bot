"""
Performance Route — updated to match performance.html template variables
"""
from flask import Blueprint, render_template
from datetime import datetime, date, timedelta, timezone
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
    today           = date.today()
    thirty_days_ago = today - timedelta(days=30)

    # Defaults
    daily_performance = []
    best_trades       = []
    worst_trades      = []
    total_trades      = wins = losses = 0
    win_rate          = total_pnl = today_pnl = avg_bet_size = max_drawdown = 0.0
    today_trades      = 0

    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:

                # Daily performance (last 30 days)
                cur.execute("""
                    SELECT * FROM daily_performance
                    WHERE date >= %s ORDER BY date DESC
                """, (thirty_days_ago,))
                daily_performance = cur.fetchall()

                # All closed trades
                cur.execute("""
                    SELECT t.*, m.question as market_question
                    FROM trades t
                    LEFT JOIN markets m ON t.market_id = m.id
                    WHERE t.status = 'closed'
                    ORDER BY t.executed_at DESC
                """)
                all_trades = cur.fetchall()

                # Today trades
                cur.execute("""
                    SELECT COUNT(*) as cnt,
                           COALESCE(SUM(realized_pnl), 0) as pnl
                    FROM trades
                    WHERE DATE(executed_at) = %s
                """, (today,))
                row = cur.fetchone()
                today_trades = int(row["cnt"] or 0)
                today_pnl    = float(row["pnl"] or 0)

        # Stats
        total_trades = len(all_trades)
        wins         = sum(1 for t in all_trades if (t.get("outcome") or "").lower() == "win")
        losses       = sum(1 for t in all_trades if (t.get("outcome") or "").lower() == "loss")
        win_rate     = (wins / total_trades * 100) if total_trades > 0 else 0.0
        total_pnl    = sum(float(t.get("realized_pnl") or 0) for t in all_trades)
        total_bets   = sum(float(t.get("bet_size") or 0) for t in all_trades)
        avg_bet_size = total_bets / total_trades if total_trades > 0 else 0.0

        # Max drawdown — largest single loss
        losses_list  = [float(t.get("realized_pnl") or 0) for t in all_trades if (t.get("realized_pnl") or 0) < 0]
        max_drawdown = abs(min(losses_list)) if losses_list else 0.0

        # Best and worst trades
        closed_with_pnl = [t for t in all_trades if t.get("realized_pnl") is not None]
        best_trades  = sorted(closed_with_pnl, key=lambda t: float(t.get("realized_pnl") or 0), reverse=True)[:5]
        worst_trades = sorted(closed_with_pnl, key=lambda t: float(t.get("realized_pnl") or 0))[:5]

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Performance DB error: {e}")

    return render_template('performance.html',
        daily_performance = daily_performance,
        best_trades       = best_trades,
        worst_trades      = worst_trades,
        total_trades      = total_trades,
        wins              = wins,
        losses            = losses,
        win_rate          = round(win_rate, 1),
        total_pnl         = round(total_pnl, 2),
        today_pnl         = round(today_pnl, 2),
        today_trades      = today_trades,
        avg_bet_size      = round(avg_bet_size, 2),
        max_drawdown      = round(max_drawdown, 2),
    )