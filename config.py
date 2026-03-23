import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================
# TELEGRAM
# ============================================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# ============================================
# POLYMARKET
# ============================================
GAMMA_API = os.getenv('GAMMA_API', 'https://gamma-api.polymarket.com')
DATA_API = os.getenv('DATA_API', 'https://data-api.polymarket.com')
CLOB_API = os.getenv('CLOB_API', 'https://clob.polymarket.com')

WALLET_ADDRESS = os.getenv('WALLET_ADDRESS', '')
PRIVATE_KEY = os.getenv('PRIVATE_KEY', '')

# ============================================
# WEATHER APIs
# ============================================
NOAA_API = os.getenv('NOAA_API', 'https://api.weather.gov')
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY', '')
OPENWEATHER_API = os.getenv('OPENWEATHER_API', 'https://api.openweathermap.org/data/2.5')

# ============================================
# DATABASE
# ============================================
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'mysql-server'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'polymarket_weather')
}

# ============================================
# BOT SETTINGS
# ============================================
AUTOMATION_MODE = os.getenv('AUTOMATION_MODE', 'semi-auto')

# Risk Management
MAX_BET_PCT = float(os.getenv('MAX_BET_PCT', 0.05))
MIN_EDGE_PCT = float(os.getenv('MIN_EDGE_PCT', 15))
MIN_CONFIDENCE_PCT = float(os.getenv('MIN_CONFIDENCE_PCT', 80))
MAX_DAILY_TRADES = int(os.getenv('MAX_DAILY_TRADES', 10))
MAX_DAILY_LOSS_PCT = float(os.getenv('MAX_DAILY_LOSS_PCT', 0.10))

# Monitoring
CHECK_INTERVAL_SECONDS = int(os.getenv('CHECK_INTERVAL_SECONDS', 7200))
ALERT_COOLDOWN_SECONDS = int(os.getenv('ALERT_COOLDOWN_SECONDS', 300))

# ============================================
# FLASK
# ============================================
FLASK_ENV = os.getenv('FLASK_ENV', 'production')
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False') == 'True'
FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))

# ============================================
# LOGGING
# ============================================
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'logs/weather_bot.log')

# ============================================
# VALIDATION
# ============================================
def validate_config():
    """Validate essential configuration"""
    errors = []
    
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN not set")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID not set")
    if not WALLET_ADDRESS:
        errors.append("WALLET_ADDRESS not set")
    if not PRIVATE_KEY:
        errors.append("PRIVATE_KEY not set")
    if not DB_CONFIG['password']:
        errors.append("DB_PASSWORD not set")
    
    if errors:
        raise ValueError(f"Configuration errors: {', '.join(errors)}")
    
    return True

if __name__ == '__main__':
    try:
        validate_config()
        print("✅ Configuration valid!")
    except ValueError as e:
        print(f"❌ {e}")
