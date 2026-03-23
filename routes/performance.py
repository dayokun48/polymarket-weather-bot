"""
Performance Route
"""

from flask import Blueprint, render_template
from database import db, DailyPerformance, Trade
from datetime import datetime, timedelta

performance_bp = Blueprint('performance', __name__)

@performance_bp.route('/performance')
def show_performance():
    """Performance analytics"""
    
    # Get last 30 days performance
    thirty_days_ago = datetime.now().date() - timedelta(days=30)
    daily_stats = DailyPerformance.query.filter(
        DailyPerformance.date >= thirty_days_ago
    ).order_by(DailyPerformance.date.desc()).all()
    
    # Get all closed trades for analysis
    all_trades = Trade.query.filter_by(status='closed').all()
    
    # Overall stats
    total_trades = len(all_trades)
    wins = len([t for t in all_trades if t.outcome == 'WIN'])
    losses = len([t for t in all_trades if t.outcome == 'LOSS'])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    total_invested = sum(t.bet_size for t in all_trades)
    total_returned = sum(t.payout or 0 for t in all_trades)
    total_pnl = sum(t.realized_pnl or 0 for t in all_trades)
    roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0
    
    # Best and worst trades
    best_trade = max(all_trades, key=lambda t: t.realized_pnl or 0) if all_trades else None
    worst_trade = min(all_trades, key=lambda t: t.realized_pnl or 0) if all_trades else None
    
    # Average trade size
    avg_trade_size = total_invested / total_trades if total_trades > 0 else 0
    
    # Prepare chart data
    chart_dates = [d.date.strftime('%Y-%m-%d') for d in reversed(daily_stats)]
    chart_pnl = [d.realized_pnl for d in reversed(daily_stats)]
    chart_winrate = [d.win_rate for d in reversed(daily_stats)]
    
    return render_template('performance.html',
                         daily_stats=daily_stats,
                         total_trades=total_trades,
                         wins=wins,
                         losses=losses,
                         win_rate=win_rate,
                         total_invested=total_invested,
                         total_returned=total_returned,
                         total_pnl=total_pnl,
                         roi=roi,
                         best_trade=best_trade,
                         worst_trade=worst_trade,
                         avg_trade_size=avg_trade_size,
                         chart_dates=chart_dates,
                         chart_pnl=chart_pnl,
                         chart_winrate=chart_winrate)
