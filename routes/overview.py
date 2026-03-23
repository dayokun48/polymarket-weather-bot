"""
Overview/Dashboard Route
"""

from flask import Blueprint, render_template
from database import db, Signal, Trade, DailyPerformance
from datetime import datetime, timedelta

overview_bp = Blueprint('overview', __name__)

@overview_bp.route('/')
def index():
    """Main dashboard"""
    
    # Get today's stats
    today = datetime.now().date()
    today_perf = DailyPerformance.query.filter_by(date=today).first()
    
    # Get recent signals (last 24h)
    yesterday = datetime.now() - timedelta(days=1)
    recent_signals = Signal.query.filter(
        Signal.created_at >= yesterday
    ).order_by(Signal.created_at.desc()).limit(5).all()
    
    # Get open positions
    open_trades = Trade.query.filter_by(status='open').all()
    
    # Get recent trades
    recent_trades = Trade.query.order_by(
        Trade.executed_at.desc()
    ).limit(5).all()
    
    # Calculate stats
    total_signals_today = Signal.query.filter(
        Signal.created_at >= datetime.now().replace(hour=0, minute=0, second=0)
    ).count()
    
    total_open_positions = len(open_trades)
    total_exposure = sum(t.bet_size for t in open_trades)
    
    # Get all-time stats
    all_trades = Trade.query.filter_by(status='closed').all()
    total_trades = len(all_trades)
    wins = len([t for t in all_trades if t.outcome == 'WIN'])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    total_pnl = sum(t.realized_pnl or 0 for t in all_trades)
    
    return render_template('overview.html',
                         today_perf=today_perf,
                         recent_signals=recent_signals,
                         open_trades=open_trades,
                         recent_trades=recent_trades,
                         total_signals_today=total_signals_today,
                         total_open_positions=total_open_positions,
                         total_exposure=total_exposure,
                         total_trades=total_trades,
                         win_rate=win_rate,
                         total_pnl=total_pnl)
