"""
Positions Route
"""
from flask import Blueprint, render_template
import pymysql
import config

positions_bp = Blueprint('positions', __name__)


def _get_conn():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


@positions_bp.route('/positions')
def list_positions():
    open_positions   = []
    closed_positions = []
    total_exposure   = 0.0
    wins = losses    = 0
    win_rate         = 0.0
    total_pnl        = 0.0

    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                # Open positions
                cur.execute("""
                    SELECT t.*, m.question as market_question
                    FROM trades t
                    LEFT JOIN markets m ON t.market_id = m.id
                    WHERE t.status = 'open'
                    ORDER BY t.executed_at DESC
                """)
                open_positions = cur.fetchall()

                # Closed positions last 30 — FIX: outcome 'win'/'loss' lowercase
                cur.execute("""
                    SELECT t.*, m.question as market_question
                    FROM trades t
                    LEFT JOIN markets m ON t.market_id = m.id
                    WHERE t.status = 'closed'
                    ORDER BY t.closed_at DESC
                    LIMIT 30
                """)
                closed_positions = cur.fetchall()

        total_exposure = sum(float(p.get("bet_size", 0)) for p in open_positions)
        wins           = sum(1 for p in closed_positions if p.get("outcome") == "win")
        losses         = sum(1 for p in closed_positions if p.get("outcome") == "loss")
        total_closed   = len(closed_positions)
        win_rate       = (wins / total_closed * 100) if total_closed > 0 else 0
        total_pnl      = sum(float(p.get("realized_pnl", 0) or 0) for p in closed_positions)

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Positions DB error: {e}")

    return render_template('positions.html',
        open_positions   = open_positions,
        closed_positions = closed_positions,
        total_open       = len(open_positions),
        total_exposure   = round(total_exposure, 2),
        total_closed     = len(closed_positions),
        wins             = wins,
        losses           = losses,
        win_rate         = round(win_rate, 1),
        total_pnl        = round(total_pnl, 2),
    )