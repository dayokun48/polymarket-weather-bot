"""
Configuration file for Polymarket Weather Trading Bot
Loads environment variables from .env file
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Polymarket API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Polymarket Wallet Configuration
WALLET_ADDRESS = os.getenv('WALLET_ADDRESS')
PRIVATE_KEY = os.getenv('PRIVATE_KEY')

# Database Configuration
DB_HOST = os.getenv('DB_HOST', 'mysql-server')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAME = os.getenv('DB_NAME', 'polymarket_weather')

# Bot Configuration
AUTOMATION_MODE = os.getenv('AUTOMATION_MODE', 'semi-auto')
MIN_EDGE_PCT = float(os.getenv('MIN_EDGE_PCT', 15))
MIN_CONFIDENCE_PCT = float(os.getenv('MIN_CONFIDENCE_PCT', 80))
MAX_BET_PCT = float(os.getenv('MAX_BET_PCT', 0.05))
MAX_DAILY_TRADES = int(os.getenv('MAX_DAILY_TRADES', 10))
CHECK_INTERVAL_SECONDS = int(os.getenv('CHECK_INTERVAL_HOURS', 2)) * 3600

# Flask Configuration
FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False') == 'True'
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

# Logging Configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'logs/bot.log')

def validate_config():
    """Validate required configuration"""
    errors = []
    
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN is required")
    
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID is required")
    
    if not DB_PASSWORD:
        errors.append("DB_PASSWORD is required")
    
    if errors:
        raise ValueError(f"Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
    
    print("✅ Configuration valid!")

if __name__ == '__main__':
    # Test configuration
    validate_config()
    print(f"Database: {DB_NAME}@{DB_HOST}:{DB_PORT}")
    print(f"Telegram: {TELEGRAM_BOT_TOKEN[:20]}...")
    print(f"Mode: {AUTOMATION_MODE}")