"""
Markets Route
"""
from flask import Blueprint, render_template, request
from datetime import datetime
import pymysql
import config

markets_bp = Blueprint('markets', __name__)


def _get_conn():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


@markets_bp.route('/markets')
def list_markets():
    search    = request.args.get('search', '')
    sort      = request.args.get('sort', 'volume')
    page      = int(request.args.get('page', 1))
    per_page  = 50
    offset    = (page - 1) * per_page

    markets   = []
    total     = 0
    total_vol = 0.0
    total_liq = 0.0

    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:

                # Build WHERE clause
                where = "WHERE 1=1"
                args  = []
                if search:
                    where += " AND question LIKE %s"
                    args.append(f"%{search}%")

                # Sort options
                order = {
                    "volume":    "volume DESC",
                    "liquidity": "liquidity DESC",
                    "end_date":  "end_date ASC",
                    "newest":    "first_seen DESC",
                }.get(sort, "volume DESC")

                # Total count
                cur.execute(f"SELECT COUNT(*) as cnt FROM markets {where}", args)
                total = cur.fetchone()["cnt"]

                # Summary stats
                cur.execute(f"""
                    SELECT SUM(volume) as tv, SUM(liquidity) as tl
                    FROM markets {where}
                """, args)
                row = cur.fetchone()
                total_vol = float(row["tv"] or 0)
                total_liq = float(row["tl"] or 0)

                # Paginated results
                cur.execute(f"""
                    SELECT id, question, category, end_date,
                           volume, liquidity, url, last_checked
                    FROM markets
                    {where}
                    ORDER BY {order}
                    LIMIT %s OFFSET %s
                """, args + [per_page, offset])
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
    )