"""
Signals Route — updated for volume-based strategy
"""
from flask import Blueprint, render_template, request
from datetime import datetime, timedelta
import pymysql
import config

signals_bp = Blueprint('signals', __name__)


def _get_conn():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
        database=config.DB_NAME, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
    )


@signals_bp.route('/signals')
def list_signals():
    status_filter = request.args.get('status', 'all')
    days          = int(request.args.get('days', 1))
    signal_type   = request.args.get('type', 'all')
    cutoff        = datetime.now() - timedelta(days=days)

    signals = []

    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                where = ["s.created_at >= %s"]
                args  = [cutoff]

                if status_filter != 'all':
                    where.append("s.status = %s")
                    args.append(status_filter)

                if signal_type == 'fresh':
                    where.append("s.signal_type = 'fresh_market_bracket'")
                elif signal_type == 'volume':
                    where.append("s.signal_type = 'volume_distribution'")

                cur.execute(f"""
                    SELECT s.*, m.question as market_question, m.url as market_url
                    FROM signals s
                    LEFT JOIN markets m ON s.market_id = m.id
                    WHERE {' AND '.join(where)}
                    ORDER BY s.created_at DESC
                    LIMIT 100
                """, args)
                signals = cur.fetchall()

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Signals DB error: {e}")

    total_signals    = len(signals)
    pending_signals  = sum(1 for s in signals if s.get("status") == "pending")
    executed_signals = sum(1 for s in signals if s.get("status") == "executed")
    skipped_signals  = sum(1 for s in signals if s.get("status") == "skipped")
    fresh_signals    = sum(1 for s in signals if s.get("signal_type") == "fresh_market_bracket")
    volume_signals   = sum(1 for s in signals if s.get("signal_type") == "volume_distribution")
    avg_edge         = (
        sum(float(s.get("edge", 0)) for s in signals) / total_signals
        if total_signals > 0 else 0
    )
    avg_confidence   = (
        sum(float(s.get("confidence", 0)) for s in signals) / total_signals
        if total_signals > 0 else 0
    )

    return render_template('signals.html',
        signals          = signals,
        status_filter    = status_filter,
        days_filter      = days,
        type_filter      = signal_type,
        total_signals    = total_signals,
        pending_signals  = pending_signals,
        executed_signals = executed_signals,
        skipped_signals  = skipped_signals,
        fresh_signals    = fresh_signals,
        volume_signals   = volume_signals,
        avg_edge         = round(avg_edge, 1),
        avg_confidence   = round(avg_confidence, 1),
    )