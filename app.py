"""
Polymarket Weather Trading Bot
Main Application - Full Integration
"""

import config
from flask import Flask
import logging
import sys
from datetime import datetime, date
from apscheduler.schedulers.background import BackgroundScheduler

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = f"mysql://{config.DB_USER}:{config.DB_PASSWORD}@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
from database import db
db.init_app(app)

# Import models
from database import Market, WeatherForecast, Signal, Trade, DailyPerformance, BotSetting

# Import collectors
from collectors.noaa_collector import NOAACollector
from collectors.polymarket_collector import PolymarketCollector

# Import analyzers
from analyzers.weather_analyzer import WeatherAnalyzer
from analyzers.arbitrage_calculator import ArbitrageCalculator
from analyzers.risk_manager import RiskManager

# Import executors
from executors.polymarket_trader import PolymarketTrader
from executors.position_tracker import PositionTracker

# Import notifications
from notifications.telegram_bot import TelegramBot

# Register routes
from routes import register_routes
register_routes(app)

# Initialize components
noaa = NOAACollector()
polymarket = PolymarketCollector()
weather_analyzer = WeatherAnalyzer(noaa, polymarket)
arbitrage_calc = ArbitrageCalculator()
risk_mgr = RiskManager()
telegram = TelegramBot()
trader = PolymarketTrader()
position_tracker = PositionTracker()

# Global state
bot_running = False
last_check = None

def initialize_database():
    """Create database tables if they don't exist"""
    with app.app_context():
        try:
            db.create_all()
            logger.info("✅ Database tables created/verified")
            
            # Check if default settings exist
            if BotSetting.query.count() == 0:
                # Insert default settings
                defaults = {
                    'automation_mode': 'semi-auto',
                    'min_edge_pct': '15',
                    'min_confidence_pct': '80',
                    'max_bet_pct': '0.05',
                    'max_daily_trades': '10',
                    'check_interval_hours': '2'
                }
                
                for key, value in defaults.items():
                    setting = BotSetting(setting_key=key, setting_value=value)
                    db.session.add(setting)
                
                db.session.commit()
                logger.info("✅ Default settings inserted")
            
        except Exception as e:
            logger.error(f"❌ Database initialization error: {e}")

def save_market_to_db(market_data):
    """Save market to database"""
    try:
        market = Market.query.filter_by(id=market_data['id']).first()
        
        if not market:
            market = Market(
                id=market_data['id'],
                question=market_data['question'],
                description=market_data.get('description', ''),
                category=market_data.get('category', ''),
                end_date=market_data.get('end_date'),
                volume=market_data.get('volume', 0),
                liquidity=market_data.get('liquidity', 0),
                url=market_data.get('url', '')
            )
            db.session.add(market)
        else:
            # Update existing market
            market.volume = market_data.get('volume', 0)
            market.liquidity = market_data.get('liquidity', 0)
            market.last_checked = datetime.utcnow()
        
        db.session.commit()
        return market
        
    except Exception as e:
        logger.error(f"Error saving market: {e}")
        db.session.rollback()
        return None

def save_forecast_to_db(forecast_data, location):
    """Save weather forecast to database"""
    try:
        for period in forecast_data.get('forecasts', []):
            target_date = datetime.strptime(period['date'], '%Y-%m-%d').date()
            
            # Check if forecast already exists
            existing = WeatherForecast.query.filter_by(
                location=location,
                target_date=target_date
            ).filter(
                WeatherForecast.retrieved_at >= datetime.utcnow().replace(hour=0, minute=0)
            ).first()
            
            if not existing:
                forecast = WeatherForecast(
                    location=location,
                    target_date=target_date,
                    rain_probability=period.get('rain_probability', 0),
                    temperature_high=period.get('temperature_high'),
                    temperature_low=period.get('temperature_low'),
                    conditions=period.get('conditions', ''),
                    detailed=period.get('detailed', ''),
                    source='NOAA'
                )
                db.session.add(forecast)
        
        db.session.commit()
        
    except Exception as e:
        logger.error(f"Error saving forecast: {e}")
        db.session.rollback()

def save_signal_to_db(signal_data):
    """Save trading signal to database"""
    try:
        signal = Signal(
            market_id=signal_data['market_id'],
            location=signal_data['location'],
            target_date=datetime.strptime(signal_data['target_date'], '%Y-%m-%d').date(),
            signal_type=signal_data['signal_type'],
            direction=signal_data['direction'],
            noaa_probability=signal_data['noaa_probability'],
            market_probability=signal_data['market_probability'],
            edge=signal_data['edge'],
            confidence=signal_data['confidence'],
            fair_value=signal_data['fair_value'],
            expected_value=signal_data['expected_value'],
            recommended_bet=signal_data.get('recommended_bet', 0),
            reasoning=signal_data['reasoning'],
            status='pending'
        )
        
        db.session.add(signal)
        db.session.commit()
        
        return signal
        
    except Exception as e:
        logger.error(f"Error saving signal: {e}")
        db.session.rollback()
        return None

