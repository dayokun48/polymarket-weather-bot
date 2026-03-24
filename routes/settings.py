"""
Settings Route
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
import pymysql
import config

settings_bp = Blueprint('settings', __name__)


def _get_conn():
    return pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


@settings_bp.route('/settings', methods=['GET', 'POST'])
def manage_settings():
    if request.method == 'POST':
        # FIX: key names sesuai database (check_interval_minutes, bukan check_interval_hours)
        settings_map = {
            'automation_mode':        request.form.get('automation_mode'),
            'min_edge_pct':           request.form.get('min_edge_pct'),
            'min_confidence_pct':     request.form.get('min_confidence_pct'),
            'max_bet_pct':            request.form.get('max_bet_pct'),
            'max_daily_trades':       request.form.get('max_daily_trades'),
            'max_daily_loss_pct':     request.form.get('max_daily_loss_pct'),
            'check_interval_minutes': request.form.get('check_interval_minutes'),
            'alert_cooldown_seconds': request.form.get('alert_cooldown_seconds'),
            'min_market_volume':      request.form.get('min_market_volume'),
            'min_market_liquidity':   request.form.get('min_market_liquidity'),
            'min_time_left_hours':    request.form.get('min_time_left_hours'),
            'max_time_left_hours':    request.form.get('max_time_left_hours'),
        }

        try:
            conn = _get_conn()
            with conn:
                with conn.cursor() as cur:
                    for key, value in settings_map.items():
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

            # Hot-reload settings ke memory
            config.load_settings_from_db()
            flash('Settings updated successfully!', 'success')

        except Exception as e:
            flash(f'Error updating settings: {e}', 'danger')

        return redirect(url_for('settings.manage_settings'))

    # GET — load settings dari DB
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