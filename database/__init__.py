"""
Database package
SQLAlchemy models and utilities
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from .models import Market, WeatherForecast, Signal, Trade, DailyPerformance, BotSetting

__all__ = ['db', 'Market', 'WeatherForecast', 'Signal', 'Trade', 'DailyPerformance', 'BotSetting']
