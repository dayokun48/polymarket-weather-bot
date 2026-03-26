"""
Settings Route — updated for volume-based strategy
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
import pymysql
import config

settings_bp = Blueprint('settings', __name__)


def _get_conn():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
        database=config.DB_NAME, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
    )


SETTINGS_MAP = {
    # ── Trading mode ──────────────────────────────────────────────────────────
    'automation_mode':            'select',
    'max_bet_pct':                'number',
    'max_daily_trades':           'number',
    'max_daily_loss_pct':         'number',
    'bankroll':                   'number',
    # ── Auto-trade ────────────────────────────────────────────────────────────
    'auto_trade_threshold':       'number',
    'auto_trade_amount':          'number',
    'alert_cooldown_seconds':     'number',
    # ── Fresh market ─────────────────────────────────────────────────────────
    'fresh_market_window_minutes':'number',
    'fresh_market_auto_bet':      'number',
    'fresh_market_scan_interval': 'number',
    # ── Volume strategy ───────────────────────────────────────────────────────
    'pre_closing_hours':          'number',
    'min_volume_signal':          'number',
    'volume_edge_threshold':      'number',
}


@settings_bp.route('/settings', methods=['GET', 'POST'])
def manage_settings():
    if request.method == 'POST':
        updates = {k: request.form.get(k) for k in SETTINGS_MAP}
        try:
            conn = _get_conn()
            with conn:
                with conn.cursor() as cur:
                    for key, value in updates.items():
                        if value is None:
                            continue
                        cur.execute("""
                            INSERT INTO bot_settings (setting_key, setting_value)
                            VALUES (%s, %s)
                            ON DUPLICATE KEY UPDATE
                                setting_value = VALUES(setting_value),
                                updated_at    = NOW()
                        """, (key, value))
                conn.commit()
            config.load_settings_from_db()
            flash('Settings saved!', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'danger')
        return redirect(url_for('settings.manage_settings'))

    settings = {}
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT setting_key, setting_value FROM bot_settings")
                for row in cur.fetchall():
                    settings[row["setting_key"]] = row["setting_value"]
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Settings DB error: {e}")

    return render_template('settings.html', settings=settings)