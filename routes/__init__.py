"""
Flask routes package
"""

from .overview import overview_bp
from .signals import signals_bp
from .positions import positions_bp
from .performance import performance_bp
from .settings import settings_bp

def register_routes(app):
    """Register all blueprints"""
    app.register_blueprint(overview_bp)
    app.register_blueprint(signals_bp)
    app.register_blueprint(positions_bp)
    app.register_blueprint(performance_bp)
    app.register_blueprint(settings_bp)

__all__ = ['register_routes']
