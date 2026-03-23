-- Polymarket Weather Trading Bot
-- Database Schema

CREATE DATABASE IF NOT EXISTS polymarket_weather;
USE polymarket_weather;

-- Markets table
CREATE TABLE IF NOT EXISTS markets (
    id VARCHAR(100) PRIMARY KEY,
    question TEXT NOT NULL,
    description TEXT,
    category VARCHAR(50),
    end_date DATETIME,
    volume FLOAT DEFAULT 0,
    liquidity FLOAT DEFAULT 0,
    url VARCHAR(500),
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_checked DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_category (category),
    INDEX idx_end_date (end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Weather forecasts table
CREATE TABLE IF NOT EXISTS weather_forecasts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    location VARCHAR(100) NOT NULL,
    target_date DATE NOT NULL,
    rain_probability FLOAT,
    temperature_high FLOAT,
    temperature_low FLOAT,
    conditions VARCHAR(200),
    detailed TEXT,
    source VARCHAR(50) DEFAULT 'NOAA',
    retrieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_location_date (location, target_date),
    INDEX idx_target_date (target_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Trading signals table
CREATE TABLE IF NOT EXISTS signals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    market_id VARCHAR(100),
    location VARCHAR(100),
    target_date DATE,
    signal_type VARCHAR(50),
    direction VARCHAR(10),
    noaa_probability FLOAT,
    market_probability FLOAT,
    edge FLOAT,
    confidence FLOAT,
    fair_value FLOAT,
    expected_value FLOAT,
    recommended_bet FLOAT,
    reasoning TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (market_id) REFERENCES markets(id) ON DELETE CASCADE,
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    INDEX idx_edge (edge)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Trades table
CREATE TABLE IF NOT EXISTS trades (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trade_id VARCHAR(100) UNIQUE NOT NULL,
    signal_id INT,
    market_id VARCHAR(100),
    direction VARCHAR(10),
    bet_size FLOAT,
    entry_price FLOAT,
    shares FLOAT,
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'open',
    outcome VARCHAR(10),
    payout FLOAT,
    realized_pnl FLOAT,
    closed_at DATETIME,
    tx_hash VARCHAR(100),
    FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE SET NULL,
    FOREIGN KEY (market_id) REFERENCES markets(id) ON DELETE CASCADE,
    INDEX idx_status (status),
    INDEX idx_executed_at (executed_at),
    INDEX idx_outcome (outcome)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Daily performance table
CREATE TABLE IF NOT EXISTS daily_performance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    total_trades INT DEFAULT 0,
    wins INT DEFAULT 0,
    losses INT DEFAULT 0,
    win_rate FLOAT DEFAULT 0,
    total_invested FLOAT DEFAULT 0,
    total_returned FLOAT DEFAULT 0,
    realized_pnl FLOAT DEFAULT 0,
    roi FLOAT DEFAULT 0,
    INDEX idx_date (date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Bot settings table
CREATE TABLE IF NOT EXISTS bot_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_key (setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Insert default settings
INSERT INTO bot_settings (setting_key, setting_value) VALUES
    ('automation_mode', 'semi-auto'),
    ('min_edge_pct', '15'),
    ('min_confidence_pct', '80'),
    ('max_bet_pct', '0.05'),
    ('max_daily_trades', '10'),
    ('check_interval_hours', '2')
ON DUPLICATE KEY UPDATE setting_key=setting_key;
