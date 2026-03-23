"""
Signals Route
"""

from flask import Blueprint, render_template, request
from database import db, Signal
from datetime import datetime, timedelta

signals_bp = Blueprint('signals', __name__)

@signals_bp.route('/signals')
def list_signals():
    """List all trading signals"""
    
    # Get filter parameters
    status = request.args.get('status', 'all')
    days = int(request.args.get('days', 7))
    
    # Build query
    query = Signal.query
    
    # Filter by status
    if status != 'all':
        query = query.filter_by(status=status)
    
    # Filter by date
    cutoff_date = datetime.now() - timedelta(days=days)
    query = query.filter(Signal.created_at >= cutoff_date)
    
    # Order by created date
    signals = query.order_by(Signal.created_at.desc()).all()
    
    # Calculate stats
    total_signals = len(signals)
    pending_signals = len([s for s in signals if s.status == 'pending'])
    executed_signals = len([s for s in signals if s.status == 'executed'])
    skipped_signals = len([s for s in signals if s.status == 'skipped'])
    avg_edge = sum(s.edge for s in signals) / total_signals if total_signals > 0 else 0
    avg_confidence = sum(s.confidence for s in signals) / total_signals if total_signals > 0 else 0
    
    return render_template('signals.html',
                         signals=signals,
                         status_filter=status,
                         days_filter=days,
                         total_signals=total_signals,
                         pending_signals=pending_signals,
                         executed_signals=executed_signals,
                         skipped_signals=skipped_signals,
                         avg_edge=avg_edge,
                         avg_confidence=avg_confidence)