def update_daily_performance():
    """Update daily performance summary"""
    try:
        today = date.today()
        
        # Get today's closed trades
        today_trades = Trade.query.filter(
            db.func.date(Trade.closed_at) == today,
            Trade.status == 'closed'
        ).all()
        
        if not today_trades:
            return
        
        # Calculate stats
        total_trades = len(today_trades)
        wins = len([t for t in today_trades if t.outcome == 'WIN'])
        losses = total_trades - wins
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        total_invested = sum(t.bet_size for t in today_trades)
        total_returned = sum(t.payout or 0 for t in today_trades)
        realized_pnl = sum(t.realized_pnl or 0 for t in today_trades)
        roi = (realized_pnl / total_invested * 100) if total_invested > 0 else 0
        
        # Update or create daily performance
        daily_perf = DailyPerformance.query.filter_by(date=today).first()
        
        if not daily_perf:
            daily_perf = DailyPerformance(date=today)
            db.session.add(daily_perf)
        
        daily_perf.total_trades = total_trades
        daily_perf.wins = wins
        daily_perf.losses = losses
        daily_perf.win_rate = win_rate
        daily_perf.total_invested = total_invested
        daily_perf.total_returned = total_returned
        daily_perf.realized_pnl = realized_pnl
        daily_perf.roi = roi
        
        db.session.commit()
        logger.info(f"✅ Daily performance updated: {total_trades} trades, {win_rate:.1f}% WR")
        
    except Exception as e:
        logger.error(f"Error updating daily performance: {e}")
        db.session.rollback()

def scan_for_opportunities():
    """
    Main bot loop - scans for weather arbitrage opportunities
    Runs every 2 hours (configurable)
    """
    global last_check
    
    with app.app_context():
        logger.info("=" * 60)
        logger.info("🔍 SCANNING FOR WEATHER ARBITRAGE OPPORTUNITIES")
        logger.info("=" * 60)
        
        try:
            # Get cities to scan
            cities = ['New York', 'Chicago', 'Miami', 'Los Angeles', 'Seattle']
            
            total_signals = 0
            
            for city in cities:
                logger.info(f"📍 Analyzing {city}...")
                
                # Get forecast
                forecast = noaa.get_forecast(city)
                if forecast:
                    save_forecast_to_db(forecast, city)
                
                # Find opportunities
                signals = weather_analyzer.find_opportunities(city)
                
                if signals:
                    logger.info(f"✅ Found {len(signals)} signal(s) for {city}")
                    
                    for signal in signals:
                        # Save market first
                        market_data = {
                            'id': signal['market_id'],
                            'question': signal['market_question'],
                            'url': signal['market_url'],
                            'volume': signal.get('market_volume', 0),
                            'liquidity': signal.get('market_liquidity', 0),
                            'end_date': signal.get('market_end_date')
                        }
                        save_market_to_db(market_data)
                        
                        # Validate with risk manager
                        is_valid, reason = risk_mgr.validate_signal(signal)
                        
                        if is_valid:
                            # Save signal to database
                            db_signal = save_signal_to_db(signal)
                            
                            if db_signal:
                                # Send Telegram alert
                                telegram.send_signal_alert(signal)
                                total_signals += 1
                                logger.info(f"✅ Signal sent: {signal['market_question'][:50]}...")
                        else:
                            logger.info(f"⏭️  Signal skipped: {reason}")
                else:
                    logger.info(f"ℹ️  No opportunities in {city}")
            
            last_check = datetime.now()
            
            # Update daily performance
            update_daily_performance()
            
            logger.info("=" * 60)
            logger.info(f"✅ Scan complete - {total_signals} signal(s) sent")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"❌ Error during scan: {e}", exc_info=True)

@app.route('/health')
def health():
    """Health check endpoint"""
    with app.app_context():
        try:
            # Check database connection
            db.session.execute(db.text('SELECT 1'))
            db_status = 'connected'
        except:
            db_status = 'disconnected'
        
        return {
            'status': 'healthy',
            'bot_running': bot_running,
            'last_check': str(last_check) if last_check else None,
            'database': db_status,
            'timestamp': datetime.utcnow().isoformat()
        }, 200

@app.route('/api/trigger-scan')
def trigger_scan():
    """Manual trigger for testing"""
    with app.app_context():
        scan_for_opportunities()
        return {'status': 'scan triggered'}, 200

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("🌧️  WEATHER TRADING BOT STARTING")
    logger.info("=" * 60)
    
    try:
        # Initialize database
        logger.info("🗄️  Initializing database...")
        initialize_database()
        
        # Validate configuration
        config.validate_config()
        logger.info("✅ Configuration validated")
        
        # Test Telegram connection
        logger.info("📱 Testing Telegram connection...")
        if telegram.test_connection():
            logger.info("✅ Telegram bot connected")
        else:
            logger.warning("⚠️  Telegram connection failed - alerts disabled")
        
        # Initialize scheduler
        logger.info("⏰ Starting scheduler...")
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            func=scan_for_opportunities,
            trigger="interval",
            seconds=config.CHECK_INTERVAL_SECONDS,
            id='weather_scan',
            name='Weather Arbitrage Scanner'
        )
        scheduler.start()
        bot_running = True
        
        logger.info("✅ Scheduler started")
        logger.info(f"📊 Dashboard: http://localhost:{config.FLASK_PORT}")
        logger.info(f"🤖 Mode: {config.AUTOMATION_MODE}")
        logger.info(f"⏰ Scan interval: {config.CHECK_INTERVAL_SECONDS // 3600} hours")
        logger.info(f"💾 Database: {config.DB_NAME}@{config.DB_HOST}")
        logger.info("=" * 60)
        
        # Run first scan immediately (in app context)
        logger.info("🚀 Running initial scan...")
        with app.app_context():
            scan_for_opportunities()
        
        # Start Flask server
        logger.info("🌐 Starting Flask web server...")
        app.run(
            host='0.0.0.0',
            port=config.FLASK_PORT,
            debug=config.FLASK_DEBUG
        )
        
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Startup error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if 'scheduler' in locals():
            scheduler.shutdown()
            logger.info("⏹️  Scheduler stopped")