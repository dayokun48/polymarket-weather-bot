"""
Positions Route
"""

from flask import Blueprint, render_template
from database import db, Trade

positions_bp = Blueprint('positions', __name__)

@positions_bp.route('/positions')
def list_positions():
    """List all trading positions"""
    
    # Get open positions
    open_positions = Trade.query.filter_by(status='open').order_by(
        Trade.executed_at.desc()
    ).all()
    
    # Get closed positions (last 30)
    closed_positions = Trade.query.filter_by(status='closed').order_by(
        Trade.closed_at.desc()
    ).limit(30).all()
    
    # Calculate metrics
    total_open = len(open_positions)
    total_exposure = sum(p.bet_size for p in open_positions)
    
    total_closed = len(closed_positions)
    wins = len([p for p in closed_positions if p.outcome == 'WIN'])
    losses = len([p for p in closed_positions if p.outcome == 'LOSS'])
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
    total_pnl = sum(p.realized_pnl or 0 for p in closed_positions)
    
    return render_template('positions.html',
                         open_positions=open_positions,
                         closed_positions=closed_positions,
                         total_open=total_open,
                         total_exposure=total_exposure,
                         total_closed=total_closed,
                         wins=wins,
                         losses=losses,
                         win_rate=win_rate,
                         total_pnl=total_pnl)
