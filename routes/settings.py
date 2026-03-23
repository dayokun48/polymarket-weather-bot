"""
Settings Route
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import db, BotSetting

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/settings', methods=['GET', 'POST'])
def manage_settings():
    """Bot settings management"""
    
    if request.method == 'POST':
        # Update settings
        automation_mode = request.form.get('automation_mode')
        min_edge = request.form.get('min_edge_pct')
        min_confidence = request.form.get('min_confidence_pct')
        max_bet = request.form.get('max_bet_pct')
        max_daily_trades = request.form.get('max_daily_trades')
        check_interval = request.form.get('check_interval_hours')
        
        # Update database
        settings_map = {
            'automation_mode': automation_mode,
            'min_edge_pct': min_edge,
            'min_confidence_pct': min_confidence,
            'max_bet_pct': max_bet,
            'max_daily_trades': max_daily_trades,
            'check_interval_hours': check_interval
        }
        
        for key, value in settings_map.items():
            setting = BotSetting.query.filter_by(setting_key=key).first()
            if setting:
                setting.setting_value = value
            else:
                setting = BotSetting(setting_key=key, setting_value=value)
                db.session.add(setting)
        
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings.manage_settings'))
    
    # GET request - load current settings
    settings = {}
    for setting in BotSetting.query.all():
        settings[setting.setting_key] = setting.setting_value
    
    return render_template('settings.html', settings=settings)
