"""
SQLAlchemy Database Models
"""

from database import db
from datetime import datetime

class Market(db.Model):
    """Polymarket markets"""
    __tablename__ = 'markets'
    
    id = db.Column(db.String(100), primary_key=True)
    question = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50))
    end_date = db.Column(db.DateTime)
    volume = db.Column(db.Float, default=0)
    liquidity = db.Column(db.Float, default=0)
    url = db.Column(db.String(500))
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_checked = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Market {self.id}: {self.question[:50]}...>'

class WeatherForecast(db.Model):
    """NOAA weather forecasts"""
    __tablename__ = 'weather_forecasts'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    location = db.Column(db.String(100), nullable=False)
    target_date = db.Column(db.Date, nullable=False)
    rain_probability = db.Column(db.Float)
    temperature_high = db.Column(db.Float)
    temperature_low = db.Column(db.Float)
    conditions = db.Column(db.String(200))
    detailed = db.Column(db.Text)
    source = db.Column(db.String(50), default='NOAA')
    retrieved_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Forecast {self.location} {self.target_date}: {self.rain_probability}% rain>'

class Signal(db.Model):
    """Trading signals generated"""
    __tablename__ = 'signals'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    market_id = db.Column(db.String(100), db.ForeignKey('markets.id'))
    location = db.Column(db.String(100))
    target_date = db.Column(db.Date)
    signal_type = db.Column(db.String(50))
    direction = db.Column(db.String(10))
    noaa_probability = db.Column(db.Float)
    market_probability = db.Column(db.Float)
    edge = db.Column(db.Float)
    confidence = db.Column(db.Float)
    fair_value = db.Column(db.Float)
    expected_value = db.Column(db.Float)
    recommended_bet = db.Column(db.Float)
    reasoning = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, executed, skipped
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    market = db.relationship('Market', backref='signals')
    
    def __repr__(self):
        return f'<Signal {self.id}: {self.location} {self.edge:.1f}% edge>'

class Trade(db.Model):
    """Executed trades"""
    __tablename__ = 'trades'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    trade_id = db.Column(db.String(100), unique=True, nullable=False)
    signal_id = db.Column(db.Integer, db.ForeignKey('signals.id'))
    market_id = db.Column(db.String(100), db.ForeignKey('markets.id'))
    direction = db.Column(db.String(10))
    bet_size = db.Column(db.Float)
    entry_price = db.Column(db.Float)
    shares = db.Column(db.Float)
    executed_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='open')  # open, closed
    outcome = db.Column(db.String(10))  # win, loss, pending
    payout = db.Column(db.Float)
    realized_pnl = db.Column(db.Float)
    closed_at = db.Column(db.DateTime)
    tx_hash = db.Column(db.String(100))
    
    # Relationships
    signal = db.relationship('Signal', backref='trades')
    market = db.relationship('Market', backref='trades')
    
    def __repr__(self):
        return f'<Trade {self.trade_id}: ${self.bet_size} {self.direction}>'

class DailyPerformance(db.Model):
    """Daily performance summary"""
    __tablename__ = 'daily_performance'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    total_trades = db.Column(db.Integer, default=0)
    wins = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0)
    total_invested = db.Column(db.Float, default=0)
    total_returned = db.Column(db.Float, default=0)
    realized_pnl = db.Column(db.Float, default=0)
    roi = db.Column(db.Float, default=0)
    
    def __repr__(self):
        return f'<DailyPerf {self.date}: {self.total_trades} trades, {self.win_rate:.1f}% WR>'

class BotSetting(db.Model):
    """Bot configuration settings"""
    __tablename__ = 'bot_settings'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False)
    setting_value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Setting {self.setting_key}: {self.setting_value}>'
