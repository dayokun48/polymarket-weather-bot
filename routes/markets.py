"""
Markets Route — updated with hours_left display
"""
from flask import Blueprint, render_template, request
from datetime import datetime, timezone
import pymysql
import config

markets_bp = Blueprint('markets', __name__)


def _get_conn():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
        database=config.DB_NAME, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
    )


@markets_bp.route('/markets')
def list_markets():
    search   = request.args.get('search', '')
    sort     = request.args.get('sort', 'end_date')
    page     = int(request.args.get('page', 1))
    per_page = 50
    offset   = (page - 1) * per_page
    now      = datetime.now(timezone.utc)

    markets   = []
    total     = 0
    total_vol = 0.0
    total_liq = 0.0

    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                # Simple filter — no timezone issues
                if search:
                    where_str = "WHERE question LIKE %s"
                    args      = [f"%{search}%"]
                    count_args = args
                else:
                    where_str  = ""
                    args       = []
                    count_args = []

                order = {
                    "end_date":  "end_date ASC",
                    "volume":    "volume DESC",
                    "liquidity": "liquidity DESC",
                    "newest":    "first_seen DESC",
                }.get(sort, "end_date ASC")

                cur.execute(f"SELECT COUNT(*) as cnt FROM markets {where_str}", count_args)
                total = cur.fetchone()["cnt"]

                cur.execute(f"""
                    SELECT SUM(volume) as tv, SUM(liquidity) as tl
                    FROM markets {where_str}
                """, count_args)
                row = cur.fetchone()
                total_vol = float(row["tv"] or 0)
                total_liq = float(row["tl"] or 0)

                cur.execute(f"""
                    SELECT id, question, end_date, volume, liquidity, url,
                           TIMESTAMPDIFF(HOUR, NOW(), end_date) as hours_left
                    FROM markets {where_str}
                    ORDER BY {order}
                    LIMIT %s OFFSET %s
                """, count_args + [per_page, offset])
                markets = cur.fetchall()

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Markets DB error: {e}")

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template('markets.html',
        markets     = markets,
        search      = search,
        sort        = sort,
        page        = page,
        total_pages = total_pages,
        total       = total,
        total_vol   = total_vol,
        total_liq   = total_liq,
        per_page    = per_page,
        now         = now,
    )